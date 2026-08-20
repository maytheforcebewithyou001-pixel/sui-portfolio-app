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
import marketstore
from market import get_benchmark_history, get_cached_market_data, get_cached_ticker_info
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


def _compute_state(force_refresh: bool = False) -> dict:
    """スナップショットの内部計算(DataFrameのまま返す)。build_snapshot と AI総評生成が共用

    市場データは marketstore のポリシー層経由(自動更新は1日2回・手動は30分間隔、
    それ以外は永続キャッシュ供給)。force_refresh=True は手動更新ボタン相当
    """
    df = load_data()
    fund_prices = load_fund_prices()
    gas_prices = load_gas_prices()
    gas_last_updated = get_gas_last_updated()
    prev_fund_prices = load_prev_fund_prices()
    warnings = []
    market_fetched_at = None

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
        closes_df, info_dict, market_fetched_at, notice = marketstore.get_market_bundle(
            unique_tickers, force=force_refresh)
        if notice:
            warnings.append(notice)
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
        "display_df": display_df,
        "totals": totals,
        "jpy_usd_rate": float(jpy_usd_rate),
        "gas_last_updated": gas_last_updated,
        "warnings": warnings,
        "targets": {"jpy_pct": target_jpy_pct, "usd_pct": target_usd_pct},
        "market_fetched_at": market_fetched_at.isoformat() if market_fetched_at else None,
    }


def build_snapshot(force_refresh: bool = False) -> dict:
    state = _compute_state(force_refresh)
    display_df = state["display_df"]
    totals = state["totals"]
    jpy_usd_rate = state["jpy_usd_rate"]
    gas_last_updated = state["gas_last_updated"]
    warnings = state["warnings"]
    target_jpy_pct = state["targets"]["jpy_pct"]
    target_usd_pct = state["targets"]["usd_pct"]

    return {
        "rows": _df_to_records(display_df),
        "totals": totals,
        "jpy_usd_rate": float(jpy_usd_rate),
        "gas_last_updated": gas_last_updated,
        "warnings": warnings,
        "market_fetched_at": state["market_fetched_at"],
        "targets": {"jpy_pct": target_jpy_pct, "usd_pct": target_usd_pct},
        "nisa_limits": {
            "growth_annual": NISA_GROWTH_ANNUAL,
            "growth_lifetime": NISA_GROWTH_LIFETIME,
            "tsumitate_annual": NISA_TSUMITATE_ANNUAL,
            "tsumitate_lifetime": NISA_TSUMITATE_LIFETIME,
            "total_lifetime": NISA_TOTAL_LIFETIME,
        },
    }


# ══════════════════════════════════════════
# 資産推移 + ベンチマーク比較 (tab_portfolio._render_history_chart と同一手順)
# ══════════════════════════════════════════
HISTORY_BENCHMARK_TICKERS = ("ACWI", "^GSPC")


def get_history_state() -> dict:
    """資産推移履歴・投資元本(概算)・円換算ベンチマーク系列を返す。

    元本は Streamlit 版と同じく生データの Σ(保有株数×取得単価)。米国株の取得単価は
    USD のまま合算されるため「概算」表記が前提(パリティ維持のため換算しない)。
    期間フィルタ・100指数化・α算出はフロント側で行う(Streamlit版と同一の数式)
    """
    hdf = load_history()
    rows = []
    if not hdf.empty:
        hdf = hdf.copy()
        hdf["総資産額(円)"] = pd.to_numeric(hdf["総資産額(円)"], errors="coerce")
        hdf = hdf.dropna(subset=["総資産額(円)"])
        hdf["日付_dt"] = pd.to_datetime(hdf["日付"], errors="coerce")
        hdf = hdf.dropna(subset=["日付_dt"]).sort_values("日付_dt")
        rows = [{"date": d.strftime("%Y-%m-%d"), "total": float(v)}
                for d, v in zip(hdf["日付_dt"], hdf["総資産額(円)"])]

    df = load_data()
    cost_total = float((df["保有株数"] * df["取得単価"]).sum()) if not df.empty else 0.0

    benchmarks = {}
    if len(rows) >= 2:
        bdf = get_benchmark_history(HISTORY_BENCHMARK_TICKERS + ("JPY=X",), "2y")
        if not bdf.empty and "JPY=X" in bdf.columns:
            bdf = bdf.copy()
            bdf.index = pd.to_datetime(bdf.index)
            for tk in HISTORY_BENCHMARK_TICKERS:
                if tk not in bdf.columns:
                    continue
                jpy = (bdf[tk] * bdf["JPY=X"]).dropna()
                if len(jpy) < 2:
                    continue
                benchmarks[tk] = [{"date": i.strftime("%Y-%m-%d"), "value": float(v)}
                                  for i, v in jpy.items()]
    return {"history": rows, "cost_total": cost_total, "benchmarks": benchmarks}


