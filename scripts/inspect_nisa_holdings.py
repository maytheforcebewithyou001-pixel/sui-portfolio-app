"""保有シート(PortfolioData)のNISA行を点検する(読み取り専用)。

欠落しているNISA取引(年初成長枠・1/2/5月つみたて)を逆算するための材料集め。
"""
import json
import os
import sys

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

    pf_ws = None
    for title in ("PortfolioData", "シート1", "Sheet1"):
        try:
            pf_ws = sh.worksheet(title)
            break
        except gspread.WorksheetNotFound:
            continue
    if pf_ws is None:
        pf_ws = sh.worksheets()[0]

    vals = pf_ws.get_all_values()
    header = vals[0]
    idx = {c: i for i, c in enumerate(header)}
    print(f"ヘッダー: {header}\n")
    print("=== NISA口座の保有行 ===")
    for rno, row in enumerate(vals[1:], start=2):
        kbn = row[idx["口座区分"]] if "口座区分" in idx else ""
        if "NISA" not in kbn:
            continue
        cells = {c: row[idx[c]] for c in header if c in idx}
        shares = cells.get("保有株数", "")
        price = cells.get("取得単価", "")
        try:
            cost = float(shares) * float(price)
        except ValueError:
            cost = float("nan")
        print(f"  行{rno} {cells.get('銘柄名','')} [{kbn}] 保有 {shares} @ {price} "
              f"取得日={cells.get('取得日','')} → 取得コスト {cost:,.0f}円")


if __name__ == "__main__":
    main()
