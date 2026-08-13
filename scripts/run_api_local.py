"""ローカル突合・E2E用のAPIサーバー起動スクリプト(このマシン専用)

外部通信あり(Google Sheets / yfinance / J-Quants)。
認証はローカル限定のテスト資格情報(admin / testpass)を注入する — 本番secretsには触れない。
テスト用ハッシュは rounds=4 の使い捨てで、セキュリティ用途ではない。

APIキーは stock_backtest/.env から環境変数へ読み込む(値は表示しない・ログにも出さない)。
J-Quants CLI はカレントディレクトリの .env を見るため、リポジトリ直下で起動すると
キーが見つからず 403 になる。この読み込みでその問題も解消する。

使い方(リポジトリ直下で): python scripts/run_api_local.py
"""
import os
import secrets
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DEFAULT_SHEET_ID = "1OGQ4Is39LwaidrwQqS_fTu0hodq5bOFZwBKzJlukECE"
DEFAULT_CREDS = r"C:\Users\mayth\Documents\stock_backtest\credentials\gsa_key.json"
DOTENV_PATH = r"C:\Users\mayth\Documents\stock_backtest\.env"
# bcrypt("testpass", rounds=4) — ローカルE2E専用
TEST_HASH = "$2b$04$pgSg0FlKnBZZ1h4ShpkGKev0HK8MhwROekBXm06U6feDTVsd28GOS"

# ── .env 読み込み(値は一切出力しない。存否のみ報告) ──
if os.path.exists(DOTENV_PATH):
    try:
        from dotenv import load_dotenv
        load_dotenv(DOTENV_PATH, override=False)
        found = [k for k in ("JQUANTS_API_KEY", "ANTHROPIC_API_KEY") if os.environ.get(k)]
        missing = [k for k in ("JQUANTS_API_KEY", "ANTHROPIC_API_KEY") if not os.environ.get(k)]
        print(f".env 読込: {DOTENV_PATH}")
        print(f"  設定済み: {', '.join(found) if found else '(なし)'}")
        if missing:
            print(f"  未設定  : {', '.join(missing)}  ← .env のキー名が違う可能性")
    except ImportError:
        print("python-dotenv が未導入のため .env を読み込めません (pip install python-dotenv)")
else:
    print(f".env が見つかりません: {DOTENV_PATH}")

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