# ══════════════════════════════════════════
# AI総評 / ライフプラン (tab_ai.py の共有関数を再利用)
# ══════════════════════════════════════════
import json as _json  # noqa: E402
import os as _os  # noqa: E402
from datetime import datetime as _dt  # noqa: E402
from zoneinfo import ZoneInfo as _ZoneInfo  # noqa: E402

from calc import build_portfolio_summary_text  # noqa: E402
from data import (  # noqa: E402
    _current_user,
    load_ai_review,
    load_ai_review_history,
    load_history,
    load_lifeplan_history,
    save_ai_review,
    save_lifeplan,
    save_settings,
)
from tabs.tab_ai import (  # noqa: E402
    KURISU_USERS,
    _build_history_context,
    _call_claude,
    build_lifeplan_system_prompt,
    build_lifeplan_user_content,
    build_review_system_prompt,
    build_review_user_content,
)

_JST = _ZoneInfo("Asia/Tokyo")


class AIKeyMissing(Exception):
    pass


class AIGenerationError(Exception):
    pass


def _anthropic_api_key() -> str:
    key = _os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("anthropic_api_key", "")
        except Exception:
            key = ""
    if not key:
        raise AIKeyMissing("ANTHROPIC_API_KEY が未設定です(環境変数またはsecrets)")
    return key


def get_ai_review_state(include_summary: bool = True) -> dict:
    dt, text = load_ai_review()
    history = load_ai_review_history(10)
    summary_text = ""
    if include_summary:
        state = _compute_state()
        if not state["display_df"].empty:
            summary_text = build_portfolio_summary_text(
                state["display_df"], state["totals"], state["jpy_usd_rate"], history_df=load_history())
    return {
        "review_dt": dt,
        "review_text": text,
        "history": [{"dt": d, "text": t} for d, t in history],
        "policy_memo": load_settings().get("ai_policy_memo", ""),
        "summary_text": summary_text,
    }


def generate_ai_review() -> dict:
    """tab_ai._render_review の生成ブロックと同一手順(プロンプトは共有関数)"""
    api_key = _anthropic_api_key()
    state = _compute_state()
    if state["display_df"].empty or state["totals"]["total_asset"] <= 0:
        raise AIGenerationError("銘柄がないため総評を生成できません")
    ptxt = build_portfolio_summary_text(
        state["display_df"], state["totals"], state["jpy_usd_rate"], history_df=load_history())
    past_reviews = load_ai_review_history(10)
    history_context = _build_history_context(past_reviews)
    policy_memo = load_settings().get("ai_policy_memo", "").strip()
    system_prompt = build_review_system_prompt(
        policy_memo, bool(past_reviews), kurisu=_current_user() in KURISU_USERS)
    user_content = build_review_user_content(ptxt, policy_memo, history_context)
    ok, result, stop = _call_claude(api_key, system_prompt, user_content, max_tokens=4000)
    if not ok:
        raise AIGenerationError(result)
    ns = _dt.now(_JST).strftime("%Y/%m/%d %H:%M")
    save_ai_review(ns, result)
    return {"dt": ns, "text": result, "truncated": stop == "max_tokens"}


def save_policy_memo(memo: str) -> None:
    save_settings({"ai_policy_memo": memo.strip()})


def get_lifeplan_state() -> dict:
    history = load_lifeplan_history(10)
    return {"history": [{"dt": d, "inputs": ij, "text": t} for d, ij, t in history]}


