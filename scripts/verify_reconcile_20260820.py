# 2026-08-20消し込みの読み戻し検証(読み取りのみ)
import os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CREDS = r"C:\Users\mayth\dev\stock_backtest\credentials\gsa_key.json"
os.environ["GCP_CREDENTIALS_JSON"] = open(CREDS, encoding="utf-8").read()
os.environ["FC_SHEET_ID"] = "1OGQ4Is39LwaidrwQqS_fTu0hodq5bOFZwBKzJlukECE"
os.environ["FC_API_USER"] = "default"

import data

df = data.load_data()
print("総行数:", len(df))
print("現金行残存:", df["銘柄コード"].isin(["現金SBI", "現金野村"]).sum())
m = (df["銘柄コード"] == "eMAXIS") & (df["口座区分"] == "特定口座") & (df["口座"] == "SBI証券")
print(df.loc[m, ["銘柄名", "保有株数", "取得単価", "取得日", "最新更新日"]].to_string())
