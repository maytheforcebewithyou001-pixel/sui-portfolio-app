"""データ層: Google Sheets 読み書き・マイグレーション・履歴管理"""
import streamlit as st
import pandas as pd
import json
import gspread
from google.oauth2.service_account import Credentials
from config import logger, EXPECTED_COLS, normalize_broker, normalize_tax

@st.cache_resource
def init_gspread():
    try:
        creds_json = json.loads(st.secrets["gcp_credentials"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
        return gspread.authorize(credentials)
    except Exception as e:
        logger.error("GCP認証エラー: %s", e)
        st.error(f"認証エラー: {e}")
        return None

@st.cache_resource
def get_spreadsheet():
    gc = init_gspread()
    if gc is None: return None
    try:
        return gc.open("PortfolioData")
    except Exception as e:
        logger.error("スプレッドシートを開けません: %s", e)
        st.error(f"スプレッドシートを開けません: {e}")
        return None

def _migrate_account_columns(df):
    has_broker = "口座" in df.columns
    has_tax = "口座区分" in df.columns
    if has_tax and not has_broker:
        def _split(val):
            val = str(val)
            if "NISA" in val: return "SBI証券", normalize_tax(val)
            return normalize_broker(val), "特定口座"
        split = df["口座区分"].apply(_split)
        df["口座"] = split.apply(lambda x: x[0])
        df["口座区分"] = split.apply(lambda x: x[1])
    elif has_broker and not has_tax:
        df["口座"] = df["口座"].apply(normalize_broker)
        df["口座区分"] = "特定口座"
    elif has_broker and has_tax:
        df["口座"] = df["口座"].apply(normalize_broker)
        df["口座区分"] = df["口座区分"].apply(normalize_tax)
    return df

def _fill_missing_columns(df):
    defaults = {"口座": "SBI証券", "口座区分": "特定口座", "手動配当利回り(%)": 0.0,
                "年間配当金(円/株)": 0.0, "取得時為替": 0.0, "配当月": ""}
    for col in EXPECTED_COLS:
        if col not in df.columns:
            df[col] = defaults.get(col, "-")
    return df

def _cast_numeric_columns(df):
    df["銘柄コード"] = df["銘柄コード"].astype(str)
    df["銘柄名"] = df["銘柄名"].astype(str)
    for col, fill in {"保有株数": 0, "取得単価": 0, "手動配当利回り(%)": 0.0,
                       "年間配当金(円/株)": 0.0, "取得時為替": 0.0}.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(fill)
    return df

@st.cache_data(ttl=120, show_spinner=False)
def load_data():
    sh = get_spreadsheet()
    if sh is None: return pd.DataFrame(columns=EXPECTED_COLS)
    try:
        all_values = sh.sheet1.get_all_values()
        if not all_values or len(all_values) < 2: return pd.DataFrame(columns=EXPECTED_COLS)
        raw_headers = all_values[0]
        valid_col_count = max((i + 1 for i, h in enumerate(raw_headers) if h.strip()), default=0)
        if valid_col_count == 0: return pd.DataFrame(columns=EXPECTED_COLS)
        headers = raw_headers[:valid_col_count]
        rows = [row[:valid_col_count] for row in all_values[1:]
                if any(cell.strip() for cell in row[:valid_col_count])]
        if not rows: return pd.DataFrame(columns=EXPECTED_COLS)
        df = pd.DataFrame(rows, columns=headers)
        df = _migrate_account_columns(df)
        df = _fill_missing_columns(df)
        df = _cast_numeric_columns(df)
        ordered = [c for c in EXPECTED_COLS if c in df.columns]
        extra = [c for c in df.columns if c not in EXPECTED_COLS]
        return df[ordered + extra]
    except Exception as e:
        logger.error("データ読み込みエラー: %s", e)
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame(columns=EXPECTED_COLS)

def save_data(df):
    sh = get_spreadsheet()
    if sh is None: return
    try:
        sh.sheet1.clear()
        save_df = df.fillna("")
        sh.sheet1.update([save_df.columns.values.tolist()] + save_df.values.tolist())
    except Exception as e:
        logger.error("データ保存エラー: %s", e)

@st.cache_data(ttl=120, show_spinner=False)
def load_fund_prices():
    sh = get_spreadsheet()
    if sh is None: return {}
    try:
        ws = sh.worksheet("投信価格")
        all_values = ws.get_all_values()
        if not all_values or len(all_values) < 2: return {}
        fund_prices = {}
        for row in all_values[1:]:
            if len(row) >= 3 and row[0].strip() and row[2].strip():
                try: fund_prices[row[0].strip()] = float(str(row[2]).replace(",", ""))
                except (ValueError, TypeError): pass
        return fund_prices
    except Exception: return {}

@st.cache_data(ttl=120, show_spinner=False)
def load_history():
    sh = get_spreadsheet()
    empty = pd.DataFrame(columns=["日付", "総資産額(円)"])
    if sh is None: return empty
    try:
        try: worksheet = sh.worksheet("HistoryData")
        except gspread.exceptions.WorksheetNotFound:
            worksheet = sh.add_worksheet(title="HistoryData", rows="1000", cols="2")
            worksheet.append_row(["日付", "総資産額(円)"])
        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) < 2: return empty
        rows = [r for r in all_values[1:] if any(c.strip() for c in r)]
        if not rows: return empty
        df = pd.DataFrame(rows, columns=all_values[0])
        df["総資産額(円)"] = pd.to_numeric(df["総資産額(円)"], errors="coerce").fillna(0)
        return df
    except Exception as e:
        logger.error("履歴読み込みエラー: %s", e)
        return empty

def save_history(date_str, total_asset):
    sh = get_spreadsheet()
    if sh is None: return
    try:
        worksheet = sh.worksheet("HistoryData")
        worksheet.append_row([date_str, total_asset])
    except Exception as e:
        logger.error("履歴保存エラー: %s", e)

def load_ai_review():
    sh = get_spreadsheet()
    if sh is None: return None, ""
    try:
        ws = sh.worksheet("AI総評")
        vals = ws.get_all_values()
        if len(vals) >= 2 and vals[1][0]: return vals[1][0], vals[1][1]
    except Exception as e:
        logger.debug("AI総評シートなし: %s", e)
    return None, ""

def save_ai_review(dt_str, text):
    sh = get_spreadsheet()
    if sh is None: return
    try:
        try: ws = sh.worksheet("AI総評")
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title="AI総評", rows="5", cols="2")
            ws.update_cell(1, 1, "生成日時")
            ws.update_cell(1, 2, "分析レポート")
        ws.update_cell(2, 1, dt_str)
        ws.update_cell(2, 2, text)
    except Exception as e:
        logger.error("AI総評保存エラー: %s", e)
        st.warning(f"保存エラー: {e}")