# ══════════════════════════════════════════
# 世界指標 / 投資部門フロー / ランク
# ══════════════════════════════════════════
import jquants  # noqa: E402
from config import RANK_TIERS, WORLD_INDICES, get_rank  # noqa: E402
from tabs.tab_market import _INVESTOR_COLORS, _INVESTOR_LABELS, _flow_streak  # noqa: E402

PERIOD_MAP = {"1週間": "5d", "1ヶ月": "1mo", "3ヶ月": "3mo", "1年": "1y"}


def get_world_indices(period_label: str) -> dict:
    """tab_market.render の指標カード部と同一(最終値・前日比・スパークライン系列)"""
    sp = PERIOD_MAP.get(period_label, "1mo")
    closes = get_cached_market_data(tuple(sorted(WORLD_INDICES.values())), period=sp)
    out = []
    for name, tk in WORLD_INDICES.items():
        item = {"name": name, "ticker": tk, "status": "ok"}
        if tk not in closes.columns:
            item["status"] = "取得失敗"
        else:
            ser = closes[tk].dropna()
            if len(ser) < 2:
                item["status"] = "データ不足"
            else:
                last, prev = float(ser.iloc[-1]), float(ser.iloc[-2])
                item.update({
                    "last": last,
                    "diff": last - prev,
                    "pct": ((last / prev) - 1) * 100,
                    "series": [{"t": str(idx)[:10], "v": float(v)} for idx, v in ser.items()],
                })
        out.append(item)
    return {"period": period_label, "indices": out}


def get_investor_flow(weeks: int) -> dict:
    """tab_market._render_investor_flow と同一(要約・系列・直近4週・シグナル)"""
    df = jquants.get_investor_types(weeks=weeks)
    if df is None or df.empty:
        return {"available": False, "reason": "J-Quants 投資部門別売買データを取得できませんでした。プラン契約範囲を確認してください。"}
    cols = [c for c in _INVESTOR_LABELS if c in df.columns]
    if "EnDate" not in df.columns or not cols:
        return {"available": False, "reason": "投資部門データのカラム構造が想定と違う。スキップ。"}

    summary = []
    for col in ("FrgnBal", "IndBal"):
        if col in df.columns:
            stk = _flow_streak(df[col])
            if stk:
                summary.append({
                    "col": col, "label": _INVESTOR_LABELS[col], "sign": stk["sign"],
                    "weeks": stk["weeks"], "cum_oku": stk["cum"] / 1e8, "latest_oku": stk["latest"] / 1e8,
                })

    rows = []
    for _, r in df.iterrows():
        row = {"date": str(r["EnDate"])[:10]}
        for c in cols:
            v = r[c]
            row[c] = None if pd.isna(v) else float(v) / 1e8  # 億円
        rows.append(row)

    topix = jquants.get_topix_ohlc(period_days=weeks * 7 + 30)
    topix_rows = []
    if topix is not None and not topix.empty and "Close" in topix.columns:
        t0 = df["EnDate"].min() - pd.Timedelta(days=6)
        t1 = df["EnDate"].max()
        t = topix[(topix["Date"] >= t0) & (topix["Date"] <= t1)]
        topix_rows = [{"date": str(d)[:10], "close": float(c)} for d, c in zip(t["Date"], t["Close"])]

    signals = []
    if "FrgnBal" in df.columns:
        f = df["FrgnBal"].dropna()
        if len(f) >= 2:
            prev, curr = f.iloc[-2], f.iloc[-1]
            if prev < 0 and curr > 0:
                signals.append(f"🟢 海外投資家がネット買越転換 ({prev/1e8:+,.0f}億 → {curr/1e8:+,.0f}億) — 買い好機")
            elif prev > 0 and curr < 0:
                signals.append(f"🔴 海外投資家がネット売越転換 ({prev/1e8:+,.0f}億 → {curr/1e8:+,.0f}億) — 警戒")
    if "IndBal" in df.columns:
        ind = df["IndBal"].dropna()
        if len(ind) >= 8:
            mean_, std_ = ind.iloc[:-1].mean(), ind.iloc[:-1].std()
            latest = ind.iloc[-1]
            if std_ and std_ > 0:
                z = (latest - mean_) / std_
                if z > 1.5:
                    signals.append(f"⚠️ 個人ネット買越過熱 (Z={z:+.2f}) — 戻り売り圧力警戒")
                elif z < -1.5:
                    signals.append(f"⚠️ 個人ネット売越過熱 (Z={z:+.2f}) — 逆張り好機の可能性")

    return {
        "available": True, "weeks": weeks,
        "columns": [{"key": c, "label": _INVESTOR_LABELS[c], "color": _INVESTOR_COLORS.get(c, "#888")} for c in cols],
        "rows": rows, "topix": topix_rows, "summary": summary, "signals": signals,
    }


