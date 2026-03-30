"""J-Quants API V2 クライアント（日本株専用）"""
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from concurrent.futures import ThreadPoolExecutor, as_completed
from config import logger

_JST = ZoneInfo("Asia/Tokyo")
_BASE = "https://api.jquants.com/v2"


def _api_key():
    return st.secrets.get("jquants_api_key", "")


def _headers():
    return {"x-api-key": _api_key()}


def _get(path, params=None):
    """J-Quants V2 API GET（ページネーション対応）"""
    if not _api_key():
        return None
    results = []
    url = f"{_BASE}{path}"
    try:
        while url:
            resp = requests.get(url, headers=_headers(), params=params, timeout=15)
            if resp.status_code != 200:
                logger.debug("J-Quants %s HTTP %s: %s", path, resp.status_code, resp.text[:300])
                return None
            data = resp.json()
            logger.debug("J-Quants %s keys: %s, count=%d", path, list(data.keys()), len(results))
            # レスポンスのメインキーを探す（daily_quotes, info, statements等）
            for key in data:
                if key != "pagination_key" and isinstance(data[key], list):
                    results.extend(data[key])
            # ページネーション
            pkey = data.get("pagination_key")
            if pkey:
                params = params or {}
                params["pagination_key"] = pkey
            else:
                break
    except Exception as e:
        logger.debug("J-Quants API error: %s", e)
        return None
    return results


# ══════════════════════════════════════════
# 株価取得
# ══════════════════════════════════════════
def _fetch_single_quote(code, from_date, to_date):
    """1銘柄の株価を取得（並列実行用）"""
    c = str(code).replace(".T", "").strip()
    if not c or len(c) < 3:
        return None, None
    data = _get("/equities/bars/daily", {"code": c, "from": from_date, "to": to_date})
    if data:
        df = pd.DataFrame(data)
        logger.debug("J-Quants OK %s: %d rows, cols=%s", c, len(df), list(df.columns)[:8])
        if not df.empty and ("Date" in df.columns):
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.sort_values("Date")
            if "AC" in df.columns:
                close_col = "AC"
            elif "AdjustmentClose" in df.columns:
                close_col = "AdjustmentClose"
            elif "C" in df.columns:
                close_col = "C"
            elif "Close" in df.columns:
                close_col = "Close"
            else:
                logger.debug("J-Quants %s: 終値カラムが見つからない cols=%s", c, list(df.columns))
                return c, None
            entries = []
            for _, row in df.iterrows():
                entries.append({
                    "Date": row["Date"],
                    "Close": float(row.get(close_col, 0) or 0),
                })
            return c, entries
    else:
        logger.debug("J-Quants FAIL %s: data=None", c)
    return c, None


@st.cache_data(ttl=600, show_spinner=False)
def get_daily_quotes(codes, days=5):
    """日本株の直近N日の終値を取得（並列化）。{銘柄コード: [{Date, Close}, ...]}"""
    if not _api_key() or not codes:
        logger.debug("J-Quants: APIキーなし or コードなし. key=%s, codes=%s", bool(_api_key()), codes)
        return {}
    today = datetime.now(_JST)
    from_date = (today - timedelta(days=days + 10)).strftime("%Y%m%d")
    to_date = today.strftime("%Y%m%d")
    result = {}
    with ThreadPoolExecutor(max_workers=min(len(codes), 5)) as executor:
        futures = {executor.submit(_fetch_single_quote, code, from_date, to_date): code for code in codes}
        for future in as_completed(futures):
            try:
                c, entries = future.result()
                if c and entries:
                    result[c] = entries
            except Exception as e:
                logger.debug("J-Quants parallel fetch error: %s", e)
    logger.debug("J-Quants get_daily_quotes result keys: %s", list(result.keys()))
    return result


def get_latest_prices(codes):
    """日本株の最新終値を返す。{銘柄コード: {price, change_pct}}"""
    quotes = get_daily_quotes(codes, days=5)
    result = {}
    for code, entries in quotes.items():
        if len(entries) >= 1:
            latest = entries[-1]["Close"]
            change_pct = None
            if len(entries) >= 2 and entries[-2]["Close"] > 0:
                change_pct = ((latest / entries[-2]["Close"]) - 1) * 100
            result[code] = {"price": latest, "change_pct": change_pct}
    return result


# ══════════════════════════════════════════
# 銘柄情報（セクター等）
# ══════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def get_listed_info(code=None):
    """銘柄情報を取得。codeを指定すれば1銘柄、Noneなら全銘柄"""
    params = {}
    if code:
        c = str(code).replace(".T", "").strip()
        params["code"] = c
    data = _get("/equities/master", params)
    if not data:
        return {}
    if data:
        logger.debug("J-Quants master sample keys: %s", list(data[0].keys()) if data else "empty")
    result = {}
    for item in data:
        c = str(item.get("Code", ""))[:4]
        result[c] = {
            "name": item.get("CoName", "") or item.get("CompanyName", ""),
            "name_en": item.get("CoNameEn", "") or item.get("CompanyNameEnglish", ""),
            "sector17": item.get("S17Nm", "") or item.get("Sector17CodeName", ""),
            "sector33": item.get("S33Nm", "") or item.get("Sector33CodeName", ""),
            "market": item.get("MktNm", "") or item.get("MarketCodeName", ""),
        }
    return result


# ══════════════════════════════════════════
# 財務情報（配当利回り含む）
# ══════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def get_fin_statements(code):
    """直近の財務サマリーを取得"""
    c = str(code).replace(".T", "").strip()
    data = _get("/fins/summary", {"code": c})
    if not data:
        return {}
    # 最新の決算データを返す
    df = pd.DataFrame(data)
    if df.empty:
        return {}
    df = df.sort_values("DisclosedDate", ascending=False)
    latest = df.iloc[0].to_dict()
    return latest


def is_available():
    """J-Quants APIが利用可能か確認"""
    return bool(_api_key())
