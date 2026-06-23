"""J-Quants データ取得（CLI優先 → HTTP API V2 フォールバック）

ローカル環境: jquants CLI (Rust binary) が PATH にあれば CLI 経由で取得
Streamlit Cloud: CLI がないため従来の HTTP API V2 を使用
"""
import streamlit as st
import pandas as pd
import subprocess
import shutil
import json
import time
import os
import requests
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from config import logger

_JST = ZoneInfo("Asia/Tokyo")
_BASE = "https://api.jquants.com/v2"

# CLI検出（起動時に1回だけ）
_CLI_PATH = shutil.which("jquants")
_USE_CLI = _CLI_PATH is not None

if _USE_CLI:
    logger.info("J-Quants CLI detected: %s", _CLI_PATH)
else:
    logger.info("J-Quants CLI not found, using HTTP API")


# ══════════════════════════════════════════
# API key
# ══════════════════════════════════════════
def _api_key():
    # CLI は .env / credentials.json から自動読み込みするため secrets 不要
    return os.environ.get("JQUANTS_API_KEY", "") or st.secrets.get("jquants_api_key", "")


# ══════════════════════════════════════════
# CLI wrapper
# ══════════════════════════════════════════
def _cli(args, cwd=None):
    """jquants CLI を実行し JSON を返す。失敗時は None。"""
    cmd = [_CLI_PATH, "--output", "json"] + args
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
            encoding="utf-8", cwd=cwd,
            env={**os.environ, "JQUANTS_API_KEY": _api_key()},
        )
        if r.returncode != 0:
            stderr = r.stderr.strip()
            if "429" in stderr:
                # Rate limit — retry once after 2s
                time.sleep(2)
                r = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=30,
                    encoding="utf-8", cwd=cwd,
                    env={**os.environ, "JQUANTS_API_KEY": _api_key()},
                )
                if r.returncode != 0:
                    logger.warning("J-Quants CLI retry failed: %s", stderr)
                    return None
            else:
                logger.warning("J-Quants CLI error: %s", stderr[:300])
                return None
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        logger.warning("J-Quants CLI: invalid JSON output")
        return None
    except subprocess.TimeoutExpired:
        logger.warning("J-Quants CLI: timeout")
        return None
    except Exception as e:
        logger.warning("J-Quants CLI error: %s", e)
        return None


# ══════════════════════════════════════════
# HTTP API fallback
# ══════════════════════════════════════════
def _headers():
    return {"x-api-key": _api_key()}


def _http_get(path, params=None):
    """J-Quants V2 API GET（ページネーション対応）"""
    if not _api_key():
        return None
    results = []
    url = f"{_BASE}{path}"
    try:
        while url:
            resp = requests.get(url, headers=_headers(), params=params, timeout=15)
            if resp.status_code == 429:
                for attempt in range(3):
                    wait = int(resp.headers.get("Retry-After", 2 ** (attempt + 1)))
                    logger.warning("J-Quants HTTP %s 429, retry %d/3 after %ds", path, attempt + 1, wait)
                    time.sleep(wait)
                    resp = requests.get(url, headers=_headers(), params=params, timeout=15)
                    if resp.status_code != 429:
                        break
                if resp.status_code == 429:
                    return None
            if resp.status_code != 200:
                logger.warning("J-Quants HTTP %s %s: %s", path, resp.status_code, resp.text[:300])
                return None
            data = resp.json()
            for key in data:
                if key != "pagination_key" and isinstance(data[key], list):
                    results.extend(data[key])
            pkey = data.get("pagination_key")
            if pkey:
                params = params or {}
                params["pagination_key"] = pkey
            else:
                break
    except Exception as e:
        logger.warning("J-Quants HTTP error: %s", e)
        return None
    return results