# ══════════════════════════════════════════
# アプリ設定 (Streamlit版サイドバー相当)
# ══════════════════════════════════════════
class SettingsError(Exception):
    pass


def get_app_settings() -> dict:
    s = load_settings()

    def _f(key, default):
        try:
            return float(s.get(key, default) or default)
        except (TypeError, ValueError):
            return float(default)

    return {
        "target_jpy_pct": _f("target_jpy_pct", 50),
        "target_usd_pct": _f("target_usd_pct", 50),
        "cash_balance_jpy": _f("cash_balance_jpy", 0),
    }


def save_app_settings(target_jpy_pct=None, target_usd_pct=None, cash_balance_jpy=None) -> dict:
    """サイドバーの保存ボタン相当。目標配分は合計100%でなければ保存しない(app.py:207 のdisabled条件と同一)"""
    updates = {}
    if target_jpy_pct is not None or target_usd_pct is not None:
        if target_jpy_pct is None or target_usd_pct is None:
            raise SettingsError("JPY目標とUSD目標は同時に指定してください")
        if not (0 <= target_jpy_pct <= 100) or not (0 <= target_usd_pct <= 100):
            raise SettingsError("目標配分は0〜100%で指定してください")
        if abs((target_jpy_pct + target_usd_pct) - 100) > 1e-9:
            raise SettingsError(f"合計を100%にしてね（現在 {target_jpy_pct + target_usd_pct:.1f}%）")
        updates["target_jpy_pct"] = target_jpy_pct
        updates["target_usd_pct"] = target_usd_pct
    if cash_balance_jpy is not None:
        if not (0 <= cash_balance_jpy <= 1e10):
            raise SettingsError("現金残高は0〜100億円で指定してください")
        updates["cash_balance_jpy"] = cash_balance_jpy
    if not updates:
        raise SettingsError("保存対象がありません")
    save_settings(updates)
    return get_app_settings()


# ══════════════════════════════════════════
# 銘柄詳細 (tab_portfolio._render_stock_detail と同一手順)
# ══════════════════════════════════════════
from calc import calc_risk_metrics  # noqa: E402
from market import get_stock_detail as _get_stock_detail  # noqa: E402
from tabs.tab_portfolio import build_fin_view  # noqa: E402


