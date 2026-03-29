"""J-Quants API V2 クライアント（日本株専用）"""
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
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
                logger.warning("J-Quants %s HTTP %s: %s", path, resp.status_code, resp.text[:300])
                return None
            data = resp.json()
            logger.info("J-Quants %s keys: %s", path, list(data.keys()))
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
        logger.warning("J-Quants API error: %s", e)
        return None
    return results


# ══════════════════════════════════════════
# 株価取得
# ══════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def get_daily_quotes(codes, days=5):
    """日本株の直近N日の終値を取得。{銘柄コード: [{Date, Close, AdjClose, Change%}, ...]}"""
    if not _api_key() or not codes:
        return {}
    today = datetime.now(_JST)
    from_date = (today - timedelta(days=days + 10)).strftime("%Y%m%d")  # 余裕を持つ
    to_date = today.strftime("%Y%m%d")
    result = {}
    for code in codes:
        # J-Quantsは4桁コード（.T不要）、英字含むコードもある（例: 166A）
        c = str(code).replace(".T", "").strip()
        if not c or len(c) < 3:
            continue
        data = _get("/equities/bars/daily", {"code": c, "from": from_date, "to": to_date})
        if data:
            df = pd.DataFrame(data)
            if not df.empty and "Date" in df.columns:
                df["Date"] = pd.to_datetime(df["Date"])
                df = df.sort_values("Date")
                close_col = "AdjustmentClose" if "AdjustmentClose" in df.columns else "Close"
                entries = []
                for _, row in df.iterrows():
                    entries.append({
                        "Date": row["Date"],
                        "Close": float(row.get(close_col, 0) or 0),
                    })
                result[c] = entries
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
    result = {}
    for item in data:
        c = str(item.get("Code", ""))[:4]
        result[c] = {
            "name": item.get("CompanyName", "") or item.get("company_name", ""),
            "name_en": item.get("CompanyNameEnglish", "") or item.get("company_name_english", ""),
            "sector17": item.get("Sector17CodeName", "") or item.get("sector17_code_name", ""),
            "sector33": item.get("Sector33CodeName", "") or item.get("sector33_code_name", ""),
            "market": item.get("MarketCodeName", "") or item.get("market_code_name", ""),
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
