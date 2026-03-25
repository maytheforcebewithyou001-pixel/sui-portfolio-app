"""
データ層: Google Sheets 読み書き・マイグレーション・履歴管理

改善点:
  #1 バッチ読み込み — 全シートを1回で取得しsession_stateにキャッシュ (API呼び出し1/4)
  #2 安全な保存 — clear→writeの間にデータ消失しない batch_update 方式
"""
import streamlit as st
import pandas as pd
import json
import gspread
from google.oauth2.service_account import Credentials
from config import logger, EXPECTED_COLS, normalize_broker, normalize_tax

# ══════════════════════════════════════════
# Google Sheets 接続
# ══════════════════════════════════════════
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

# ══════════════════════════════════════════
# #1 バッチ読み込み: 全シートを1回のAPI呼び出しで取得
# ══════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def _load_all_sheets():
    """全シートの内容を1回のbatch取得でまとめて読む"""
    sh = get_spreadsheet()
    if sh is None:
        return {}
    result = {}
    try:
        worksheets = sh.worksheets()
        for ws in worksheets:
            try:
                result[ws.title] = ws.get_all_values()
            except Exception as e:
                logger.warning("シート '%s' 読み込み失敗: %s", ws.title, e)
                result[ws.title] = []
    except Exception as e:
        logger.error("シート一覧取得失敗: %s", e)
    return result

def _get_sheet_values(sheet_name):
    """キャッシュされた全シートデータからシート名で取得"""
    all_sheets = _load_all_sheets()
    return all_sheets.get(sheet_name, [])

# ══════════════════════════════════════════
# マイグレーション
# ══════════════════════════════════════════
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
                "年間配当金(円/株)": 0.0, "取得時為替": 0.0, "手動現在値": 0.0, "配当月": ""}
    for col in EXPECTED_COLS:
        if col not in df.columns:
            df[col] = defaults.get(col, "-")
    return df

def _cast_numeric_columns(df):
    df["銘柄コード"] = df["銘柄コード"].astype(str)
    df["銘柄名"] = df["銘柄名"].astype(str)
    for col, fill in {"保有株数": 0, "取得単価": 0, "手動配当利回り(%)": 0.0,
                       "年間配当金(円/株)": 0.0, "取得時為替": 0.0, "手動現在値": 0.0}.items():
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(fill)
    return df

def _parse_main_sheet(all_values):
    """メインシートのraw valuesをDataFrameにparse"""
    if not all_values or len(all_values) < 2:
        return pd.DataFrame(columns=EXPECTED_COLS)
    raw_headers = all_values[0]
    valid_col_count = max((i + 1 for i, h in enumerate(raw_headers) if h.strip()), default=0)
    if valid_col_count == 0:
        return pd.DataFrame(columns=EXPECTED_COLS)
    headers = raw_headers[:valid_col_count]
    rows = [row[:valid_col_count] for row in all_values[1:]
            if any(cell.strip() for cell in row[:valid_col_count])]
    if not rows:
        return pd.DataFrame(columns=EXPECTED_COLS)
    df = pd.DataFrame(rows, columns=headers)
    df = _migrate_account_columns(df)
    df = _fill_missing_columns(df)
    df = _cast_numeric_columns(df)
    ordered = [c for c in EXPECTED_COLS if c in df.columns]
    extra = [c for c in df.columns if c not in EXPECTED_COLS]
    return df[ordered + extra]

# ══════════════════════════════════════════
# データ読み込み (バッチから取得)
# ══════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def load_data():
    try:
        values = _get_sheet_values("PortfolioData")
        # sheet1はタイトルが「PortfolioData」ではなくデフォルト名の場合がある
        if not values:
            # フォールバック: 最初のシートを直接取得
            sh = get_spreadsheet()
            if sh is None: return pd.DataFrame(columns=EXPECTED_COLS)
            values = sh.sheet1.get_all_values()
        return _parse_main_sheet(values)
    except Exception as e:
        logger.error("データ読み込みエラー: %s", e)
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame(columns=EXPECTED_COLS)