def _f_or_none(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def get_stock_detail_bundle(code: str, market_type: str, shares: float,
                            buy_price: float, buy_date: str) -> dict:
    """銘柄詳細タブのデータ一式。計算手順は tab_portfolio.py:202-451 と同一"""
    out = {"detail": None, "risk": None, "chart": None, "fin": None, "revisions": []}

    # ── 指標カード ──
    try:
        d = _get_stock_detail(code, market_type)
        out["detail"] = d or None
    except Exception:
        out["detail"] = None

    # ── リスク指標(日本株のみ、TOPIX対比) ──
    if market_type == "日本株":
        try:
            ticker_jp = f"{code}.T"
            risk_closes = get_cached_market_data(tuple(sorted([ticker_jp])), period="1y")
            topix_df = jquants.get_topix_ohlc(period_days=400)
            asset_series = risk_closes[ticker_jp].dropna() if ticker_jp in risk_closes.columns else pd.Series(dtype=float)
            topix_series = topix_df.set_index("Date")["Close"] if (topix_df is not None and not topix_df.empty and "Close" in topix_df.columns) else None
            rm = calc_risk_metrics(asset_series, topix_series)
            if any(v is not None for v in rm.values()):
                out["risk"] = {k: _f_or_none(v) for k, v in rm.items()}
        except Exception as e:
            logger_msg = f"リスク指標の計算でエラー: {e}"
            out["risk_error"] = logger_msg

    # ── 損益チャート(取得日〜現在) ──
    if market_type in ("日本株", "米国株"):
        ticker = f"{code}.T" if market_type == "日本株" else code
        chart_period = "1y"
        if buy_date:
            try:
                bd = pd.to_datetime(buy_date)
                days_held = (pd.Timestamp.now() - bd).days
                if days_held > 3650:
                    chart_period = "max"
                elif days_held > 1800:
                    chart_period = "10y"
                elif days_held > 730:
                    chart_period = "5y"
                elif days_held > 365:
                    chart_period = "2y"
            except Exception:
                pass
        try:
            chart_closes = get_cached_market_data(tuple(sorted([ticker, "JPY=X"])), period=chart_period)
            if ticker in chart_closes.columns:
                cs = chart_closes[ticker].dropna()
                if buy_date:
                    try:
                        cs = cs[cs.index >= pd.to_datetime(buy_date)]
                    except Exception:
                        pass
                if len(cs) >= 2:
                    cost_total = buy_price * shares
                    eval_series = cs * shares
                    if market_type == "米国株" and "JPY=X" in chart_closes.columns:
                        fx = chart_closes["JPY=X"].reindex(cs.index, method="ffill").fillna(FALLBACK_USDJPY)
                        eval_series = cs * shares * fx
                    latest_eval = float(eval_series.iloc[-1])
                    pnl_val = latest_eval - cost_total
                    pnl_pct = (pnl_val / cost_total * 100) if cost_total > 0 else 0
                    out["chart"] = {
                        "points": [{"t": str(idx)[:10], "v": round(float(v), 2)}
                                   for idx, v in eval_series.items() if pd.notna(v)],
                        "cost_total": round(cost_total, 2),
                        "pnl_val": round(pnl_val, 2),
                        "pnl_pct": round(pnl_pct, 2),
                    }
        except Exception:
            pass

    # ── 業績推移(日本株のみ、過去8期) + 業績修正検出 ──
    # 整形・修正検出は tabs.tab_portfolio.build_fin_view と共用(V2短縮カラム対応/
    # FY行限定の乖離判定を両系で単一実装に)
    if market_type == "日本株":
        try:
            fin_hist = jquants.get_fin_statements_history(code, limit=8)
            fin_rows, fin_metrics, rev_msgs = build_fin_view(fin_hist)
            if fin_rows:
                out["fin"] = {"rows": fin_rows, "metrics": fin_metrics}
            out["revisions"] = rev_msgs
        except Exception:
            pass

    return out


def get_rank_state() -> dict:
    totals = _compute_state()["totals"]
    ta = totals.get("total_asset_all", totals["total_asset"])
    rank = get_rank(ta)
    return {
        "total_asset": ta,
        "rank": None if rank is None else {"name": rank[0], "color": rank[1], "level": rank[2], "max_level": rank[3]},
        "tiers": [{"threshold": t, "name": n, "color": c} for t, n, c in RANK_TIERS],
    }


# ══════════════════════════════════════════
# 取引履歴 (tab_transaction.py の共有関数を再利用)
# ══════════════════════════════════════════
import io as _io  # noqa: E402

from config import BROKER_OPTIONS, TAX_OPTIONS  # noqa: E402
from data import load_transactions  # noqa: E402
from tabs.tab_transaction import (  # noqa: E402
    _parse_broker_csv,
    apply_csv_import,
    record_transaction,
)


class TxError(Exception):
    pass


def get_transactions_state() -> dict:
    tx_df = load_transactions()
    df = load_data()
    holdings = []
    for i, row in df.iterrows():
        holdings.append({
            "index": int(i),
            "code": str(row["銘柄コード"]),
            "name": str(row["銘柄名"]),
            "market": str(row.get("市場", "-")),
            "broker": str(row.get("口座", "")),
            "tax": str(row.get("口座区分", "")),
        })
    return {
        "transactions": _df_to_records(tx_df),
        "holdings": holdings,
        "broker_options": list(BROKER_OPTIONS),
        "tax_options": list(TAX_OPTIONS),
    }


def record_manual_transaction(index: int, code: str, tx_type: str, date_str: str,
                              qty: float, price: float, fee: float, broker: str, tax: str) -> float:
    df = load_data()
    if index not in df.index:
        raise TxError("指定行が見つかりません(保有データが変わった可能性)。再読込してください")
    if str(df.at[index, "銘柄コード"]) != code:
        raise TxError("銘柄コードが一致しません(保有データが変わった可能性)。再読込してください")
    return record_transaction(df, index, tx_type, date_str, qty, price, fee, broker, tax)


def parse_broker_csv_bytes(content: bytes):
    csv_df, broker, err = _parse_broker_csv(_io.BytesIO(content))
    if err:
        raise TxError(err)
    return csv_df, broker


def preview_broker_csv(content: bytes) -> dict:
    csv_df, broker = parse_broker_csv_bytes(content)
    cols = [c for c in ["約定日", "_name", "_code", "_取引種別", "_口座区分", "_qty", "_price"] if c in csv_df.columns]
    return {"broker": broker, "count": len(csv_df), "rows": _df_to_records(csv_df[cols])}


def execute_broker_csv(content: bytes, imp_mode: str) -> dict:
    csv_df, broker = parse_broker_csv_bytes(content)
    df = load_data()
    tx_count, upd_count, skip_count = apply_csv_import(csv_df, broker, imp_mode, df)
    return {"broker": broker, "tx_count": tx_count, "upd_count": upd_count, "skip_count": skip_count}


def generate_lifeplan(inputs: dict) -> dict:
    """tab_ai._render_lifeplan の生成ブロックと同一手順(inputsはクライアント整形済み表示文字列)"""
    api_key = _anthropic_api_key()
    system_prompt = build_lifeplan_system_prompt()
    user_content = build_lifeplan_user_content(inputs)
    ok, result, stop = _call_claude(api_key, system_prompt, user_content, max_tokens=8000)
    if not ok:
        raise AIGenerationError(result)
    ns = _dt.now(_JST).strftime("%Y/%m/%d %H:%M")
    save_lifeplan(ns, _json.dumps(inputs, ensure_ascii=False), result)
    return {"dt": ns, "text": result, "truncated": stop == "max_tokens"}


# ══════════════════════════════════════════
# ライフプランMC (lifeplan_montecarlo_20260717 のエンジンを共有)
# ══════════════════════════════════════════
import math as _math  # noqa: E402

from data import load_lifeplan_mc_history, save_lifeplan_mc  # noqa: E402
from lifeplan_montecarlo_20260717 import (  # noqa: E402
    historical_sequences as lifeplan_historical_sequences,
    simulate as lifeplan_simulate,
)

# simulate() 引数のパススルー許可リスト(track は常にTrue)。
# hist_returns/returns_seq の系列直接注入はAPIでは受けない(リプレイはPhase C)
_LP_FLOAT_KEYS = frozenset({
    "mu", "sigma", "save", "spend", "spend_after70", "pension_scale",
    "risk0", "cash0", "pension_self", "pension_spouse", "reemploy_income",
    "cash_real", "crash_year1", "tax_rate", "calm65_if_above", "ar1_rho", "mu_sd",
    "edu_inflow"})
_LP_INT_KEYS = frozenset({
    "retire_age", "spouse_from", "age_end", "reemploy_until", "pension_from",
    "block_len", "n_paths", "seed", "spend_change_age"})
_LP_TUPLE_KEYS = {"calm65": 2, "guardrail": 2, "ideco": 5, "bonus_risk": 3,
                  "disable_risk": 2, "death": 4, "crash_at": 2, "save_cut": 3}


def _lp_num(v, name):
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} は数値で指定")
    if not _math.isfinite(f):
        raise ValueError(f"{name} が有限の数値でない")
    return f


