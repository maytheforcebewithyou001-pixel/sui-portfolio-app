"""
市場データ取得
  日本株: J-Quants V2（メイン）→ yfinance（フォールバック）→ GAS → 手動
  米国株: yfinance
  為替・指数: yfinance
"""
import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import logger, SECTOR_MAP
from data import save_last_prices, load_last_prices
import jquants


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
        try:
            data = yf.download(other_tickers, period=period, progress=False, threads=True)
            if not data.empty:
                if isinstance(data.columns, pd.MultiIndex):
                    closes = data["Close"]
                else:
                    closes = data[["Close"]]
                    closes.columns = [other_tickers[0]]
                closes = closes.ffill().bfill()
        except Exception as e:
            logger.warning("yfinance取得失敗（米国株等）: %s", e)

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
        try:
            data = yf.download(missing_jp, period=period, progress=False, threads=True)
            if not data.empty:
                if isinstance(data.columns, pd.MultiIndex):
                    fb = data["Close"]
                else:
                    fb = data[["Close"]]
                    fb.columns = [missing_jp[0]]
                for col in fb.columns:
                    closes[col] = fb[col]
        except Exception as e:
            logger.warning("yfinance日本株フォールバック失敗: %s", e)

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
        div_yield = info.get("trailingAnnualDividendYield") or info.get("dividendYield") or 0.0
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
def get_ticker_name(code, market_type):
    if not code: return ""
    if market_type in ["投資信託", "その他資産"]: return "手動入力"

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
