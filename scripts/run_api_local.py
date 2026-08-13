"""ローカル突合・E2E用のAPIサーバー起動スクリプト(このマシン専用)

外部通信あり(Google Sheets / yfinance / J-Quants)。
認証はローカル限定のテスト資格情報(admin / testpass)を注入する — 本番secretsには触れない。
テスト用ハッシュは rounds=4 の使い捨てで、セキュリティ用途ではない。

使い方(リポジトリ直下で): python scripts/run_api_local.py
"""
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_SHEET_ID = "1OGQ4Is39LwaidrwQqS_fTu0hodq5bOFZwBKzJlukECE"
DEFAULT_CREDS = r"C:\Users\mayth\Documents\stock_backtest\credentials\gsa_key.json"
# bcrypt("testpass", rounds=4) — ローカルE2E専用
TEST_HASH = "$2b$04$pgSg0FlKnBZZ1h4ShpkGKev0HK8MhwROekBXm06U6feDTVsd28GOS"

if not os.environ.get("GCP_CREDENTIALS_JSON") and os.path.exists(DEFAULT_CREDS):
    with open(DEFAULT_CREDS, encoding="utf-8") as f:
        os.environ["GCP_CREDENTIALS_JSON"] = f.read()

os.environ.setdefault("FC_API_USER", "admin")
os.environ.setdefault("FC_SHEET_ID", DEFAULT_SHEET_ID)
os.environ.setdefault("FC_TOKEN_SECRET", secrets.token_hex(32))
os.environ.setdefault("FC_AUTH_USERNAME", "admin")
os.environ.setdefault("FC_AUTH_PASSWORD_HASH", TEST_HASH)

import uvicorn  # noqa: E402

uvicorn.run("api.main:app", host="127.0.0.1", port=8000, log_level="warning")
