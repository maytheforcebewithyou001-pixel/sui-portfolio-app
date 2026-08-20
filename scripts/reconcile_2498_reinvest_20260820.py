# 2498売却手取りの再投資消し込み(2026-08-20、概算)
# 現金SBI/現金野村の2行を削除し、eMAXIS特定口座(SBI)へ買付分を加算する。
# 口数はSBI注文照会の見積基準価額38,525円による概算。約定通知で確定後に微修正する。
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CREDS = r"C:\Users\mayth\dev\stock_backtest\credentials\gsa_key.json"
os.environ["GCP_CREDENTIALS_JSON"] = open(CREDS, encoding="utf-8").read()
os.environ["FC_SHEET_ID"] = "1OGQ4Is39LwaidrwQqS_fTu0hodq5bOFZwBKzJlukECE"
os.environ["FC_API_USER"] = "default"

import data

BACKUP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "backups", "PortfolioData_20260820_before_reinvest_reconcile.json")

BUY_TOTAL = 3_346_560 + 1_670_556   # SBI注文照会 #182+#183 実額
EST_NAV = 38_525                    # 見積基準価額(円/万口)

sh = data.get_spreadsheet()
ws = sh.worksheet("PortfolioData")
values = ws.get_all_values()
with open(BACKUP, "w", encoding="utf-8") as f:
    json.dump(values, f, ensure_ascii=False, indent=1)
print(f"バックアップ保存: {BACKUP} ({len(values)}行)")

df = data.load_data()
n_before = len(df)

# 消し込み対象: 現金SBI/現金野村(8/19に追加した待機現金2行)
cash = df["銘柄コード"].isin(["現金SBI", "現金野村"])
assert cash.sum() == 2, f"現金行が2行でない: {cash.sum()}"
print("削除行:")
print(df.loc[cash, ["銘柄コード", "銘柄名", "取得単価"]].to_string())

# 加算対象: eMAXIS特定口座(SBI)
tgt = (df["銘柄コード"] == "eMAXIS") & (df["口座"] == "SBI証券") & (df["口座区分"] == "特定口座")
assert tgt.sum() == 1, f"eMAXIS特定(SBI)行が一意でない: {tgt.sum()}"
i = df.index[tgt][0]
old_units = float(df.at[i, "保有株数"])
old_price = float(df.at[i, "取得単価"])
add_units = round(BUY_TOTAL / EST_NAV, 4)          # 万口
new_units = round(old_units + add_units, 4)
new_price = round((old_units * old_price + BUY_TOTAL) / new_units)
print(f"eMAXIS特定(SBI): {old_units}万口@{old_price:.0f} → {new_units}万口@{new_price} (+{add_units}万口)")

df.at[i, "保有株数"] = new_units
df.at[i, "取得単価"] = new_price
df.at[i, "最新更新日"] = "2026/8/20"
df = df.loc[~cash].reset_index(drop=True)

assert ws.title == sh.sheet1.title == "PortfolioData", "sheet1がPortfolioDataでない"
data.save_data(df)
print(f"保存完了: {n_before}行 → {len(df)}行")
