"""2026年8月つみたて分の追記: 保有シート口数更新 + TransactionData記録

約定内容(2026/08/12約定・8/17受渡、SBI約定履歴スクショで確認済み):
  SBI・全世界株式インデックス・ファンド  NISA(つみたて)  13,880口 @36,023円  50,000円
  SBI・V・S&P500インデックス・ファンド   NISA(つみたて)   4,831口 @41,402円  20,000円

使い方(リポジトリ直下で):
  python scripts\\add_aug_tsumitate_20260813.py           # dry-run(表示のみ)
  python scripts\\add_aug_tsumitate_20260813.py --apply   # 書込(事前にbackups/へ全値退避)

安全装置: 保有シートの現在値が期待値(下記EXPECTED)と一致しない場合は中断する。
"""
import csv
import json
import os
import sys
import unicodedata
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from parity_check import DEFAULT_CREDS, DEFAULT_SHEET_ID, DEFAULT_USER  # noqa: E402

# ── 追記内容の定義 ──
# (銘柄名の部分一致キー, 期待の現在値[万口, 円/万口], 追加[口, 円/万口])
UPDATES = [
    {"name_key": "全世界株式", "expect_shares": 26.5277, "expect_price": 27707,
     "add_kuchi": 13880, "add_price": 36023, "full_name": "SBI・全世界株式インデックス・ファンド"},
    {"name_key": "V・S&P500", "expect_shares": 21.3571, "expect_price": 30669,
     "add_kuchi": 4831, "add_price": 41402, "full_name": "SBI・V・S&P500インデックス・ファンド"},
]
TRADE_DATE = "2026/08/12"

TX_ROWS = [
    # TRANSACTION_COLS: 日付, 銘柄コード, 銘柄名, 市場, 取引種別, 数量, 単価(円), 手数料, 損益確定(円), 口座, 口座区分
    [TRADE_DATE, "", u["full_name"], "投資信託", "買い増し", u["add_kuchi"], u["add_price"], 0, "", "SBI証券", "NISA(積立投資枠)"]
    for u in UPDATES
]


def main():
    apply = "--apply" in sys.argv

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

    pf_ws = None
    for title in ("PortfolioData", "シート1", "Sheet1"):
        try:
            pf_ws = sh.worksheet(title)
            break
        except gspread.WorksheetNotFound:
            continue
    if pf_ws is None:
        pf_ws = sh.worksheets()[0]
    tx_ws = sh.worksheet("TransactionData")

    pf_vals = pf_ws.get_all_values()
    header = pf_vals[0]
    idx = {c: i for i, c in enumerate(header)}
    for col in ("銘柄名", "口座区分", "保有株数", "取得単価"):
        if col not in idx:
            print(f"中断: 保有シートに列 '{col}' がありません (ヘッダー: {header})")
            sys.exit(1)

    # ── バックアップ(常時、dry-runでも取る) ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("backups", exist_ok=True)
    for label, vals in (("portfolio", pf_vals), ("transactions", tx_ws.get_all_values())):
        path = os.path.join("backups", f"backup_{ts}_{label}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            csv.writer(f).writerows(vals)
        print(f"バックアップ: {path}")

    # ── 対象行の特定と検証 ──
    plans = []
    for u in UPDATES:
        hits = []
        for rno, row in enumerate(pf_vals[1:], start=2):  # 1-indexed + ヘッダー
            name = unicodedata.normalize("NFKC", row[idx["銘柄名"]])
            kubun = row[idx["口座区分"]]
            if u["name_key"] in name and "積立" in kubun:
                hits.append((rno, row))
        if len(hits) != 1:
            print(f"中断: '{u['name_key']}'×積立 の該当行が {len(hits)} 件(期待1件)")
            sys.exit(1)
        rno, row = hits[0]
        cur_shares = float(row[idx["保有株数"]])
        cur_price = float(row[idx["取得単価"]])
        if abs(cur_shares - u["expect_shares"]) > 1e-6 or abs(cur_price - u["expect_price"]) > 0.5:
            print(f"中断: 行{rno} の現在値 {cur_shares}口(万)@{cur_price}円 が期待値 "
                  f"{u['expect_shares']}@{u['expect_price']} と不一致。シートが先に更新された可能性")
            sys.exit(1)
        add_man = u["add_kuchi"] / 10000.0  # 口 → 万口
        new_shares = round(cur_shares + add_man, 4)
        new_price = round((cur_shares * cur_price + add_man * u["add_price"]) / new_shares)
        plans.append({"rno": rno, "u": u, "cur": (cur_shares, cur_price), "new": (new_shares, new_price)})

    print("\n=== 保有シート更新プラン ===")
    for p in plans:
        cs, cp = p["cur"]
        ns, np_ = p["new"]
        print(f"  行{p['rno']} {p['u']['full_name']}")
        print(f"    保有株数: {cs} → {ns} 万口 (+{p['u']['add_kuchi']}口)")
        print(f"    取得単価: {cp:,.0f} → {np_:,.0f} 円 (加重平均)")

    print("\n=== TransactionData 追記プラン ===")
    for r in TX_ROWS:
        amt = r[5] * r[6] / 10000
        print(f"  {r[0]} {r[2]} {r[5]:,}口 @{r[6]:,}円 → つみたて枠消化 +{amt:,.0f}円")

    if not apply:
        print("\n(dry-run: 書込していません。実行するには --apply を付けてください)")
        return

    # ── 書込 ──
    for p in plans:
        ns, np_ = p["new"]
        pf_ws.update_cell(p["rno"], idx["保有株数"] + 1, ns)
        pf_ws.update_cell(p["rno"], idx["取得単価"] + 1, np_)
        if "最新更新日" in idx:
            pf_ws.update_cell(p["rno"], idx["最新更新日"] + 1, datetime.now().strftime("%Y/%m/%d"))
    tx_ws.append_rows(TX_ROWS, value_input_option="USER_ENTERED")

    # ── 書込後検証 ──
    pf_vals2 = pf_ws.get_all_values()
    ok = True
    for p in plans:
        row = pf_vals2[p["rno"] - 1]
        got = (float(row[idx["保有株数"]]), float(row[idx["取得単価"]]))
        if abs(got[0] - p["new"][0]) > 1e-6 or abs(got[1] - p["new"][1]) > 0.5:
            print(f"⚠ 検証NG: 行{p['rno']} 期待{p['new']} 実際{got}")
            ok = False
    tx_tail = tx_ws.get_all_values()[-2:]
    print("\n書込完了。TransactionData末尾2行:")
    for r in tx_tail:
        print(f"  {r}")
    print("検証: " + ("OK — 全て期待値と一致" if ok else "NG — バックアップから確認してください"))
    print("Streamlit側はキャッシュ(120秒)が切れるか「全データ最新化」で反映されます")


if __name__ == "__main__":
    main()
