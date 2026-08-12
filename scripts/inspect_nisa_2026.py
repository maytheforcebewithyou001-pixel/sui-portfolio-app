"""2026年NISA枠消化の実データ点検(読み取り専用)。

TransactionData の2026年NISA買付行を全件表示し、calc_nisa_usage と同一ロジックで
成長枠/つみたて枠の消化額を再現する。書込は一切しない。
"""
import json
import os
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from parity_check import DEFAULT_CREDS, DEFAULT_SHEET_ID  # noqa: E402


def main():
    if os.path.exists(DEFAULT_CREDS) and not os.environ.get("GCP_CREDENTIALS_JSON"):
        with open(DEFAULT_CREDS, encoding="utf-8") as f:
            os.environ["GCP_CREDENTIALS_JSON"] = f.read()

    import gspread
    from google.oauth2.service_account import Credentials
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GCP_CREDENTIALS_JSON"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"])
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(DEFAULT_SHEET_ID)
    tx_ws = sh.worksheet("TransactionData")
    vals = tx_ws.get_all_values()
    header = vals[0]
    idx = {c: i for i, c in enumerate(header)}
    print(f"ヘッダー: {header}")
    print(f"総行数: {len(vals) - 1}")

    g_used = t_used = 0.0
    print("\n=== 2026年・NISA関連の全取引行 ===")
    for rno, row in enumerate(vals[1:], start=2):
        date = row[idx["日付"]]
        kbn = row[idx["口座区分"]] if "口座区分" in idx else ""
        if "2026" not in date or "NISA" not in kbn:
            continue
        kind = row[idx["取引種別"]]
        name = row[idx["銘柄名"]]
        code = row[idx["銘柄コード"]].strip()
        mkt = row[idx["市場"]]
        try:
            qty = float(str(row[idx["数量"]]).replace(",", ""))
            price = float(str(row[idx["単価(円)"]]).replace(",", ""))
        except ValueError:
            qty = price = float("nan")
        amt = qty * price
        norm = unicodedata.normalize("NFKC", name)
        fund = (mkt == "投資信託") or ("積立" in kbn) or (
            not code[:1].isdigit() and ("ファンド" in norm or "インデックス" in norm))
        if fund:
            amt /= 10000
        counted = kind in ("買い増し", "新規購入")
        print(f"  行{rno} {date} [{kind}] {name} 数量{qty:,.0f} @ {price:,.2f} "
              f"kbn={kbn} 市場={mkt} 投信={fund} → 枠消化 {amt:,.0f}円"
              f"{'' if counted else ' (対象外: 取引種別)'}")
        if counted:
            if "成長" in kbn:
                g_used += amt
            elif "積立" in kbn:
                t_used += amt

    print(f"\n成長枠消化: {g_used:,.0f}円 / つみたて枠消化: {t_used:,.0f}円")


if __name__ == "__main__":
    main()
