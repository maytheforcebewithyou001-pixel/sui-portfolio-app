"""P3-1 突合スクリプト: APIパイプラインの計算結果を表示し、Streamlit版ヘッダーと目視比較する

外部通信あり(Google Sheets / yfinance / J-Quants)。
secrets はローカルの .streamlit/secrets.toml から st.secrets 経由で読まれる
(環境変数 GCP_CREDENTIALS_JSON が設定されていればそちらを優先)。

使い方(リポジトリ直下で):
  set FC_API_USER=admin && python scripts/parity_check.py
比較方法: Streamlit版を開いてヘッダーの評価額・損益・年間配当・銘柄数と見比べる。
価格更新タイミングの差による±0.1%程度のズレは許容、それ以上は要調査。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # cp932コンソールでの¥・全角出力対策

from api.service import build_snapshot  # noqa: E402


# このマシン用の既定値(引数・環境変数があればそちらを優先)
DEFAULT_USER = "admin"
DEFAULT_SHEET_ID = "1OGQ4Is39LwaidrwQqS_fTu0hodq5bOFZwBKzJlukECE"
DEFAULT_CREDS = r"C:\Users\mayth\dev\stock_backtest\credentials\gsa_key.json"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--creds", default=None, help="GCPサービスアカウントJSONのパス(GCP_CREDENTIALS_JSON環境変数の代わり)")
    args = parser.parse_args()

    creds_path = args.creds or (DEFAULT_CREDS if os.path.exists(DEFAULT_CREDS) else None)
    if creds_path and not os.environ.get("GCP_CREDENTIALS_JSON"):
        with open(creds_path, encoding="utf-8") as f:
            os.environ["GCP_CREDENTIALS_JSON"] = f.read()

    os.environ.setdefault("FC_API_USER", DEFAULT_USER)
    os.environ.setdefault("FC_SHEET_ID", DEFAULT_SHEET_ID)
    user = os.environ["FC_API_USER"]
    print(f"ユーザー '{user}' のスナップショットを構築中...")
    snap = build_snapshot()
    t = snap["totals"]
    print()
    print("=== FORCE CAPITAL パリティチェック (APIパイプライン) ===")
    print(f"評価額(証券)     : ¥{t['total_asset']:,.0f}")
    print(f"現金             : ¥{t['cash_jpy']:,.0f}")
    print(f"評価額(現金込み) : ¥{t['total_asset_all']:,.0f}")
    print(f"損益(税引後)     : ¥{t['total_net_profit']:,.0f}")
    print(f"損益(含み)       : ¥{t['total_gross_profit']:,.0f}")
    print(f"年間配当(税引前) : ¥{t['total_dividend']:,.0f} ({t['avg_dividend_yield']:.2f}%)")
    print(f"年間配当(税引後) : ¥{t['total_dividend_after_tax']:,.0f}  ← ヘッダーの「年間配当」はこちら(app.py:313 tda)")
    print(f"米国株 株価損益  : ¥{t['total_stock_gain']:,.0f}")
    print(f"米国株 為替損益  : ¥{t['total_fx_gain']:,.0f}")
    print(f"銘柄数           : {t['stock_count']}")
    print(f"USD/JPY          : {snap['jpy_usd_rate']:.2f}")
    print(f"GAS最終更新      : {snap['gas_last_updated']}")
    for w in snap["warnings"]:
        print(f"⚠ {w}")
    print()
    print("→ Streamlit版ヘッダーの同項目と比較してください")


if __name__ == "__main__":
    main()
