"""フロント検証用のスタブAPI(外部通信ゼロ・このマシン専用)

run_api_local.py と違い Google Sheets / yfinance / J-Quants に一切触れない。
api.main の本物のルーティング・検証・エラー変換はそのまま使い、データ層だけを
インメモリの架空ポートフォリオに差し替える。UI の見た目・操作フローの確認用。

認証はローカル限定のテスト資格情報(admin / testpass)。トークン鍵は起動毎に使い捨て。

使い方(リポジトリ直下で): python scripts/run_api_stub.py
  → http://127.0.0.1:8000 (web/ 側は NEXT_PUBLIC_API_BASE 既定の localhost:8000 で接続)
"""
import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("FC_API_USER", "admin")
os.environ.setdefault("FC_TOKEN_SECRET", secrets.token_hex(32))
os.environ.setdefault("FC_AUTH_USERNAME", "admin")
# bcrypt("testpass", rounds=4) — ローカルE2E専用(run_api_local.py と同一)
os.environ.setdefault("FC_AUTH_PASSWORD_HASH", "$2b$04$pgSg0FlKnBZZ1h4ShpkGKev0HK8MhwROekBXm06U6feDTVsd28GOS")

import pandas as pd  # noqa: E402

import api.main as m  # noqa: E402
import api.service as svc  # noqa: E402
from config import EXPECTED_COLS  # noqa: E402

JST = timezone(timedelta(hours=9))

# ── 架空の保有シート(EXPECTED_COLS 準拠) ──
_ROWS = [
    ["7203", "トヨタ自動車", "日本株", "JPY", 100, 2500, "SBI証券", "特定口座", 0, "3,9", 90, 0, 0, "2024/05/10", ""],
    ["8593", "三菱HCキャピタル", "日本株", "JPY", 1800, 1000, "SBI証券", "特定口座", 0, "3,9", 40, 0, 0, "2023/01/20", ""],
    ["9887", "松屋フーズHLDGS", "日本株", "JPY", 100, 4200, "楽天証券", "NISA(成長投資枠)", 0, "3", 24, 0, 0, "", ""],
    ["VT", "バンガード・トータル・ワールド・ストックETF", "米国株", "USD", 120, 95.5, "SBI証券", "NISA(成長投資枠)", 0, "3,6,9,12", 2.2, 148.2, 0, "2024/01/15", ""],
    ["WDIV", "ST SPDR S&P 全世界配当株式 ETF", "米国株", "USD", 80, 60.0, "SBI証券", "特定口座", 0, "3,6,9,12", 3.5, 140.0, 0, "", ""],
    ["オルカン", "eMAXIS Slim 全世界株式(オール・カントリー)", "投資信託", "USD", 3200000, 21000, "SBI証券", "NISA(積立投資枠)", 0, "", 0, 0, 0, "", ""],
]
_state = {"df": pd.DataFrame(_ROWS, columns=EXPECTED_COLS)}
for _c in ("保有株数", "取得単価", "手動配当利回り(%)", "年間配当金(円/株)", "取得時為替", "手動現在値"):
    _state["df"][_c] = pd.to_numeric(_state["df"][_c], errors="coerce").fillna(0.0)


def _load_data():
    return _state["df"].copy()


def _save_data(df):
    _state["df"] = df.copy()
    print(f"[stub] save_data: {len(df)}行")


svc.load_data = _load_data
svc.save_data = _save_data
svc._clear_sheet_cache = lambda: None
svc.get_ticker_name = lambda code, market: {"7203": "トヨタ自動車", "6758": "ソニーグループ", "VT": "Vanguard Total World Stock ETF"}.get(code, "取得失敗")

# ── 架空スナップショット(/api/portfolio)。前日比を散らしてヒートマップの色を出す ──
_FX = 150.0
_PRICES = {"7203": (2850.0, +0.50), "8593": (1023.0, -0.31), "9887": (4390.0, +0.39),
           "VT": (128.4, +1.03), "WDIV": (66.1, +0.55), "オルカン": (27950.0, +0.80)}


def _snapshot(force_refresh=False):
    rows = []
    for _, r in _state["df"].iterrows():
        code = str(r["銘柄コード"])
        px, chg = _PRICES.get(code, (float(r["取得単価"]) * 1.1, 0.0))
        shares = float(r["保有株数"])
        buy = float(r["取得単価"])
        if r["市場"] == "投資信託":
            value, cost = shares / 10000 * px, shares / 10000 * buy
        elif r["通貨"] == "USD":
            value, cost = shares * px * _FX, shares * buy * _FX
        else:
            value, cost = shares * px, shares * buy
        div = shares * float(r["年間配当金(円/株)"]) * (_FX if r["通貨"] == "USD" else 1)
        rows.append({
            "銘柄コード": code, "銘柄名": r["銘柄名"], "市場": r["市場"], "通貨": r["通貨"],
            "口座": r["口座"], "口座区分": r["口座区分"], "保有株数": shares, "取得単価": buy,
            "現在値(円)": px * (_FX if r["通貨"] == "USD" and r["市場"] != "投資信託" else 1),
            "前日比": chg, "評価額(円)": value, "含み損益(円)": value - cost,
            "税引後損益(円)": (value - cost) * (1.0 if "NISA" in r["口座区分"] else 0.79685),
            "予想配当(円)": div, "税引後配当(円)": div * (1.0 if "NISA" in r["口座区分"] else 0.79685),
            "実質利回り(%)": round(div / value * 100, 2) if value else 0,
            "セクター": {"日本株": "資本財", "米国株": "ETF/その他"}.get(r["市場"], "投資信託"),
            "取得日": r["取得日"], "配当月": r["配当月"], "最新更新日": datetime.now(JST).strftime("%Y/%m/%d %H:%M"),
        })
    total = sum(x["評価額(円)"] for x in rows)
    gross = sum(x["含み損益(円)"] for x in rows)
    div_after = sum(x["税引後配当(円)"] for x in rows)
    return {
        "rows": rows,
        "totals": {
            "total_asset": total, "total_net_profit": gross * 0.8, "total_gross_profit": gross,
            "total_dividend": sum(x["予想配当(円)"] for x in rows), "total_dividend_after_tax": div_after,
            "total_fx_gain": 12345.0, "total_stock_gain": 67890.0,
            "avg_dividend_yield": round(div_after / total * 100, 2) if total else 0,
            "stock_count": len(rows), "cash_jpy": 3_000_000.0, "total_asset_all": total + 3_000_000.0,
        },
        "jpy_usd_rate": _FX, "gas_last_updated": None, "warnings": [],
        "market_fetched_at": datetime.now(JST).isoformat(),
        "targets": {"jpy_pct": 30.0, "usd_pct": 70.0},
        "nisa_limits": {"growth_annual": 2_400_000, "growth_lifetime": 12_000_000,
                        "tsumitate_annual": 1_200_000, "tsumitate_lifetime": 6_000_000,
                        "total_lifetime": 18_000_000},
    }


m.build_snapshot = _snapshot

import uvicorn  # noqa: E402

print("[stub] FORCE CAPITAL stub API (no external I/O) on http://127.0.0.1:8000  login: admin / testpass")
uvicorn.run(m.app, host="127.0.0.1", port=8000, log_level="warning")
