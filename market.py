"""
市場データ取得
  日本株: J-Quants V2（メイン）→ yfinance（フォールバック）→ GAS → 手動
  米国株: yfinance
  為替・指数: yfinance
"""
import streamlit as st
import pandas as pd
import yfinance as yf
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import logger, SECTOR_MAP
from data import save_last_prices, load_last_prices
import jquants


def _yf_close_df(tickers, period):
    """yfinanceから終値(Close)のDataFrameを取得。失敗・空なら空DFを返す。"""
    try:
        data = yf.download(tickers, period=period, progress=False, threads=True)
        if data.empty:
            return pd.DataFrame()
        if isinstance(data.columns, pd.MultiIndex):
            out = data["Close"]
        else:
            out = data[["Close"]]
            out.columns = [tickers[0]]
        return out
    except Exception as e:
        logger.warning("yfinance取得失敗 (%s): %s", tickers, e)
        return pd.DataFrame()


# ══════════════════════════════════════════
# 株価データ（日足終値）
# ══════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def get_cached_market_data(tickers_tuple, period="1y"):
    """米国株・為替・指数をyfinanceから取得。日本株はJ-Quantsで別途取得。"""
    tickers = list(tickers_tuple)
    if not tickers: return pd.DataFrame()

    # 日本株(.T)とそれ以外を分離
    jp_tickers = [t for t in tickers if t.endswith(".T")]
    other_tickers = [t for t in tickers if not t.endswith(".T")]

    closes = pd.DataFrame()

    # ── 米国株・為替・指数 → yfinance ──
    if other_tickers:
        df_other = _yf_close_df(other_tickers, period)
        if not df_other.empty:
            closes = df_other.ffill().bfill()

    # ── 日本株 → J-Quants優先 ──
    if jp_tickers and jquants.is_available():
        codes = [t.replace(".T", "") for t in jp_tickers]
        # periodをJ-Quantsの日数に変換（終値＋前日比に必要な最小限）
        period_days = {"5d": 10, "1mo": 40, "3mo": 100, "1y": 370}
        jq_days = period_days.get(period, 370)
        jq_quotes = jquants.get_daily_quotes(codes, days=jq_days)
        for code, entries in jq_quotes.items():
            ticker = f"{code}.T"
            if entries:
                df_jq = pd.DataFrame(entries)
                df_jq["Date"] = pd.to_datetime(df_jq["Date"])
                df_jq = df_jq.set_index("Date").sort_index()
                if closes.empty:
                    closes = pd.DataFrame(index=df_jq.index)
                closes[ticker] = df_jq["Close"]

    # J-Quantsで取れなかった日本株 → yfinanceフォールバック
    missing_jp = [t for t in jp_tickers if t not in closes.columns]
    if missing_jp:
        fb = _yf_close_df(missing_jp, period)
        for col in fb.columns:
            closes[col] = fb[col]

    if not closes.empty:
        closes = closes.ffill().bfill()
        # 最終価格をSheetsに保存（障害時フォールバック用）
        try:
            last_prices = {}
            for col in closes.columns:
                s = closes[col].dropna()
                if not s.empty:
                    last_prices[col] = float(s.iloc[-1])
            if last_prices:
                save_last_prices(last_prices)
        except Exception as e:
            logger.debug("最終価格保存スキップ: %s", e)
        return closes

    # 全部ダメ → Sheetsフォールバック
    fallback = load_last_prices()
    if fallback:
        fb_data = {t: [fallback.get(t, 0.0)] for t in tickers if t in fallback}
        if fb_data:
            fb_df = pd.DataFrame(fb_data, index=[pd.Timestamp.now()])
            st.warning("⚠ 株価を取得できませんでした。前回取得した価格を表示しています。")
            return fb_df
    return pd.DataFrame()


# ══════════════════════════════════════════
# 銘柄情報（セクター・配当）
# ══════════════════════════════════════════
def _fetch_single_info(t):
    """yfinanceで1銘柄の情報を取得（米国株用）"""
    if t == "JPY=X": return t, None
    try:
        info = yf.Ticker(t).info
        div_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0
        div_yield = float(info.get("trailingAnnualDividendYield") or info.get("dividendYield") or 0.0)
        # yfinanceはdividendYieldをパーセント形式(例:3.5)で返すことがある → 小数に正規化
        if div_yield > 1: div_yield = div_yield / 100.0
        # それでも>20%なら誤データとみなし無視
        if div_yield > 0.2: div_yield = 0.0
        sec = info.get("sector") or "ETF/その他"
        return t, {"sector": SECTOR_MAP.get(sec, sec), "div_rate": float(div_rate),
                    "div_yield": float(div_yield), "ex_div_date": info.get("exDividendDate"),
                    "name": info.get("shortName", "")}
    except Exception as e:
        logger.warning("銘柄情報取得失敗 %s: %s", t, e)
        return t, {"sector": "不明", "div_rate": 0.0, "div_yield": 0.0, "ex_div_date": None, "name": ""}