# ══════════════════════════════════════════
# 株価取得
# ══════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def get_daily_quotes(codes, days=5):
    """日本株の直近N日の終値を取得。
    Returns: {銘柄コード: [{Date, Close}, ...]}
    """
    if not _api_key() and not _USE_CLI:
        logger.debug("J-Quants: APIキーなし & CLIなし")
        return {}
    if not codes:
        return {}

    today = datetime.now(_JST)
    from_date = (today - timedelta(days=days + 10)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")
    result = {}

    for code in codes:
        c = str(code).replace(".T", "").strip()
        if not c or len(c) < 3:
            continue

        entries = _fetch_daily_single(c, from_date, to_date)
        if entries:
            result[c] = entries

    logger.debug("J-Quants get_daily_quotes: %d/%d codes fetched", len(result), len(codes))
    return result


def _fetch_daily_single(code, from_date, to_date):
    """1銘柄の日足を取得。CLI → HTTP フォールバック。"""
    entries = None

    # ── CLI ──
    if _USE_CLI:
        data = _cli(["eq", "daily", "--code", code, "--from", from_date, "--to", to_date])
        if data:
            entries = _parse_daily(data, code)

    # ── HTTP fallback ──
    if entries is None:
        from_compact = from_date.replace("-", "")
        to_compact = to_date.replace("-", "")
        data = _http_get("/equities/bars/daily", {"code": code, "from": from_compact, "to": to_compact})
        if data:
            entries = _parse_daily(data, code)

    return entries


def _parse_daily(data, code):
    """CLI / HTTP のどちらのレスポンスからも [{Date, Close}] を生成。"""
    if not data:
        return None
    df = pd.DataFrame(data)
    if df.empty or "Date" not in df.columns:
        return None

    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date")

    # カラム名の違いを吸収 (CLI: AdjC, HTTP API: AC/AdjustmentClose/C/Close)
    close_col = None
    for candidate in ("AdjC", "AC", "AdjustmentClose", "C", "Close"):
        if candidate in df.columns:
            close_col = candidate
            break
    if close_col is None:
        logger.warning("J-Quants %s: 終値カラムが見つからない cols=%s", code, list(df.columns))
        return None

    entries = []
    for _, row in df.iterrows():
        val = row.get(close_col, 0)
        if val is None:
            continue
        entries.append({"Date": row["Date"], "Close": float(val)})
    return entries if entries else None


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
    """銘柄情報を取得。codeを指定すれば1銘柄、Noneなら全銘柄。"""
    data = None

    # ── CLI ──
    if _USE_CLI:
        args = ["eq", "master"]
        if code:
            c = str(code).replace(".T", "").strip()
            args += ["--code", c]
        data = _cli(args)

    # ── HTTP fallback ──
    if data is None:
        params = {}
        if code:
            c = str(code).replace(".T", "").strip()
            params["code"] = c
        data = _http_get("/equities/master", params)

    if not data:
        return {}

    result = {}
    for item in data:
        c = str(item.get("Code", ""))[:4]
        # CLI field names: CoName, CoNameEn, S17Nm, S33Nm, MktNm
        # HTTP field names may differ: CompanyName, Sector17CodeName, etc.
        result[c] = {
            "name": item.get("CoName", "") or item.get("CompanyName", ""),
            "name_en": item.get("CoNameEn", "") or item.get("CompanyNameEnglish", ""),
            "sector17": item.get("S17Nm", "") or item.get("Sector17CodeName", ""),
            "sector33": item.get("S33Nm", "") or item.get("Sector33CodeName", ""),
            "market": item.get("MktNm", "") or item.get("MarketCodeName", ""),
        }
    return result


# ══════════════════════════════════════════
# 財務情報
# ══════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def get_fin_statements(code):
    """直近の財務サマリーを取得。"""
    c = str(code).replace(".T", "").strip()
    data = None

    # ── CLI ──
    if _USE_CLI:
        data = _cli(["fins", "summary", "--code", c])

    # ── HTTP fallback ──
    if data is None:
        data = _http_get("/fins/summary", {"code": c})

    if not data:
        return {}

    df = pd.DataFrame(data)
    if df.empty:
        return {}

    # CLI: DiscDate, HTTP: DisclosedDate — normalize
    date_col = "DiscDate" if "DiscDate" in df.columns else "DisclosedDate"
    if date_col in df.columns:
        df = df.sort_values(date_col, ascending=False)

    return df.iloc[0].to_dict()


# ══════════════════════════════════════════
# 投資部門別売買 (TSEPrime)
# ══════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def get_investor_types(weeks=12, section="TSEPrime"):
    """投資部門別売買代金を取得。海外/個人/信託銀行等のネット買越額。

    Returns: pd.DataFrame
        週末日(EnDate) と 各部門の Bal カラム
        FrgnBal=海外, IndBal=個人, TrstBnkBal=信託銀行, InvTrBal=投信, BusCoBal=事業法人 等
    """
    if not _api_key() and not _USE_CLI:
        return pd.DataFrame()

    today = datetime.now(_JST)
    from_date = (today - timedelta(days=weeks * 7 + 14)).strftime("%Y-%m-%d")
    to_date = today.strftime("%Y-%m-%d")

    data = None
    # ── HTTP fallback ──
    params = {"section": section,
              "from": from_date.replace("-", ""),
              "to": to_date.replace("-", "")}
    data = _http_get("/equities/investor-types", params)

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    if df.empty:
        return df

    # 日付変換
    for col in ["PubDate", "StDate", "EnDate"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    # 数値変換
    skip = {"Section", "StDate", "EnDate", "PubDate"}
    for col in df.columns:
        if col not in skip:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "EnDate" in df.columns:
        df = df.sort_values("EnDate").reset_index(drop=True)
    return df


# ══════════════════════════════════════════
# TOPIX OHLC
# ══════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def get_topix_ohlc(period_days=400):
    """TOPIX 日足を取得。
    Returns: pd.DataFrame with columns [Date, Open, High, Low, Close]
    (V2の短縮カラム名 O/H/L/C も自動で長名へ正規化)
    """
    if not _api_key() and not _USE_CLI:
        return pd.DataFrame()

    today = datetime.now(_JST)
    from_date = (today - timedelta(days=period_days)).strftime("%Y%m%d")
    to_date = today.strftime("%Y%m%d")
    data = _http_get("/indices/bars/daily/topix", {"from": from_date, "to": to_date})

    if not data:
        return pd.DataFrame()

    df = pd.DataFrame(data)
    if df.empty or "Date" not in df.columns:
        return pd.DataFrame()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    # V2 短縮名 → 長名 へ正規化
    rename_map = {"O": "Open", "H": "High", "L": "Low", "C": "Close"}
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns and v not in df.columns})
    for col in ("Open", "High", "Low", "Close"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["Date"]).sort_values("Date").reset_index(drop=True)


