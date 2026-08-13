"""ポートフォリオ・スナップショット構築

app.py の「データ取得」ブロック(load→ティッカー組立→市場データ→為替フォールバック→calc)と
同一の手順・同一の関数で計算する。UI通知(st.warning相当)は warnings リストとして返す。
並行運用中に app.py 側のパイプラインを変更した場合はここも追随すること(PHASE3_PLAN §5)。
"""
import json

import pandas as pd

from config import (
    FALLBACK_USDJPY,
    NISA_GROWTH_ANNUAL,
    NISA_GROWTH_LIFETIME,
    NISA_TOTAL_LIFETIME,
    NISA_TSUMITATE_ANNUAL,
    NISA_TSUMITATE_LIFETIME,
)
from data import (
    get_gas_last_updated,
    load_data,
    load_fund_prices,
    load_gas_prices,
    load_last_prices_full,
    load_prev_fund_prices,
    load_settings,
)
from market import get_cached_market_data, get_cached_ticker_info
from calc import (
    calculate_portfolio,
    get_future_simulation,
    get_portfolio_totals,
    simulate_withdrawal,
)

EMPTY_TOTALS = dict(
    total_asset=0, total_net_profit=0, total_gross_profit=0, total_dividend=0,
    total_dividend_after_tax=0, total_fx_gain=0, total_stock_gain=0,
    avg_dividend_yield=0.0, stock_count=0,
)


def _df_to_records(df: pd.DataFrame) -> list:
    """NaN→null・numpy型→Python型を保証してJSON安全なレコード列にする"""
    if df.empty:
        return []
    return json.loads(df.to_json(orient="records", force_ascii=False))


def future_simulation_yearly(initial: float, annual_rate: float, years: int, yearly_addition: float) -> list:
    """tab_simulation.py:30-32/67-71 と同一の年次グルーピング(各年の最終月・経過年数ラベル)"""
    sdl = get_future_simulation(initial, annual_rate, years, yearly_addition)
    sdl["年"] = sdl["日時"].dt.year
    yd = sdl.groupby("年").last().reset_index()
    by = yd["年"].iloc[0]
    yd["経過年数"] = yd["年"].apply(lambda y: f"{y - by}年目" if y > by else "現在")
    return _df_to_records(yd[["経過年数", "予測評価額(円)", "積立元本(円)", "運用益(円)"]])


def withdrawal_simulation(initial: float, annual_rate: float, mode: str,
                          annual_withdrawal: float, withdrawal_rate: float,
                          inflation_rate: float, max_years: int) -> list:
    sim = simulate_withdrawal(initial, annual_rate, mode,
                              annual_withdrawal=annual_withdrawal,
                              withdrawal_rate=withdrawal_rate,
                              inflation_rate=inflation_rate,
                              max_years=max_years)
    return _df_to_records(sim)


def build_snapshot() -> dict:
    df = load_data()
    fund_prices = load_fund_prices()
    gas_prices = load_gas_prices()
    gas_last_updated = get_gas_last_updated()
    prev_fund_prices = load_prev_fund_prices()
    warnings = []

    if df.empty:
        display_df = pd.DataFrame()
        totals = dict(EMPTY_TOTALS)
        jpy_usd_rate = FALLBACK_USDJPY
    else:
        tickers = ["JPY=X", "^N225", "^GSPC", "^VIX"]
        for _, row in df.iterrows():
            c, m = str(row["銘柄コード"]), row["市場"]
            if m == "日本株":
                tickers.append(f"{c}.T")
            elif m in ("米国株", "暗号資産"):
                tickers.append(c)
        unique_tickers = tuple(sorted(set(tickers)))
        closes_df = get_cached_market_data(unique_tickers, period="1y")
        info_dict = get_cached_ticker_info(unique_tickers)
        s = closes_df["JPY=X"].dropna() if "JPY=X" in closes_df.columns else pd.Series()
        # 2点未満はmarket.pyが前回値で最終行のみ補完した系列(=取得失敗)とみなす — app.pyと同一判定
        if len(s) >= 2:
            jpy_usd_rate = float(s.iloc[-1])
        else:
            _last_fx = load_last_prices_full().get("JPY=X")
            if _last_fx and _last_fx[0] > 0:
                jpy_usd_rate = float(_last_fx[0])
                _fx_ts = f"・{_last_fx[1]}時点" if _last_fx[1] else ""
                warnings.append(f"USD/JPYの最新レートを取得できませんでした。前回取得値（{_last_fx[0]:.2f}円{_fx_ts}）で表示しています。")
            else:
                jpy_usd_rate = FALLBACK_USDJPY
                warnings.append(f"USD/JPYの最新レートを取得できませんでした。概算値（{FALLBACK_USDJPY:.1f}円）で表示しています — USD建て資産の評価額・損益・為替損益は不正確な可能性があります。")
        display_df = calculate_portfolio(df, closes_df, info_dict, fund_prices, jpy_usd_rate, gas_prices, prev_fund_prices)
        totals = get_portfolio_totals(display_df)

    settings = load_settings()
    try:
        cash_jpy = float(settings.get("cash_balance_jpy", 0) or 0)
    except (TypeError, ValueError):
        cash_jpy = 0.0
    totals["cash_jpy"] = cash_jpy
    totals["total_asset_all"] = totals["total_asset"] + cash_jpy

    def _fnum(key, default):
        try:
            return float(settings.get(key, default) or default)
        except (TypeError, ValueError):
            return float(default)

    target_jpy_pct = _fnum("target_jpy_pct", 50)  # app.py:195-196と同一の既定値
    target_usd_pct = _fnum("target_usd_pct", 50)

    return {
        "rows": _df_to_records(display_df),
        "totals": totals,
        "jpy_usd_rate": float(jpy_usd_rate),
        "gas_last_updated": gas_last_updated,
        "warnings": warnings,
        "targets": {"jpy_pct": target_jpy_pct, "usd_pct": target_usd_pct},
        "nisa_limits": {
            "growth_annual": NISA_GROWTH_ANNUAL,
            "growth_lifetime": NISA_GROWTH_LIFETIME,
            "tsumitate_annual": NISA_TSUMITATE_ANNUAL,
            "tsumitate_lifetime": NISA_TSUMITATE_LIFETIME,
            "total_lifetime": NISA_TOTAL_LIFETIME,
        },
    }
