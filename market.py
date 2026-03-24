"""
市場データ取得: yfinance + 並列化

改善点:
  #3 yfinance障害フォールバック — 取得成功時に最終価格を保存、失敗時に復元
"""
import streamlit as st
import pandas as pd
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import logger, SECTOR_MAP
from data import save_last_prices, load_last_prices

@st.cache_data(ttl=600, show_spinner=False)
def get_cached_market_data(tickers_tuple, period="1y"):
    tickers = list(tickers_tuple)
    if not tickers: return pd.DataFrame()
    try:
        data = yf.download(tickers, period=period, progress=False, threads=True)
        if data.empty:
            raise ValueError("yfinanceから空データ")
        if isinstance(data.columns, pd.MultiIndex):
            closes = data["Close"]
        else:
            closes = data[["Close"]]
            closes.columns = [tickers[0]]
        closes = closes.ffill().bfill()
        # 成功時: 最終価格をSheetsに保存（フォールバック用）
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
    except Exception as e:
        logger.error("yfinance取得失敗 — フォールバック価格を使用: %s", e)
        # フォールバック: Sheetsに保存された最終価格から疑似DataFrameを生成
        fallback = load_last_prices()
        if fallback:
            fb_data = {t: [fallback.get(t, 0.0)] for t in tickers if t in fallback}
            if fb_data:
                fb_df = pd.DataFrame(fb_data, index=[pd.Timestamp.now()])
                st.warning("⚠ yfinanceから株価を取得できませんでした。前回取得した価格を表示しています。")
                return fb_df
        return pd.DataFrame()

def _fetch_single_info(t):
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
    tickers = list(tickers_tuple)
    info_dict = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_single_info, t): t for t in tickers}
        for future in as_completed(futures):
            t, result = future.result()
            if result is not None: info_dict[t] = result
    return info_dict

@st.cache_data(ttl=3600, show_spinner=False)
def get_ticker_name(code, market_type):
    if not code: return ""
    if market_type in ["投資信託", "その他資産"]: return "手動入力"
    try:
        t = f"{code}.T" if market_type == "日本株" else code
        info = yf.Ticker(t).info
        return info.get("longName", info.get("shortName", "名称不明"))
    except Exception as e:
        logger.warning("銘柄名取得失敗 %s: %s", code, e)
        return "取得失敗"