# ══════════════════════════════════════════
# 財務サマリ時系列（過去N四半期）
# ══════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def get_fin_statements_history(code, limit=8):
    """直近N件分の財務サマリーを開示日昇順で返す。"""
    c = str(code).replace(".T", "").strip()
    data = None
    if _USE_CLI:
        data = _cli(["fins", "summary", "--code", c])
    if data is None:
        data = _http_get("/fins/summary", {"code": c})
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if df.empty:
        return pd.DataFrame()
    date_col = "DiscDate" if "DiscDate" in df.columns else "DisclosedDate"
    if date_col not in df.columns:
        return df
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.sort_values(date_col, ascending=False).head(limit).sort_values(date_col).reset_index(drop=True)
    return df


# ══════════════════════════════════════════
# 減配検知（配当予想 vs 前期実績）
# ══════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def get_dividend_status(code):
    """財務サマリから年間配当(予想/実績)を取り、減配の兆候を判定。

    Returns: dict | None
      {current: 現在の年間配当予想(円/株), prior: 直近の年間配当実績(円/株),
       pct: 変化率%, is_cut: bool}
    ※ /fins/summary の配当DPSは分割未調整。減配判定は人手確認が前提（分割で誤検知しうる）。
    """
    fh = get_fin_statements_history(code, limit=8)
    if fh is None or fh.empty:
        return None
    fcst_cols = ("NextYearForecastDividendPerShareAnnual", "ForecastDividendPerShareAnnual")
    res_col = "ResultDividendPerShareAnnual"
    if res_col not in fh.columns and not any(c in fh.columns for c in fcst_cols):
        return None  # 配当フィールドが取得できない（プラン/エンドポイント差異）

    # 実績年間配当の時系列（>0のみ）
    results = []
    if res_col in fh.columns:
        for v in pd.to_numeric(fh[res_col], errors="coerce").tolist():
            if pd.notna(v) and v > 0:
                results.append(float(v))

    # 現在の年間配当予想（最新レコード：翌期予想 → 当期予想）
    current = None
    last = fh.iloc[-1]
    for col in fcst_cols:
        if col in fh.columns:
            v = pd.to_numeric(last.get(col), errors="coerce")
            if pd.notna(v) and v > 0:
                current = float(v)
                break

    prior = results[-1] if results else None
    if current is None:
        # 予想が無ければ実績の前年比で判定
        if len(results) >= 2:
            current, prior = results[-1], results[-2]
        else:
            return None
    if prior is None or prior <= 0:
        return None

    pct = (current / prior - 1) * 100
    return {"current": current, "prior": prior, "pct": pct, "is_cut": pct <= -1.0}


@st.cache_data(ttl=86400, show_spinner=False)
def scan_dividend_cuts(codes_tuple):
    """保有日本株を一括スキャンし減配の疑いがある銘柄を返す（日次キャッシュ）。

    Returns: list[{code, current, prior, pct}]
    """
    out = []
    for code in codes_tuple:
        try:
            ds = get_dividend_status(code)
        except Exception:
            ds = None
        if ds and ds.get("is_cut"):
            d = dict(ds)
            d["code"] = str(code)
            out.append(d)
    return out


# ══════════════════════════════════════════
# 決算カレンダー (yfinance + J-Quants当日分)
# ══════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def get_upcoming_earnings(codes, days_ahead=7):
    """保有銘柄の今後N日以内の決算発表予定を返す。

    yfinance Ticker.calendar の Earnings Date を使用。
    Args:
        codes: 日本株コードのリスト (4桁、例 ["8593", "2498"])
        days_ahead: 先読み日数 (デフォルト7日)
    Returns:
        list[dict]: [{code, date, days_until}, ...] (日付昇順)
    """
    import yfinance as yf
    today = datetime.now(_JST).date()
    cutoff = today + timedelta(days=days_ahead)
    result = []
    for code in codes:
        c = str(code).replace(".T", "").strip()
        if not c or len(c) < 3:
            continue
        try:
            t = yf.Ticker(f"{c}.T")
            cal = t.calendar
            if not cal:
                continue
            dates = cal.get("Earnings Date", []) or []
            for d in dates:
                if d and today <= d <= cutoff:
                    result.append({
                        "code": c,
                        "date": d,
                        "days_until": (d - today).days,
                    })
        except Exception as e:
            logger.debug("yfinance earnings %s: %s", c, e)
            continue
    result.sort(key=lambda x: x["date"])
    return result


# ══════════════════════════════════════════
# ユーティリティ
# ══════════════════════════════════════════
def is_available():
    """J-Quantsが利用可能か確認（CLI or API key）"""
    return _USE_CLI or bool(_api_key())
