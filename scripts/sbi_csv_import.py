"""SBI証券CSVの統合取込: 約定履歴→TransactionData追記+保有更新、分配金履歴→年間配当金更新。

対象CSV(リポジトリ直下、最新のタイムスタンプのものを自動選択):
  SaveFile*.csv      投資信託の約定履歴(cp932)。投信金額買付/分配金再投資を取り込む
  DISTRIBUTION*.csv  配当金・分配金履歴(cp932)。投信の分配実績から年間配当金(円/万口)を再計算

処理内容:
  1. TransactionData追記: CSVの買付系明細のうちシート未記録のもの(日付+数量+口座区分で重複判定)
  2. 保有シート更新: 1のうち「シート既存取引の最新約定日より後」の明細のみ口数加算+取得単価加重平均
     (それ以前の明細は証券突合済みの保有に反映済みとみなし、二重計上を防ぐ)
  3. 年間配当金更新: 投信ごとに直近分配(円/万口)×直近365日の分配回数。NISA受取=税引前をそのまま、
     特定受取は÷0.79685で税引前換算。配当月も実績月で更新

使い方(リポジトリ直下で):
  python scripts\\sbi_csv_import.py           # dry-run(表示のみ)
  python scripts\\sbi_csv_import.py --apply   # 書込(事前にbackups/へ全値退避)
"""
import csv
import glob
import io
import json
import os
import re
import sys
import unicodedata
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from parity_check import DEFAULT_CREDS, DEFAULT_SHEET_ID  # noqa: E402

KBN_MAP = {"NISA(成)": "NISA(成長投資枠)", "NISA(つ)": "NISA(積立投資枠)", "特定/一般": "特定口座"}
BUY_KINDS = ("投信金額買付", "投信口数買付", "分配金再投資")
TAX_RATE = 0.20315


def norm(s):
    """NFKC正規化+空白除去。CSV(全角)とシート(半角)の銘柄名表記揺れを吸収する。"""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(s))).strip()


def same_fund(csv_name, sheet_name):
    a, b = norm(csv_name), norm(sheet_name)
    return a == b or a.startswith(b) or b.startswith(a)


def parse_date(s):
    s = str(s).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def to_num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def read_sjis_csv(path):
    raw = open(path, "rb").read()
    for enc in ("cp932", "utf-8-sig", "utf-8"):
        try:
            return list(csv.reader(io.StringIO(raw.decode(enc))))
        except UnicodeDecodeError:
            continue
    raise RuntimeError(f"デコード不能: {path}")


def latest_file(pattern):
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def parse_savefile(rows):
    """約定履歴 → [{date, name, kind, qty(口), price(円/万口), kbn}]。買付系のみ、対象外はskippedへ。"""
    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0].strip() == "約定日":
            header_idx = i
            break
    if header_idx is None:
        raise RuntimeError("SaveFile: ヘッダー行(約定日)が見つからない")
    h = {c.strip(): k for k, c in enumerate(rows[header_idx])}
    out, skipped = [], []
    for row in rows[header_idx + 1:]:
        if len(row) < len(h) or not row[h["約定日"]].strip():
            continue
        date = parse_date(row[h["約定日"]])
        kind = row[h["取引"]].strip()
        azukari = row[h["預り"]].strip()
        name = row[h["銘柄"]].strip()
        if kind not in BUY_KINDS or azukari not in KBN_MAP:
            skipped.append(f"{date} [{kind}/{azukari}] {name}")
            continue
        qty, price = to_num(row[h["約定数量"]]), to_num(row[h["約定単価"]])
        if date is None or not qty or not price:
            skipped.append(f"(数値不正) {row}")
            continue
        out.append({"date": date, "name": name, "kind": kind, "qty": int(qty),
                    "price": price, "kbn": KBN_MAP[azukari]})
    return out, skipped


def parse_distribution(rows):
    """分配金履歴 → 投信のみ [{date, account, name, qty(口), amount(税引後円)}]"""
    header_idx = None
    for i, row in enumerate(rows):
        if row and row[0].strip() == "受渡日":
            header_idx = i  # 明細ヘッダーは「受渡日,口座,商品,...」の方(列数で判別)
            if len(row) >= 6:
                break
    if header_idx is None:
        raise RuntimeError("DISTRIBUTION: 明細ヘッダーが見つからない")
    h = {c.strip(): k for k, c in enumerate(rows[header_idx])}
    out = []
    for row in rows[header_idx + 1:]:
        if len(row) < len(h) or row[h["商品"]].strip() != "投資信託":
            continue
        date = parse_date(row[h["受渡日"]])
        qty = to_num(row[h["数量"]])
        amount = to_num(row[h["受取額(税引後・円)"]])
        if date is None or not qty or not amount:
            continue
        out.append({"date": date, "account": row[h["口座"]].strip(),
                    "name": row[h["銘柄名"]].strip(), "qty": qty, "amount": amount})
    return out