def _lp_coerce(params: dict) -> dict:
    """検証+型変換して simulate() に渡せる kw を返す。

    数値パリティの肝: 変換は型合わせのみで値の丸め・補正はしない。
    既定値の適用はエンジン側に任せる(キー未指定=simulate()の既定)。"""
    if not isinstance(params, dict):
        raise ValueError("params はオブジェクトで指定")
    allowed = (_LP_FLOAT_KEYS | _LP_INT_KEYS | set(_LP_TUPLE_KEYS)
               | {"edu_track", "deterministic", "ret_model", "edu_plan", "shocks"})
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(f"未対応パラメータ: {sorted(unknown)}")
    kw = {}
    for k, v in params.items():
        if v is None:
            continue
        if k in _LP_FLOAT_KEYS:
            kw[k] = _lp_num(v, k)
        elif k in _LP_INT_KEYS:
            kw[k] = int(_lp_num(v, k))
        elif k in _LP_TUPLE_KEYS:
            n = _LP_TUPLE_KEYS[k]
            if not isinstance(v, (list, tuple)) or len(v) != n:
                raise ValueError(f"{k} は要素{n}の配列で指定")
            kw[k] = tuple(_lp_num(x, k) for x in v)
        elif k == "shocks":
            if not isinstance(v, (list, tuple)) or len(v) > 200:
                raise ValueError("shocks は [[年齢, 万円], ...] 形式(200件まで)")
            rows = []
            for item in v:
                if not isinstance(item, (list, tuple)) or len(item) != 2:
                    raise ValueError("shocks の各要素は [年齢, 万円]")
                rows.append((int(_lp_num(item[0], "shocks.年齢")),
                             _lp_num(item[1], "shocks.金額")))
            kw[k] = tuple(rows)
        elif k == "edu_plan":
            if (not isinstance(v, dict) or set(v) != {"c1", "c2"}
                    or any(not isinstance(v[c], (list, tuple)) or len(v[c]) != 4
                           for c in ("c1", "c2"))):
                raise ValueError('edu_plan は {"c1": [中,高,大,下宿], "c2": [...]} で指定')
            kw[k] = {c: tuple(_lp_num(x, f"edu_plan.{c}") for x in v[c])
                     for c in ("c1", "c2")}
        elif k == "edu_track":
            if v not in ("private", "light"):
                raise ValueError('edu_track は "private" か "light"')
            kw[k] = v
        elif k == "ret_model":
            if v not in ("iid", "bootstrap"):
                raise ValueError('ret_model は "iid" か "bootstrap"')
            kw[k] = v
        elif k == "deterministic":
            kw[k] = bool(v)
    # 計算量ガード(Cloud Run 1リクエストの上限)
    if not (90 <= kw.get("age_end", 95) <= 110):
        raise ValueError("age_end は 90〜110")
    if not (1 <= kw.get("n_paths", 20_000) <= 20_000):
        raise ValueError("n_paths は 1〜20,000")
    if not (1 <= kw.get("block_len", 5) <= 20):
        raise ValueError("block_len は 1〜20")
    if not (0 <= kw.get("edu_inflow", 21.0) <= 100):
        raise ValueError("edu_inflow は 0〜100")
    if not (55 <= kw.get("spend_change_age", 70) <= 105):
        raise ValueError("spend_change_age は 55〜105")
    return kw


