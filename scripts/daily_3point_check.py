"""日次3点チェック + 配当・決算アラート

ローカル計算(このリポジトリのAPIパイプライン)と Cloud Run 本番 /api/portfolio の
3点(評価額(現金込み)/損益(税引後)/年間配当(税引後))を突合し、乖離を検知する。
あわせて旧Streamlit版ヘッダーにあった減配検知・決算カレンダーのアラートを実行する
(2026-08-30 Streamlit退役に伴う移植)。

- 認証: パスワードを保存しない。Secret Manager から fc-token-secret を gcloud で
  実行時取得し、api.auth.issue_token で自前署名したトークンを使う
- 判定: 相対誤差 0.1% 以内で合格(市場データ取得タイミング差の吸収)。朝の閉場中
  実行を前提とする(タスクスケジューラ 07:10 JST)
- 出力: %LOCALAPPDATA%\\fc_checks\\daily_3point_log.csv に追記。
  NG時はデスクトップに FC_日次チェックNG_<日付>.txt を生成して目視導線を作る

使い方(リポジトリ直下・引数なし): python scripts/daily_3point_check.py
外部通信あり(Google Sheets / yfinance / Secret Manager / Cloud Run)。
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
LOG_PATH = os.path.join(LOG_DIR, "daily_3point_log.csv")
# 3点の定義(2026-08-14 E2Eの「3点一致」と同一)。許容誤差は点別:
# 配当は yfinance div_rate の取得成否がリクエスト毎に揺れる既知の性質があり
# (2026-08-16実測で同時刻4.07%乖離)、揺らぎ幅を超える構造破壊のみ検知する
POINTS = [
    ("評価額(現金込み)", lambda t: t["total_asset_all"], 0.001),
    ("損益(税引後)", lambda t: t["total_net_profit"], 0.001),
    ("年間配当(税引後)", lambda t: t["total_dividend_after_tax"], 0.05),
]


def mint_token() -> str:
    # text=False: シークレットは登録時の末尾改行ごと鍵として使われている(2026-08-16実測、
    # strip()すると署名不一致で401)。取得バイト列を無加工で渡すこと
    gcloud = r"C:\Users\mayth\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
    if not os.path.exists(gcloud):
        gcloud = "gcloud"  # タスクスケジューラ以外の環境向けフォールバック
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


def fetch_prod(token: str) -> dict:
    req = urllib.request.Request(f"{PROD_API}/api/portfolio",
                                 headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=120) as res:
        return json.load(res)


def compute_local() -> dict:
    if not os.environ.get("GCP_CREDENTIALS_JSON") and os.path.exists(DEFAULT_CREDS):
        with open(DEFAULT_CREDS, encoding="utf-8") as f:
            os.environ["GCP_CREDENTIALS_JSON"] = f.read()
    os.environ.setdefault("FC_API_USER", "admin")
    os.environ.setdefault("FC_SHEET_ID", ADMIN_SHEET_ID)
    from api.service import build_snapshot
    return build_snapshot()


def _desktop_dir() -> str:
    desktop = os.path.join(os.path.expanduser("~"), "OneDrive", "デスクトップ")
    if not os.path.isdir(desktop):
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    return desktop


def check_alerts(local_snapshot: dict) -> list:
    """減配検知 + 決算カレンダー(旧app.pyヘッダーアラートの移植)。

    - 減配の疑いは常にアラート(※分割の可能性があるためIR確認前提)
    - 決算予定はFCアラート規約(前日比±3%以上 AND 1週間以内決算のAND条件)を満たす
      ものだけアラート化し、それ以外は情報として印字のみ
    戻り値: アラート文字列のリスト(空なら異常なし)
    """
    jp = {}
    for r in local_snapshot.get("rows", []):
        if str(r.get("市場", "")).strip() != "日本株":
            continue
        c = str(r.get("銘柄コード", "")).replace(".T", "").strip()
        if len(c) >= 3 and c.isdigit():
            jp[c] = {"name": str(r.get("銘柄名", "")), "dod": r.get("前日比")}
    if not jp:
        return []

    import jquants
    alerts = []
    try:
        cuts = jquants.scan_dividend_cuts(tuple(sorted(jp)))
    except Exception as e:
        print(f"[WARN] 減配スキャン失敗: {e}")
        cuts = []
    for cut in cuts:
        nm = jp.get(cut["code"], {}).get("name") or cut["code"]
        alerts.append(
            f"減配の疑い(要確認): {nm}({cut['code']}) 予想年配当 {cut['current']:.1f}円 ＜ "
            f"前期実績 {cut['prior']:.1f}円 ({cut['pct']:+.1f}%) ※株式分割の可能性あり。IR・適時開示で確認")

    try:
        upcoming = jquants.get_upcoming_earnings(tuple(sorted(jp)), days_ahead=7)
    except Exception as e:
        print(f"[WARN] 決算カレンダー取得失敗: {e}")
        upcoming = []
    for e in upcoming:
        info = jp.get(e["code"], {})
        label = "本日決算" if e["days_until"] == 0 else f"あと{e['days_until']}日"
        line = f"決算予定: {info.get('name') or e['code']}({e['code']}) {e['date']:%m/%d} — {label}"
        dod = info.get("dod")
        try:
            dod_f = float(dod) if dod is not None else None
        except (TypeError, ValueError):
            dod_f = None
        if dod_f is not None and abs(dod_f) >= 3.0:
            alerts.append(f"{line} / 前日比 {dod_f:+.2f}% (±3%閾値超)")
        else:
            print(f"[INFO] {line}" + (f" / 前日比 {dod_f:+.2f}%" if dod_f is not None else ""))
    return alerts


def git_rev() -> str:
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        b = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True,
                           cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        return f"{b.stdout.strip()}@{r.stdout.strip()}"
    except Exception:
        return "unknown"


def main():
    now = datetime.now().strftime("%Y/%m/%d %H:%M")
    token = mint_token()
    prod = fetch_prod(token)["totals"]
    local_snapshot = compute_local()
    local = local_snapshot["totals"]

    results, ok_all = [], True
    for name, getter, tol in POINTS:
        pv, lv = float(getter(prod)), float(getter(local))
        base = max(abs(pv), abs(lv), 1.0)
        rel = abs(pv - lv) / base
        ok = rel <= tol
        ok_all &= ok
        results.append((name, pv, lv, rel, ok))
        mark = "OK" if ok else "NG"
        print(f"[{mark}] {name}: 本番¥{pv:,.0f} / ローカル¥{lv:,.0f} (乖離{rel * 100:.4f}% / 許容{tol * 100:.1f}%)")

    os.makedirs(LOG_DIR, exist_ok=True)
    new_file = not os.path.exists(LOG_PATH)
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["日時", "判定", "リビジョン"] +
                       [f"{n}({s})" for n, _, _ in POINTS for s in ("本番", "ローカル")])
        row = [now, "OK" if ok_all else "NG", git_rev()]
        for _, pv, lv, _, _ in results:
            row += [f"{pv:.0f}", f"{lv:.0f}"]
        w.writerow(row)

    # ── 減配・決算アラート(3点チェックの成否と独立。失敗しても突合結果は壊さない) ──
    try:
        alerts = check_alerts(local_snapshot)
    except Exception as e:
        print(f"[WARN] アラートチェック失敗: {e}")
        alerts = []
    for a in alerts:
        print(f"⚠ {a}")
    if alerts:
        alert_path = os.path.join(_desktop_dir(), f"FC_配当決算アラート_{datetime.now():%Y%m%d}.txt")
        with open(alert_path, "w", encoding="utf-8") as f:
            f.write(f"FORCE CAPITAL 配当・決算アラート ({now})\n\n")
            for a in alerts:
                f.write(f"- {a}\n")
        print(f"⚠ アラートファイル生成: {alert_path}")

    if not ok_all:
        alert = os.path.join(_desktop_dir(), f"FC_日次チェックNG_{datetime.now():%Y%m%d}.txt")
        with open(alert, "w", encoding="utf-8") as f:
            f.write(f"FORCE CAPITAL 日次3点チェック NG ({now})\n\n")
            for name, pv, lv, rel, ok in results:
                f.write(f"{'OK' if ok else 'NG'} {name}: 本番¥{pv:,.0f} / ローカル¥{lv:,.0f} (乖離{rel * 100:.4f}%)\n")
            f.write(f"\nログ: {LOG_PATH}\n")
        print(f"⚠ NG — アラートファイル生成: {alert}")
        raise SystemExit(1)
    print(f"✓ 3点一致 (ログ: {LOG_PATH})")


if __name__ == "__main__":
    main()