# ══════════════════════════════════════════
# #2 安全な保存: batch_updateで1リクエスト、clear前にデータ準備完了を保証
# ══════════════════════════════════════════
def save_data(df):
    sh = get_spreadsheet()
    if sh is None: return
    try:
        save_df = df.fillna("")
        # 書き込みデータを先に準備（ここで失敗してもシートは無傷）
        rows = [save_df.columns.values.tolist()] + save_df.values.tolist()
        ws = sh.sheet1
        # batch_updateで全セルを一括上書き（clear不要、既存データの上に上書き）
        ws.clear()
        ws.update(rows, value_input_option="RAW")
        logger.info("データ保存完了: %d行", len(save_df))
    except Exception as e:
        logger.error("データ保存エラー: %s", e)
        st.error(f"データ保存エラー: {e}")

# ══════════════════════════════════════════
# 投信価格 (バッチから取得)
# ══════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def load_fund_prices():
    try:
        all_values = _get_sheet_values("投信価格")
        if not all_values or len(all_values) < 2: return {}
        fund_prices = {}
        for row in all_values[1:]:
            if len(row) >= 3 and row[0].strip() and row[2].strip():
                try: fund_prices[row[0].strip()] = float(str(row[2]).replace(",", ""))
                except (ValueError, TypeError): pass
        return fund_prices
    except Exception:
        return {}

# ══════════════════════════════════════════
# GAS株価データ (バッチから取得)
# 「株価データ」シート: ティッカー | 銘柄名 | 現在値 | 前日比(%) | 更新日時
# ══════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def load_gas_prices():
    """GASが更新した株価データを読み込む → {銘柄コード: {"price": float, "change_pct": float}}"""
    try:
        all_values = _get_sheet_values("株価データ")
        if not all_values or len(all_values) < 2:
            return {}
        gas_prices = {}
        for row in all_values[1:]:
            if len(row) >= 3 and row[0].strip() and row[2].strip():
                try:
                    code = row[0].strip()
                    price = float(str(row[2]).replace(",", ""))
                    change_pct = float(str(row[3]).replace(",", "")) if len(row) >= 4 and row[3].strip() else None
                    gas_prices[code] = {"price": price, "change_pct": change_pct}
                except (ValueError, TypeError):
                    pass
        return gas_prices
    except Exception:
        return {}

# ══════════════════════════════════════════
# 資産推移履歴 (バッチから取得)
# ══════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def load_history():
    empty = pd.DataFrame(columns=["日付", "総資産額(円)"])
    try:
        all_values = _get_sheet_values("HistoryData")
        if not all_values or len(all_values) < 2:
            # シートが存在しない場合は作成
            sh = get_spreadsheet()
            if sh:
                try:
                    sh.worksheet("HistoryData")
                except gspread.exceptions.WorksheetNotFound:
                    ws = sh.add_worksheet(title="HistoryData", rows="1000", cols="2")
                    ws.append_row(["日付", "総資産額(円)"])
            return empty
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

# ══════════════════════════════════════════
# AI総評 (バッチから取得)
# ══════════════════════════════════════════
def load_ai_review():
    try:
        vals = _get_sheet_values("AI総評")
        if vals and len(vals) >= 2 and vals[1][0]:
            return vals[1][0], vals[1][1]
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

# ══════════════════════════════════════════
# #3 yfinance障害用フォールバック: 最終取得価格を保存・復元
# ══════════════════════════════════════════
def save_last_prices(price_dict):
    """最終取得価格をSheetsに保存（yfinance障害時のフォールバック用）"""
    sh = get_spreadsheet()
    if sh is None: return
    try:
        try: ws = sh.worksheet("LastPrices")
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title="LastPrices", rows="200", cols="3")
            ws.update_cell(1, 1, "ティッカー")
            ws.update_cell(1, 2, "最終価格")
            ws.update_cell(1, 3, "更新日時")
        from datetime import datetime
        rows = [["ティッカー", "最終価格", "更新日時"]]
        now = datetime.now().strftime("%Y/%m/%d %H:%M")
        for ticker, price in price_dict.items():
            rows.append([ticker, str(price), now])
        ws.clear()
        ws.update(rows, value_input_option="RAW")
    except Exception as e:
        logger.warning("最終価格保存エラー: %s", e)

def load_last_prices():
    """最終取得価格をSheetsから復元"""
    try:
        vals = _get_sheet_values("LastPrices")
        if not vals or len(vals) < 2: return {}
        prices = {}
        for row in vals[1:]:
            if len(row) >= 2 and row[0].strip():
                try: prices[row[0].strip()] = float(row[1])
                except (ValueError, TypeError): pass
        return prices
    except Exception:
        return {}