def calc_annual_dividends(dists):
    """投信ごとに 直近分配(円/万口, 税引前)×直近365日の回数 と実績月を返す。"""
    by_fund = {}
    for d in dists:
        by_fund.setdefault(norm(d["name"]), []).append(d)
    result = {}
    for key, ds in by_fund.items():
        ds.sort(key=lambda d: d["date"])
        latest = ds[-1]
        gross = latest["amount"] if "NISA" in latest["account"] else latest["amount"] / (1 - TAX_RATE)
        rate = gross / (latest["qty"] / 10000)  # 円/万口(税引前)
        recent = [d for d in ds if d["date"] > latest["date"] - timedelta(days=365)]
        months = sorted({d["date"].month for d in recent})
        result[key] = {"name": latest["name"], "rate": rate, "times": len(recent),
                       "annual": round(rate * len(recent)), "months": ",".join(map(str, months)),
                       "latest_date": latest["date"]}
    return result


def main():
    apply = "--apply" in sys.argv
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    sf_path = latest_file(os.path.join(root, "SaveFile*.csv"))
    di_path = latest_file(os.path.join(root, "DISTRIBUTION*.csv"))
    if not sf_path and not di_path:
        print("中断: SaveFile*.csv / DISTRIBUTION*.csv がリポジトリ直下に見つからない")
        sys.exit(1)
    print(f"約定履歴: {os.path.basename(sf_path) if sf_path else '(なし→取引取込スキップ)'}")
    print(f"分配金履歴: {os.path.basename(di_path) if di_path else '(なし→配当更新スキップ)'}")

    if os.path.exists(DEFAULT_CREDS) and not os.environ.get("GCP_CREDENTIALS_JSON"):
        with open(DEFAULT_CREDS, encoding="utf-8") as f:
            os.environ["GCP_CREDENTIALS_JSON"] = f.read()
    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_CREDENTIALS_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(DEFAULT_SHEET_ID)
    tx_ws = sh.worksheet("TransactionData")
    pf_ws = None
    for title in ("PortfolioData", "シート1", "Sheet1"):
        try:
            pf_ws = sh.worksheet(title)
            break
        except gspread.WorksheetNotFound:
            continue
    if pf_ws is None:
        pf_ws = sh.worksheets()[0]

    tx_vals = tx_ws.get_all_values()
    pf_vals = pf_ws.get_all_values()
    tx_h = {c: i for i, c in enumerate(tx_vals[0])}
    pf_h = {c: i for i, c in enumerate(pf_vals[0])}

    # ── バックアップ(常時) ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(os.path.join(root, "backups"), exist_ok=True)
    for label, vals in (("transactions", tx_vals), ("portfolio", pf_vals)):
        path = os.path.join(root, "backups", f"backup_{ts}_{label}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(vals)
        print(f"バックアップ: {path}")

    # ── 1. 約定履歴 → TransactionData 追記候補 ──
    new_tx, holdings_plans, warns = [], [], []
    if sf_path:
        trades, skipped = parse_savefile(read_sjis_csv(sf_path))
        existing = set()
        max_tx_date = None
        for r in tx_vals[1:]:
            d = parse_date(r[tx_h["日付"]])
            q = to_num(r[tx_h["数量"]])
            if d and q is not None:
                existing.add((d, int(q), r[tx_h["口座区分"]].strip()))
                max_tx_date = d if max_tx_date is None or d > max_tx_date else max_tx_date
        print(f"\nシート既存取引: {len(tx_vals) - 1}件 (最新約定日 {max_tx_date})")
        if skipped:
            print(f"取込対象外(買付系以外・旧NISA等): {len(skipped)}件")
            for s in skipped:
                print(f"  - {s}")

        seen = set()
        for t in trades:
            key = (t["date"], t["qty"], t["kbn"])
            if key in existing or key in seen:
                continue
            seen.add(key)
            # 保有行の照合: 銘柄名×口座区分で一意なら特定
            hits = [(rno, row) for rno, row in enumerate(pf_vals[1:], start=2)
                    if same_fund(t["name"], row[pf_h["銘柄名"]]) and row[pf_h["口座区分"]].strip() == t["kbn"]]
            kind = "買い増し" if hits else "新規購入"
            new_tx.append([t["date"].strftime("%Y/%m/%d"), "", unicodedata.normalize("NFKC", t["name"]),
                           "投資信託", kind, t["qty"], int(t["price"]), 0, "", "SBI証券", t["kbn"]])
            # 保有更新は「既存取引の最新約定日より後」のみ(過去分は証券突合済みの保有に反映済み)
            if max_tx_date is None or t["date"] > max_tx_date:
                if len(hits) == 1:
                    rno, row = hits[0]
                    cur_s, cur_p = to_num(row[pf_h["保有株数"]]), to_num(row[pf_h["取得単価"]])
                    add_man = t["qty"] / 10000.0
                    new_s = round(cur_s + add_man, 4)
                    new_p = round((cur_s * cur_p + add_man * t["price"]) / new_s)
                    holdings_plans.append({"rno": rno, "name": row[pf_h["銘柄名"]], "kbn": t["kbn"],
                                           "cur": (cur_s, cur_p), "new": (new_s, new_p)})
                else:
                    warns.append(f"保有更新スキップ({len(hits)}行ヒット、手動反映要): {t['date']} {t['name']} [{t['kbn']}] {t['qty']:,}口")
            elif not hits:
                warns.append(f"保有行なしの過去取引(要確認): {t['date']} {t['name']} [{t['kbn']}]")

    print(f"\n=== 1. TransactionData 追記プラン: {len(new_tx)}件 ===")
    for r in new_tx:
        print(f"  {r[0]} [{r[4]}] {r[2]} {r[5]:,}口 @{r[6]:,}円 [{r[10]}] → 取得対価 {r[5]*r[6]/10000:,.0f}円")
    print(f"\n=== 2. 保有シート更新プラン: {len(holdings_plans)}件 ===")
    for p in holdings_plans:
        print(f"  行{p['rno']} {p['name']} [{p['kbn']}]: 保有 {p['cur'][0]} → {p['new'][0]} 万口 / 単価 {p['cur'][1]:,.0f} → {p['new'][1]:,.0f}円")

    # ── 3. 分配金履歴 → 年間配当金更新候補 ──
    div_plans = []
    if di_path:
        dists = parse_distribution(read_sjis_csv(di_path))
        annuals = calc_annual_dividends(dists)
        print(f"\n=== 3. 年間配当金 更新プラン (投信の分配実績 {len(dists)}件から) ===")
        for key, a in annuals.items():
            print(f"  {a['name']}: 直近 {a['rate']:,.1f}円/万口 × 年{a['times']}回 = {a['annual']}円 (配当月 {a['months']}, 直近受渡 {a['latest_date']})")
            for rno, row in enumerate(pf_vals[1:], start=2):
                if not same_fund(a["name"], row[pf_h["銘柄名"]]):
                    continue
                cur_div = to_num(row[pf_h["年間配当金(円/株)"]]) or 0
                cur_mon = row[pf_h["配当月"]].strip()
                if round(cur_div) != a["annual"] or cur_mon != a["months"]:
                    div_plans.append({"rno": rno, "name": row[pf_h["銘柄名"]], "kbn": row[pf_h["口座区分"]],
                                      "div": (round(cur_div), a["annual"]), "mon": (cur_mon, a["months"])})
        if not div_plans:
            print("  → シートは全行最新。変更なし")
        for p in div_plans:
            print(f"  行{p['rno']} {p['name']} [{p['kbn']}]: 年間配当金 {p['div'][0]} → {p['div'][1]} / 配当月 {p['mon'][0]!r} → {p['mon'][1]!r}")

    for w in warns:
        print(f"⚠ {w}")
    if not (new_tx or holdings_plans or div_plans):
        print("\n変更なし。全データはシートと一致しているわ")
        return
    if not apply:
        print("\n(dry-run: 書込していません。実行するには --apply を付けてください)")
        return

    # ── 書込 ──
    if new_tx:
        tx_ws.append_rows(new_tx, value_input_option="USER_ENTERED")
    today = datetime.now().strftime("%Y/%m/%d")
    for p in holdings_plans:
        pf_ws.update_cell(p["rno"], pf_h["保有株数"] + 1, p["new"][0])
        pf_ws.update_cell(p["rno"], pf_h["取得単価"] + 1, p["new"][1])
        if "最新更新日" in pf_h:
            pf_ws.update_cell(p["rno"], pf_h["最新更新日"] + 1, today)
    for p in div_plans:
        pf_ws.update_cell(p["rno"], pf_h["年間配当金(円/株)"] + 1, p["div"][1])
        pf_ws.update_cell(p["rno"], pf_h["配当月"] + 1, p["mon"][1])

    # ── 書込後検証 ──
    ok = True
    n_added = len(tx_ws.get_all_values()) - len(tx_vals)
    if n_added != len(new_tx):
        print(f"⚠ 検証NG: 追記 {n_added}行(期待{len(new_tx)})")
        ok = False
    pf_vals2 = pf_ws.get_all_values()
    for p in holdings_plans:
        row = pf_vals2[p["rno"] - 1]
        if abs(to_num(row[pf_h["保有株数"]]) - p["new"][0]) > 1e-6 or abs(to_num(row[pf_h["取得単価"]]) - p["new"][1]) > 0.5:
            print(f"⚠ 検証NG: 保有行{p['rno']}")
            ok = False
    for p in div_plans:
        row = pf_vals2[p["rno"] - 1]
        if round(to_num(row[pf_h["年間配当金(円/株)"]]) or -1) != p["div"][1]:
            print(f"⚠ 検証NG: 配当行{p['rno']}")
            ok = False
    print(f"\n書込完了: TX追記{len(new_tx)}件 / 保有更新{len(holdings_plans)}件 / 配当更新{len(div_plans)}件")
    print("検証: " + ("OK — 全て期待値と一致" if ok else "NG — バックアップから確認してください"))
    print("Streamlit側はキャッシュが切れるか「全データ最新化」で反映されます")


if __name__ == "__main__":
    main()
