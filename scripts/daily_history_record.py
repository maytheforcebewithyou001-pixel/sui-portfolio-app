"""日次資産記録 (HistoryData 自動追記)

Streamlit 版の「💾 記録」ボタン(app.py→data.save_history)が手動のため、資産推移の
データ点がアクセス日しか残らない問題への対処。毎朝 07:00 にその時点の評価額を
HistoryData シートへ自動追記する(タスクスケジューラ FC_DailyHistoryRecord)。

- 値の正: Cloud Run 本番 /api/portfolio の totals.total_asset_all(現金込み・
  画面表示と同一定義)。07:00 のリクエストが marketstore の朝境界(06:10)更新を
  兼ねるため、07:10 の日次3点チェックのキャッシュ温めにもなる
- 認証: パスワード非保存。fc-token-secret を gcloud で実行時取得し自前署名
  (daily_3point_check.py と同一。シークレットは末尾改行ごと鍵なので無加工で使う)
- 書込: data.save_history() を流用(手動ボタンと完全に同じ追記経路・同じ日付書式)。
  同日の行が既にあればスキップ(手動記録との二重追記防止)
- 出力: %LOCALAPPDATA%\\fc_checks\\daily_history_log.csv に追記。
  失敗時はデスクトップに FC_資産記録NG_<日付>.txt を生成

使い方(リポジトリ直下): python scripts/daily_history_record.py [--dry-run]
外部通信あり(Secret Manager / Cloud Run / Google Sheets)。
"""
import csv
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROD_API = "https://fc-api-bop3i2fmpa-an.a.run.app"
ADMIN_SHEET_ID = "1OGQ4Is39LwaidrwQqS_fTu0hodq5bOFZwBKzJlukECE"
DEFAULT_CREDS = r"C:\Users\mayth\dev\stock_backtest\credentials\gsa_key.json"
LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "fc_checks")
LOG_PATH = os.path.join(LOG_DIR, "daily_history_log.csv")


def mint_token() -> str:
    gcloud = r"C:\Users\mayth\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    if not os.path.exists(gcloud):
        gcloud = "gcloud"
    r = subprocess.run(
        [gcloud, "secrets", "versions", "access", "latest", "--secret", "fc-token-secret"],
        capture_output=True, text=False, shell=True,
    )
    secret = r.stdout.decode()
    if r.returncode != 0 or not secret:
        raise RuntimeError(f"fc-token-secret 取得失敗 (gcloud rc={r.returncode})")
    os.environ["FC_TOKEN_SECRET"] = secret
    from api import auth
    return auth.issue_token("admin")


def fetch_total_asset_all(token: str) -> float:
    req = urllib.request.Request(f"{PROD_API}/api/portfolio",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return float(json.load(res)["totals"]["total_asset_all"])


def write_log(status: str, value, note: str = "") -> None:
    os.makedirs(LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["日時", "判定", "評価額(現金込み)", "備考"])
        w.writerow([datetime.now().strftime("%Y/%m/%d %H:%M"), status,
                    "" if value is None else f"{value:.0f}", note])


def alert_desktop(message: str) -> None:
    desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "デスクトップ")
    if not os.path.isdir(desktop):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    path = os.path.join(desktop, f"FC_資産記録NG_{datetime.now():%Y%m%d}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"FORCE CAPITAL 日次資産記録 NG ({datetime.now():%Y/%m/%d %H:%M})\n\n")
        f.write(message + f"\n\nログ: {LOG_PATH}\n")


def main():
    dry_run = "--dry-run" in sys.argv
    today = datetime.now().strftime("%Y/%m/%d")
    try:
        total = fetch_total_asset_all(mint_token())

        # 書込側は data.py の env シーム経由(手動ボタンと同一経路)
        if not os.environ.get("GCP_CREDENTIALS_JSON") and os.path.exists(DEFAULT_CREDS):
            with open(DEFAULT_CREDS, encoding="utf-8") as f:
                os.environ["GCP_CREDENTIALS_JSON"] = f.read()
        os.environ.setdefault("FC_API_USER", "admin")
        os.environ.setdefault("FC_SHEET_ID", ADMIN_SHEET_ID)
        from data import load_history, save_history

        if today in set(load_history()["日付"].astype(str)):
            write_log("SKIP", total, "同日記録あり(手動または再実行)")
            print(f"→ スキップ: {today} は記録済み (評価額¥{total:,.0f})")
            return
        if dry_run:
            write_log("DRY", total, "dry-run(未書込)")
            print(f"[dry-run] 追記予定: {today}, ¥{total:,.0f}")
            return
        save_history(today, total)
        # save_history は例外を握りつぶすため、再読込で追記成立を確認する
        if today not in set(load_history()["日付"].astype(str)):
            raise RuntimeError("save_history 後の再読込で当日行が見つからない(書込失敗)")
        write_log("OK", total)
        print(f"✓ 記録: {today}, ¥{total:,.0f}")
    except Exception as e:
        write_log("NG", None, str(e))
        alert_desktop(f"エラー: {e}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