@st.cache_data(ttl=86400, show_spinner=False)
def get_cached_ticker_info(tickers_tuple):
    """全銘柄の情報を取得。日本株はJ-Quants、米国株はyfinance。"""
    tickers = list(tickers_tuple)
    info_dict = {}

    # 日本株 → J-Quantsで銘柄情報取得
    jp_tickers = [t for t in tickers if t.endswith(".T")]
    us_tickers = [t for t in tickers if not t.endswith(".T") and t != "JPY=X"]

    if jp_tickers and jquants.is_available():
        codes = [t.replace(".T", "") for t in jp_tickers]
        jq_info = jquants.get_listed_info()  # 全銘柄一括取得（キャッシュされる）
        for t in jp_tickers:
            code = t.replace(".T", "")
            if code in jq_info:
                ji = jq_info[code]
                sector = ji.get("sector33", "") or ji.get("sector17", "") or "不明"
                info_dict[t] = {
                    "sector": sector,
                    "div_rate": 0.0,  # J-Quantsの銘柄情報には配当率なし、財務で別途取得
                    "div_yield": 0.0,
                    "ex_div_date": None,
                    "name": ji.get("name", ""),
                }

    # J-Quantsで取れなかった日本株 → yfinanceフォールバック
    missing_jp = [t for t in jp_tickers if t not in info_dict]

    # 米国株 + フォールバック日本株 → yfinance並列
    yf_targets = us_tickers + missing_jp
    if yf_targets:
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = {executor.submit(_fetch_single_info, t): t for t in yf_targets}
            for future in as_completed(futures):
                t, result = future.result()
                if result is not None:
                    info_dict[t] = result

    return info_dict


@st.cache_data(ttl=3600, show_spinner=False)
def get_stock_detail(code, market_type):
    """銘柄の詳細指標を取得。前日終値,配当利回り,1株配当,PER,PBR,EPS,BPS,ROEを返す。"""
    if not code or market_type not in ("日本株", "米国株"):
        return {}
    t = f"{code}.T" if market_type == "日本株" else code
    try:
        info = yf.Ticker(t).info
        if not info or info.get("quoteType") is None:
            return {}
        bps = info.get("bookValue")
        eps = info.get("trailingEps")
        roe_raw = info.get("returnOnEquity")
        dy = info.get("dividendYield") or 0
        if 0 < dy < 0.2:
            dy = dy * 100
        def _ts(val):
            if not val: return None
            try: return datetime.fromtimestamp(val, tz=timezone.utc).strftime("%Y/%m/%d")
            except Exception: return None
        return {
            "前日終値": info.get("previousClose") or info.get("regularMarketPreviousClose"),
            "配当利回り(%)": round(dy, 2),
            "1株配当": info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0,
            "PER": info.get("trailingPE"),
            "PBR": info.get("priceToBook"),
            "EPS": eps,
            "BPS": bps,
            "ROE(%)": round(roe_raw * 100, 2) if roe_raw is not None else None,
            "直近四半期末": _ts(info.get("mostRecentQuarter")),
            "次回決算発表": _ts(info.get("earningsTimestamp")),
            "通貨": "USD" if market_type == "米国株" else "JPY",
        }
    except Exception as e:
        logger.warning("銘柄詳細取得失敗 %s: %s", t, e)
        return {}


@st.cache_data(ttl=3600, show_spinner=False)
def get_ticker_name(code, market_type):
    if not code: return ""
    if market_type in ["投資信託", "その他資産", "債券/国債", "コモディティ"]: return "手動入力"

    # 日本株 → J-Quants優先
    if market_type == "日本株" and jquants.is_available():
        jq_info = jquants.get_listed_info(code)
        c = str(code).replace(".T", "").strip()
        if c in jq_info:
            return jq_info[c].get("name", "") or "名称不明"

    # フォールバック → yfinance
    try:
        t = f"{code}.T" if market_type == "日本株" else code
        info = yf.Ticker(t).info
        return info.get("longName", info.get("shortName", "名称不明"))
    except Exception as e:
        logger.warning("銘柄名取得失敗 %s: %s", code, e)
        return "取得失敗"
