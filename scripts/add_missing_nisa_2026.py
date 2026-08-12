"""2026年NISA買付の欠落分をTransactionDataへ追記する。

出典: SBI約定履歴CSV (SaveFile_000001_000027.csv、2026/01/01-2026/08/13、本人提供)。
欠落12件(成長枠5件・つみたて枠7件)を追記し、NISA枠消化表示を実態に合わせる。
7/10高配当再投資(特定/一般)と7/15特定オルカンはNISA枠対象外のため追記しない。

使い方(リポジトリ直下で):
  python scripts\\add_missing_nisa_2026.py           # dry-run(表示のみ)
  python scripts\\add_missing_nisa_2026.py --apply   # 書込(事前にbackups/へ退避)

安全装置: 追記前のNISA枠消化額が期待値(成長7,890/つみたて350,015)と一致しない場合は中断。
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

from parity_check import DEFAULT_CREDS, DEFAULT_SHEET_ID  # noqa: E402

# ── 追記内容(SBI約定履歴CSVの転記。数量=口, 単価=円/万口) ──
# TRANSACTION_COLS: 日付, 銘柄コード, 銘柄名, 市場, 取引種別, 数量, 単価(円), 手数料, 損益確定(円), 口座, 口座区分
G = "NISA(成長投資枠)"
T = "NISA(積立投資枠)"
TX_ROWS = [
    ["2026/01/06", "", "eMAXIS Slim 全世界株式(オール・カントリー)", "投資信託", "新規購入", 296851, 33687, 0, "", "SBI証券", G],
    ["2026/01/13", "", "SBI日本高配当株式(分配)ファンド(年4回決算型)", "投資信託", "買い増し", 5077, 15401, 0, "", "SBI証券", G],
    ["2026/01/13", "", "SBI・新興国株式インデックス・ファンド", "投資信託", "新規購入", 8998, 22228, 0, "", "SBI証券", T],
    ["2026/01/13", "", "SBI・V・S&P500インデックス・ファンド", "投資信託", "買い増し", 8123, 36932, 0, "", "SBI証券", T],
    ["2026/01/13", "", "SBI・全世界株式インデックス・ファンド", "投資信託", "買い増し", 6236, 32072, 0, "", "SBI証券", T],
    ["2026/01/14", "", "eMAXIS Slim 全世界株式(オール・カントリー)", "投資信託", "買い増し", 8393, 34555, 0, "", "SBI証券", G],
    ["2026/02/10", "", "eMAXIS Slim 全世界株式(オール・カントリー)", "投資信託", "買い増し", 377589, 34429, 0, "", "SBI証券", G],
    ["2026/02/10", "", "SBI・V・S&P500インデックス・ファンド", "投資信託", "買い増し", 5499, 36375, 0, "", "SBI証券", T],
    ["2026/02/10", "", "SBI・全世界株式インデックス・ファンド", "投資信託", "買い増し", 15528, 32201, 0, "", "SBI証券", T],
    ["2026/05/12", "", "SBI・V・S&P500インデックス・ファンド", "投資信託", "買い増し", 5111, 39133, 0, "", "SBI証券", T],
    ["2026/05/12", "", "SBI・全世界株式インデックス・ファンド", "投資信託", "買い増し", 14615, 34212, 0, "", "SBI証券", T],
    ["2026/06/30", "", "eMAXIS Slim 全世界株式(オール・カントリー)", "投資信託", "買い増し", 13152, 38017, 0, "", "SBI証券", G],
]

EXPECT_BEFORE = (7890, 350015)   # 追記前の(成長, つみたて)消化額(円, 四捨五入)
YEAR = 2026


def calc_usage(rows, header):
    """calc_nisa_usage と同一仕様の簡易再現(gspread生値ベース)。"""
    idx = {c: i for i, c in enumerate(header)}
    g = t = 0.0
    for row in rows:
        date, kbn, kind = row[idx["日付"]], row[idx["口座区分"]], row[idx["取引種別"]]
        if f"{YEAR}" not in date or "NISA" not in kbn or kind not in ("買い増し", "新規購入"):
            continue
        try:
            qty = float(str(row[idx["数量"]]).replace(",", ""))
            price = float(str(row[idx["単価(円)"]]).replace(",", ""))
        except ValueError:
            continue
        amt = qty * price
        code = row[idx["銘柄コード"]].strip()
        norm = unicodedata.normalize("NFKC", row[idx["銘柄名"]])
        if (row[idx["市場"]] == "投資信託") or ("積立" in kbn) or (
                not code[:1].isdigit() and ("ファンド" in norm or "インデックス" in norm)):
            amt /= 10000
        if "成長" in kbn:
            g += amt
        elif "積立" in kbn:
            t += amt
    return g, t


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
    tx_ws = sh.worksheet("TransactionData")

    vals = tx_ws.get_all_values()
    header = vals[0]

    # ── バックアップ(常時) ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("backups", exist_ok=True)
    path = os.path.join("backups", f"backup_{ts}_transactions.csv")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        csv.writer(f).writerows(vals)
    print(f"バックアップ: {path}")

    # ── 事前検証: 現在の消化額が期待値か / 追記対象が既に存在しないか ──
    g0, t0 = calc_usage(vals[1:], header)
    print(f"追記前の枠消化: 成長 {g0:,.0f}円 / つみたて {t0:,.0f}円")
    if round(g0) != EXPECT_BEFORE[0] or round(t0) != EXPECT_BEFORE[1]:
        print(f"中断: 期待値 {EXPECT_BEFORE} と不一致。シートが先に更新された可能性")
        sys.exit(1)
    idx = {c: i for i, c in enumerate(header)}
    existing = {(r[idx["日付"]], str(r[idx["数量"]]).replace(",", ""), r[idx["口座区分"]]) for r in vals[1:]}
    dup = [r for r in TX_ROWS if (r[0], str(r[5]), r[10]) in existing]
    if dup:
        print(f"中断: 追記対象 {len(dup)} 件が既にシートに存在({dup[0][0]} 等)。二重実行の可能性")
        sys.exit(1)

    g1, t1 = calc_usage(vals[1:] + [[str(c) for c in r] for r in TX_ROWS], header)
    print("\n=== TransactionData 追記プラン(12件) ===")
    for r in TX_ROWS:
        amt = r[5] * r[6] / 10000
        waku = "成長" if "成長" in r[10] else "つみたて"
        print(f"  {r[0]} [{r[4]}] {r[2]} {r[5]:,}口 @{r[6]:,}円 → {waku}枠 +{amt:,.0f}円")
    print(f"\n追記後の枠消化見込み: 成長 {g1:,.0f}円({g1/2400000*100:.1f}%) / "
          f"つみたて {t1:,.0f}円({t1/1200000*100:.1f}%)")
    print(f"SBI実績(受渡金額ベース): 成長 2,394,707円 / つみたて 560,000円 (差は口数×単価の丸め)")

    if not apply:
        print("\n(dry-run: 書込していません。実行するには --apply を付けてください)")
        return

    # ── 書込 ──
    tx_ws.append_rows(TX_ROWS, value_input_option="USER_ENTERED")

    # ── 書込後検証 ──
    vals2 = tx_ws.get_all_values()
    g2, t2 = calc_usage(vals2[1:], header)
    n_added = len(vals2) - len(vals)
    print(f"\n書込完了: {n_added}行追加(期待12)")
    print(f"再計算: 成長 {g2:,.0f}円 / つみたて {t2:,.0f}円")
    ok = n_added == 12 and abs(g2 - g1) < 1 and abs(t2 - t1) < 1
    print("検証: " + ("OK — 全て期待値と一致" if ok else "NG — バックアップから確認してください"))
    print("Streamlit側はキャッシュが切れるか「全データ最新化」で反映されます")


if __name__ == "__main__":
    main()