def run_lifeplan_mc(params: dict) -> dict:
    """POST /api/lifeplan/mc 本体。simulate(track=True) を実行して軌跡込みで返す"""
    kw = _lp_coerce(params)
    r = lifeplan_simulate(track=True, **kw)
    t = r.pop("trajectory")
    r["trajectory"] = {
        "ages": [int(a) for a in t["ages"]],
        **{p: [float(x) for x in t[p]] for p in ("p5", "p25", "p50", "p75", "p95")},
        "depletion": [float(x) for x in t["depletion"]],
    }
    # seq_score は序盤逆風の試行が無いと NaN → JSONにできないので null に落とす
    if not _math.isfinite(r.get("seq_score", 0.0) or 0.0):
        r["seq_score"] = None
    return r


# 開始年総当たりリプレイでは無効な設定(注入系列が全年のリターンを決めるため)。
# エンジン側は指定するとValueErrorを投げる仕様なので、ここで落として dropped で通知する
_LP_REPLAY_EXCLUDE = frozenset({
    "ret_model", "block_len", "ar1_rho", "crash_year1", "crash_at", "save_cut",
    "mu_sd", "calm65", "calm65_if_above", "deterministic", "seed", "n_paths"})


def run_lifeplan_replay(params: dict) -> dict:
    """POST /api/lifeplan/replay 本体。実史の全開始年リプレイ(決定論・乱数ゼロ)"""
    kw = _lp_coerce(params)
    dropped = sorted(k for k in kw if k in _LP_REPLAY_EXCLUDE)
    for k in dropped:
        kw.pop(k)
    mu = kw.pop("mu", 0.04)
    sigma = kw.pop("sigma", 0.18)
    hs = lifeplan_historical_sequences(mu=mu, sigma=sigma, **kw)
    return {
        "success_rate": hs["success_rate"], "n_starts": hs["n_starts"],
        "n_ok": hs["n_ok"], "dropped": dropped,
        "results": [{"start": x["start"], "ok": bool(x["ok"]),
                     "fail_age": x["fail_age"], "terminal": float(x["terminal"]),
                     "wrapped": bool(x["wrapped"])} for x in hs["results"]],
    }


