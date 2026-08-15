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
# AI総評 / ライフプラン (tab_ai.py の共有関数を再利用)
# ══════════════════════════════════════════
import json as _json  # noqa: E402
import os as _os  # noqa: E402
from datetime import datetime as _dt  # noqa: E402
from zoneinfo import ZoneInfo as _ZoneInfo  # noqa: E402

from calc import build_portfolio_summary_text  # noqa: E402
from data import (  # noqa: E402
    load_ai_review,
    load_ai_review_history,
    load_history,
    load_lifeplan_history,
    save_ai_review,
    save_lifeplan,
    save_settings,
)
from tabs.tab_ai import (  # noqa: E402
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
    system_prompt = build_review_system_prompt(policy_memo, bool(past_reviews))
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
        return {"available": False, "reason": "J-Quants 投資部門別売買データが取得できなかったわ。プラン契約範囲を確認して。"}
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