def solve_lifeplan_target(params: dict, target: float, lever: str) -> dict:
    """POST /api/lifeplan/solve 本体。目標スコアに必要な貯蓄増/支出減を二分探索する。

    lever="save": 年間貯蓄を現在値→400万の範囲で増やす(スコアは単調増加)
    lever="spend": 老後生活費を現在値→240万の範囲で絞る(減らすほど単調増加)
    """
    if not (50.0 <= float(target) <= 99.9):
        raise ValueError("target は 50〜99.9")
    if lever not in ("save", "spend"):
        raise ValueError('lever は "save" か "spend"')
    kw = _lp_coerce(params)
    kw.pop("deterministic", None)   # 決定論では確率目標の探索は無意味

    def score_at(x):
        return lifeplan_simulate(**{**kw, lever: float(x)})["score"]

    cur = kw.get(lever, 200.0 if lever == "save" else 360.0)  # 未指定=エンジン既定
    limit = 400.0 if lever == "save" else 240.0
    s_cur = score_at(cur)
    if s_cur >= target:
        return {"achievable": True, "already": True, "current_value": cur,
                "needed_value": cur, "score": s_cur}
    s_lim = score_at(limit)
    if s_lim < target:
        return {"achievable": False, "already": False, "current_value": cur,
                "limit_value": limit, "score": s_lim}
    lo, hi = (cur, limit) if lever == "save" else (limit, cur)
    # save: 上げるほど改善 / spend: 下げるほど改善 — 二分探索14回で±0.01万まで収束
    for _ in range(14):
        mid = (lo + hi) / 2
        if score_at(mid) >= target:
            if lever == "save":
                hi = mid
            else:
                lo = mid
        else:
            if lever == "save":
                lo = mid
            else:
                hi = mid
    needed = hi if lever == "save" else lo
    return {"achievable": True, "already": False, "current_value": cur,
            "needed_value": round(needed, 1), "score": score_at(needed)}


def get_lifeplan_mc_history() -> dict:
    """GET /api/lifeplan/mc/history 本体。新しい順で返す"""
    out = []
    for dt_s, memo, score, mj, pj in load_lifeplan_mc_history(50):
        try:
            metrics = _json.loads(mj)
        except (ValueError, TypeError):
            metrics = {}
        try:
            saved_params = _json.loads(pj)
        except (ValueError, TypeError):
            saved_params = {}
        try:
            sc = float(score)
        except (ValueError, TypeError):
            sc = None
        out.append({"dt": dt_s, "memo": memo, "score": sc,
                    "metrics": metrics, "params": saved_params})
    return {"history": out[::-1]}


def save_lifeplan_mc_run(memo: str, params: dict, metrics: dict) -> dict:
    """POST /api/lifeplan/mc/history 本体。パラメータ再検証の上でシートへ追記"""
    kw = _lp_coerce(params)   # 保存前に再検証(不正パラメータの永続化を防ぐ)
    if not isinstance(metrics, dict) or "score" not in metrics:
        raise ValueError("metrics に score が必要")
    keep = {k: metrics.get(k) for k in
            ("score", "fail_age_med", "terminal_p50", "terminal_p5",
             "cash_hit", "seq_score") if metrics.get(k) is not None}
    ns = _dt.now(_JST).strftime("%Y/%m/%d %H:%M")
    save_lifeplan_mc(ns, (memo or "").strip()[:100],
                     round(float(metrics["score"]), 3),
                     _json.dumps(keep, ensure_ascii=False),
                     _json.dumps(params, ensure_ascii=False))
    return {"dt": ns}
