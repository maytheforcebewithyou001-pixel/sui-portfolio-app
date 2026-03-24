import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import math
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="PORTFOLIO資産管理", layout="wide", initial_sidebar_state="collapsed")

# ==========================================
# 🚀 高速化エンジン ＆ データ取得
# ==========================================
@st.cache_resource
def init_gspread():
    try:
        creds_json = json.loads(st.secrets["gcp_credentials"])
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
        return gspread.authorize(credentials)
    except Exception as e:
        st.error(f"認証エラー: {e}")
        return None

@st.cache_data(ttl=600, show_spinner=False)
def get_cached_market_data(tickers_tuple, period="1y"):
    tickers = list(tickers_tuple)
    if not tickers: return pd.DataFrame()
    try:
        data = yf.download(tickers, period=period, progress=False, threads=True)
        if isinstance(data.columns, pd.MultiIndex):
            closes = data['Close']
        else:
            closes = data[['Close']]
            closes.columns = [tickers[0]]
        return closes.ffill().bfill()
    except:
        return pd.DataFrame()

def _fetch_single_info(t, sector_map):
    """1銘柄の情報取得（スレッドプール用）"""
    if t == "JPY=X": return t, None
    try:
        info = yf.Ticker(t).info
        div_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0
        div_yield = info.get("trailingAnnualDividendYield") or info.get("dividendYield") or 0.0
        if div_yield > 0.2: div_yield = 0.0
        sec = info.get("sector") or "ETF/その他"
        ex_div = info.get("exDividendDate")
        return t, {
            "sector": sector_map.get(sec, sec),
            "div_rate": float(div_rate),
            "div_yield": float(div_yield),
            "ex_div_date": ex_div,
            "name": info.get("shortName", ""),
        }
    except:
        return t, {"sector": "不明", "div_rate": 0.0, "div_yield": 0.0, "ex_div_date": None, "name": ""}

@st.cache_data(ttl=86400, show_spinner=False)
def get_cached_ticker_info(tickers_tuple):
    """★ 並列化: ThreadPoolExecutorで最大5同時取得"""
    tickers = list(tickers_tuple)
    sector_map = {
        "Technology": "テクノロジー", "Financial Services": "金融", "Healthcare": "ヘルスケア",
        "Consumer Cyclical": "一般消費財", "Industrials": "資本財", "Communication Services": "通信",
        "Consumer Defensive": "生活必需品", "Energy": "エネルギー", "Basic Materials": "素材",
        "Real Estate": "不動産", "Utilities": "公益事業"
    }
    info_dict = {}
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_fetch_single_info, t, sector_map): t for t in tickers}
        for future in as_completed(futures):
            t, result = future.result()
            if result is not None:
                info_dict[t] = result
    return info_dict

# ==========================================
# 📊 データ読み書き ＆ ヘルパー関数
# ==========================================
@st.cache_resource
def get_spreadsheet():
    """スプレッドシートオブジェクトをキャッシュ（API呼び出し1回だけ）"""
    gc = init_gspread()
    if gc is None: return None
    try:
        return gc.open("PortfolioData")
    except Exception as e:
        st.error(f"スプレッドシートを開けません: {e}")
        return None

@st.cache_data(ttl=120, show_spinner=False)
def load_fund_prices():
    """「投信価格」シートから投信の基準価額を読み込む（GASが毎日更新）"""
    sh = get_spreadsheet()
    if sh is None:
        return {}
    try:
        ws = sh.worksheet("投信価格")
        all_values = ws.get_all_values()
        if not all_values or len(all_values) < 2:
            return {}
        # {銘柄コード: 基準価額} の辞書を返す
        fund_prices = {}
        for row in all_values[1:]:
            if len(row) >= 3 and row[0].strip() and row[2].strip():
                try:
                    fund_prices[row[0].strip()] = float(str(row[2]).replace(",", ""))
                except (ValueError, TypeError):
                    pass
        return fund_prices
    except Exception:
        # シートが存在しない場合は空辞書を返す
        return {}

@st.cache_data(ttl=120, show_spinner=False)
def load_data():
    sh = get_spreadsheet()
    expected_cols = ["銘柄コード", "銘柄名", "市場", "保有株数", "取得単価", "口座", "口座区分", "手動配当利回り(%)", "配当月", "年間配当金(円/株)", "取得時為替", "最新更新日"]
    BROKER_OPTIONS = ["SBI証券", "楽天証券", "持ち株会(野村證券)"]
    TAX_OPTIONS = ["特定口座", "NISA(成長投資枠)", "NISA(積立投資枠)"]
    if sh is None: return pd.DataFrame(columns=expected_cols)
    try:
        all_values = sh.sheet1.get_all_values()
        if not all_values or len(all_values) < 2:
            return pd.DataFrame(columns=expected_cols)
        
        raw_headers = all_values[0]
        valid_col_count = 0
        for i, h in enumerate(raw_headers):
            if h.strip():
                valid_col_count = i + 1
        if valid_col_count == 0:
            return pd.DataFrame(columns=expected_cols)
        
        headers = raw_headers[:valid_col_count]
        rows = []
        for row in all_values[1:]:
            trimmed = row[:valid_col_count]
            if any(cell.strip() for cell in trimmed):
                rows.append(trimmed)
        
        if not rows:
            return pd.DataFrame(columns=expected_cols)
        
        df = pd.DataFrame(rows, columns=headers)
        
        # ── マイグレーション: 旧形式に対応 ──
        # パターン1: 「口座」のみ（旧v1形式: SBI, 楽天 等）→ 口座+口座区分に分離
        # パターン2: 「口座区分」のみ（前回の統合形式: SBI証券, NISA(成長投資枠)等）→ 口座+口座区分に分離
        # パターン3: 「口座」+「口座区分」両方あり → そのまま正規化
        
        has_broker = "口座" in df.columns
        has_tax = "口座区分" in df.columns
        
        if has_tax and not has_broker:
            # パターン2: 統合形式からの分離
            def _split_unified(val):
                val = str(val)
                if "NISA" in val:
                    tax = "NISA(積立投資枠)" if "積立" in val else "NISA(成長投資枠)"
                    return "SBI証券", tax
                if "楽天" in val: return "楽天証券", "特定口座"
                if "野村" in val or "持ち株" in val: return "持ち株会(野村證券)", "特定口座"
                if "SBI" in val: return "SBI証券", "特定口座"
                return "SBI証券", "特定口座"
            split = df["口座区分"].apply(_split_unified)
            df["口座"] = split.apply(lambda x: x[0])
            df["口座区分"] = split.apply(lambda x: x[1])
        
        elif has_broker and not has_tax:
            # パターン1: 旧形式（口座のみ）
            def _normalize_broker(val):
                val = str(val)
                if "楽天" in val: return "楽天証券"
                if "野村" in val or "持ち株" in val: return "持ち株会(野村證券)"
                return "SBI証券"
            df["口座"] = df["口座"].apply(_normalize_broker)
            df["口座区分"] = "特定口座"
        
        elif has_broker and has_tax:
            # パターン3: 両方ある → 正規化のみ
            def _norm_broker(val):
                val = str(val)
                if "楽天" in val: return "楽天証券"
                if "野村" in val or "持ち株" in val: return "持ち株会(野村證券)"
                if "SBI" in val: return "SBI証券"
                return val if val.strip() else "SBI証券"
            def _norm_tax(val):
                val = str(val)
                if "NISA" in val:
                    if "積立" in val: return "NISA(積立投資枠)"
                    return "NISA(成長投資枠)"
                return "特定口座"
            df["口座"] = df["口座"].apply(_norm_broker)
            df["口座区分"] = df["口座区分"].apply(_norm_tax)
        
        # 不足列を補完
        for col in expected_cols:
            if col not in df.columns:
                if col == "口座": df[col] = "SBI証券"
                elif col == "口座区分": df[col] = "特定口座"
                elif col == "手動配当利回り(%)": df[col] = 0.0
                elif col == "年間配当金(円/株)": df[col] = 0.0
                elif col == "取得時為替": df[col] = 0.0
                elif col == "配当月": df[col] = ""
                else: df[col] = "-"
        
        df["銘柄コード"] = df["銘柄コード"].astype(str)
        df["銘柄名"] = df["銘柄名"].astype(str)
        df["保有株数"] = pd.to_numeric(df["保有株数"], errors='coerce').fillna(0)
        df["取得単価"] = pd.to_numeric(df["取得単価"], errors='coerce').fillna(0)
        df["手動配当利回り(%)"] = pd.to_numeric(df["手動配当利回り(%)"], errors='coerce').fillna(0.0)
        df["年間配当金(円/株)"] = pd.to_numeric(df["年間配当金(円/株)"], errors='coerce').fillna(0.0)
        df["取得時為替"] = pd.to_numeric(df["取得時為替"], errors='coerce').fillna(0.0)
        
        ordered = [c for c in expected_cols if c in df.columns]
        extra = [c for c in df.columns if c not in expected_cols]
        df = df[ordered + extra]
        return df
    except Exception as e:
        st.error(f"データ読み込みエラー: {e}")
        return pd.DataFrame(columns=expected_cols)

def save_data(df):
    sh = get_spreadsheet()
    if sh is None: return
    try:
        sh.sheet1.clear()
        save_df = df.fillna("")
        sh.sheet1.update([save_df.columns.values.tolist()] + save_df.values.tolist())
    except:
        pass

@st.cache_data(ttl=120, show_spinner=False)
def load_history():
    sh = get_spreadsheet()
    if sh is None: return pd.DataFrame(columns=["日付", "総資産額(円)"])
    try:
        try: worksheet = sh.worksheet("HistoryData")
        except:
            worksheet = sh.add_worksheet(title="HistoryData", rows="1000", cols="2")
            worksheet.append_row(["日付", "総資産額(円)"])
        all_values = worksheet.get_all_values()
        if not all_values or len(all_values) < 2:
            return pd.DataFrame(columns=["日付", "総資産額(円)"])
        headers = all_values[0]
        rows = [r for r in all_values[1:] if any(c.strip() for c in r)]
        if not rows: return pd.DataFrame(columns=["日付", "総資産額(円)"])
        df = pd.DataFrame(rows, columns=headers)
        df["総資産額(円)"] = pd.to_numeric(df["総資産額(円)"], errors='coerce').fillna(0)
        return df
    except:
        return pd.DataFrame(columns=["日付", "総資産額(円)"])

def save_history(date_str, total_asset):
    sh = get_spreadsheet()
    if sh is None: return
    try:
        worksheet = sh.worksheet("HistoryData")
        worksheet.append_row([date_str, total_asset])
    except:
        pass

def get_future_simulation(current_asset, annual_rate, years, yearly_addition):
    months = years * 12
    monthly_rate = annual_rate / 12
    monthly_add = yearly_addition / 12
    today = datetime.now()
    dates, values, principals, gains = [], [], [], []
    current_val = current_asset
    current_principal = current_asset  # 初期元本
    for i in range(months + 1):
        dates.append(today + pd.DateOffset(months=i))
        values.append(current_val)
        principals.append(current_principal)
        gains.append(max(current_val - current_principal, 0))
        current_val = current_val * (1 + monthly_rate) + monthly_add
        current_principal += monthly_add
    return pd.DataFrame({"日時": dates, "予測評価額(円)": values, "積立元本(円)": principals, "運用益(円)": gains})

def get_ticker_name(code, market_type):
    if not code: return ""
    if market_type in ["投資信託", "その他資産"]: return "手動入力"
    try:
        t = f"{code}.T" if market_type == "日本株" else code
        info = yf.Ticker(t).info
        return info.get('longName', info.get('shortName', '名称不明'))
    except:
        return "取得失敗"

def round_up_3(val):
    try:
        val = float(val)
        rounded = math.ceil(val * 1000) / 1000
        return f"{int(rounded):,}" if rounded.is_integer() else f"{rounded:,.3f}".rstrip('0').rstrip('.')
    except:
        return val

# ==========================================
# 🎨 CSS（UX改善: コントラスト強化 / アニメーション / レスポンシブ）
# ==========================================
st.markdown("""
<style>
html, body, .stApp { overflow-y: auto !important; }
.stApp { background-color: #0A0E13; color: #E0E0E0; font-family: sans-serif; }

/* ヘッダー */
.logo-text { color: #00D2FF; font-weight: bold; font-size: 2.2rem; letter-spacing: 0.05rem; line-height: 1; }
.logo-text span { color: #F0F0F0; }
.logo-sub { color: #B0B0B0; font-size: 0.78rem; margin-top: 4px; }

/* ステータスカード - アニメーション付き */
@keyframes fadeSlideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes pulseGlow { 0%,100% { box-shadow: 0 4px 8px rgba(0,0,0,0.3); } 50% { box-shadow: 0 4px 16px rgba(0,210,255,0.12); } }
.status-card {
    background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px;
    padding: 1.1rem 1.2rem; margin-bottom: 0.7rem; position: relative;
    animation: fadeSlideIn 0.5s ease-out both;
    transition: transform 0.2s, box-shadow 0.2s;
}
.status-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.4); }
.c1 { animation-delay: 0s; } .c2 { animation-delay: 0.08s; } .c3 { animation-delay: 0.16s; } .c4 { animation-delay: 0.24s; }
.status-card h4 { color: #B0B8C0; font-size: 0.78rem; margin: 0 0 0.3rem 0; letter-spacing: 0.04em; font-weight: 600; }
.status-card p.mv { color: #FFFFFF; font-size: 1.55rem; font-weight: bold; margin: 0; line-height: 1.2; }
.status-card p.mv span { color: #00D2FF; font-size: 0.95rem; margin-left: 0.15rem; }
.status-card p.sv { color: #A0A8B0; font-size: 0.78rem; margin: 0.15rem 0 0 0; }
.status-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; border-radius: 10px 10px 0 0; }
.card-total::before { background: linear-gradient(90deg, #00D2FF, #3A7BD5); }
.card-profit::before { background: linear-gradient(90deg, #00E676, #69F0AE); }
.card-dividend::before { background: linear-gradient(90deg, #FFD54F, #FF8F00); }
.card-goal::before { background: linear-gradient(90deg, #9C27B0, #E040FB); }

/* ゴールバー */
.goal-bar-wrap { background: #12161E; border: 1px solid #1E232F; border-radius: 8px; padding: 0.6rem 1rem; margin-bottom: 0.8rem; }
.goal-bar-bg { background: #1E232F; border-radius: 4px; height: 8px; width: 100%; overflow: hidden; }
.goal-bar-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, #00D2FF, #00E676); transition: width 1.2s cubic-bezier(0.25,0.46,0.45,0.94); }
.goal-bar-labels { display: flex; justify-content: space-between; font-size: 0.7rem; color: #A0A8B0; margin-top: 4px; }

/* アラート */
.alert-bar { display: flex; align-items: center; gap: 8px; font-size: 0.8rem; padding: 8px 14px; border-radius: 8px; margin-bottom: 8px; }
.alert-up { background: rgba(0,230,118,0.08); color: #69F0AE; border: 1px solid rgba(0,230,118,0.2); }
.alert-down { background: rgba(255,23,68,0.08); color: #FF5252; border: 1px solid rgba(255,23,68,0.2); }

/* 口座サマリー */
.acct-badge { display: inline-block; font-size: 0.7rem; padding: 2px 8px; border-radius: 4px; margin-right: 4px; font-weight: 600; }
.acct-sbi { background: rgba(0,210,255,0.12); color: #00D2FF; }
.acct-rakuten { background: rgba(245,200,66,0.12); color: #FFD54F; }
.acct-nomura { background: rgba(189,147,249,0.12); color: #BD93F9; }
.acct-nisa-growth { background: rgba(0,230,118,0.12); color: #69F0AE; }
.acct-nisa-tsumitate { background: rgba(77,208,225,0.12); color: #4DD0E1; }
.acct-other { background: rgba(189,189,189,0.12); color: #BDBDBD; }

/* 配当カレンダー */
.div-month { text-align: center; padding: 8px 4px; border-radius: 8px; font-size: 0.75rem; }
.div-month-active { background: rgba(255,213,79,0.1); border: 1px solid rgba(255,213,79,0.3); }
.div-month-empty { background: #12161E; border: 1px solid #1E232F; color: #4A5060; }
.div-month .month-label { display: block; color: #B0B8C0; margin-bottom: 2px; font-weight: 600; }
.div-month .month-amount { display: block; color: #FFD54F; font-weight: bold; font-size: 0.85rem; }

/* ボタン */
.stButton > button { background-color: #12161E; color: #C0C8D0; border: 1px solid #1E232F; border-radius: 20px; padding: 0.5rem 1.2rem; font-size: 0.85rem; transition: all 0.2s; }
.stButton > button:hover { background-color: #1E232F; color: #FFFFFF; border-color: #00D2FF; box-shadow: 0 0 12px rgba(0,210,255,0.15); }

/* タブ */
.stTabs [data-baseweb="tab-list"] { gap: 4px; background-color: #12161E; border-radius: 10px; padding: 4px; border: 1px solid #1E232F; }
.stTabs [data-baseweb="tab"] { background: transparent; color: #A0A8B0; border-radius: 8px; padding: 8px 16px; font-weight: 600; transition: all 0.15s; }
.stTabs [data-baseweb="tab"]:hover { color: #FFFFFF; background: #1E232F; }
.stTabs [aria-selected="true"] { background: #1E232F !important; color: #00D2FF !important; }
.stTabs [data-baseweb="tab-border"], .stTabs [data-baseweb="tab-highlight"] { display: none; }

/* 指標カード */
.indicator-card { background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; transition: border-color 0.2s; }
.indicator-card:hover { border-color: #2A3040; }
.streamlit-expanderHeader { background-color: #12161E; border-radius: 10px; color: #FFFFFF; font-weight: bold; font-size: 1.1rem; border: 1px solid #1E232F; }
th { background-color: #1E232F !important; color: #FFFFFF !important; }

/* レスポンシブ */
@media (max-width: 768px) {
    .status-card p.mv { font-size: 1.1rem; }
    .status-card { padding: 0.7rem; }
    .logo-text { font-size: 1.5rem; }
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# ⚙️ サイドバー設定
# ==========================================
with st.sidebar:
    st.markdown("### ⚙️ 設定")
    goal_oku = st.slider("🎯 目標金額 (億円)", min_value=0.5, max_value=10.0, value=1.2, step=0.1)
    goal_amount = goal_oku * 1e8
    interest_rate_pct = st.slider("📈 想定年利 (%)", min_value=1.0, max_value=20.0, value=6.0, step=0.5)
    interest_rate = interest_rate_pct / 100.0
    yearly_add_man = st.number_input("💰 年間積立額 (万円)", min_value=0, value=120, step=10)
    yearly_add = yearly_add_man * 10000
    st.markdown("---")
    if st.button("🔄 全データ最新化", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.markdown("---")
    st.caption("左上の × で閉じる")

# ==========================================
# 📊 データ一括処理 ＆ 計算
# ==========================================
df = load_data()
fund_prices = load_fund_prices()  # ★ GASが更新した投信基準価額を読み込み

if not df.empty:
    with st.spinner('市場データを取得中...'):
        tickers_to_fetch = ["JPY=X"]
        for _, row in df.iterrows():
            code = str(row["銘柄コード"])
            market = row["市場"]
            if market == "日本株": tickers_to_fetch.append(f"{code}.T")
            elif market == "米国株": tickers_to_fetch.append(code)

        unique_tickers = tuple(sorted(set(tickers_to_fetch)))
        closes_df = get_cached_market_data(unique_tickers, period="1y")
        info_dict = get_cached_ticker_info(unique_tickers)

        if "JPY=X" in closes_df.columns:
            jpy_usd_series = closes_df["JPY=X"].dropna()
            jpy_usd_rate = jpy_usd_series.iloc[-1] if not jpy_usd_series.empty else 150.0
        else:
            jpy_usd_rate = 150.0

        current_prices_jpy, total_values, profits, net_profits, dividends = [], [], [], [], []
        buy_prices_jpy, update_dates = [], []
        dod_list, sector_list, manual_yield_list, div_month_list = [], [], [], []
        dividends_after_tax = []
        fx_gain_list = []  # 為替損益
        stock_gain_list = []  # 株価損益（為替除く）
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

        for _, row in df.iterrows():
            ticker_code, market_type = str(row["銘柄コード"]), row["市場"]
            shares, buy_price_raw = float(row["保有株数"]), float(row["取得単価"])
            tax_category = str(row.get("口座区分", "特定口座"))
            manual_yield = float(row.get("手動配当利回り(%)", 0.0))
            annual_div_per_share = float(row.get("年間配当金(円/株)", 0.0))
            div_month_str = str(row.get("配当月", ""))
            buy_fx_rate = float(row.get("取得時為替", 0.0))

            fetch_success = False
            dod_pct = None
            price_jpy = value = buy_jpy = dividend = net_profit = 0
            fx_gain = 0.0
            stock_gain = 0.0

            t = f"{ticker_code}.T" if market_type == "日本株" else ticker_code
            sector = info_dict.get(t, {}).get("sector", "")
            # セクター不明の場合、市場種別で分類
            if not sector or sector in ["不明", "ETF/その他", ""]:
                if market_type == "投資信託":
                    # 投資信託は銘柄名からカテゴリを推測
                    nm = str(row["銘柄名"])
                    if "全世界" in nm or "オール" in nm: sector = "投信/全世界株式"
                    elif "S&P" in nm or "米国" in nm or "500" in nm: sector = "投信/米国株式"
                    elif "新興国" in nm: sector = "投信/新興国株式"
                    elif "高配当" in nm: sector = "投信/高配当"
                    elif "債券" in nm or "国債" in nm: sector = "投信/債券"
                    else: sector = "投信/その他"
                elif market_type == "その他資産":
                    nm = str(row["銘柄名"])
                    if "国債" in nm: sector = "国債"
                    elif "金" in nm or "ゴールド" in nm: sector = "コモディティ"
                    else: sector = "その他資産"
                else:
                    sector = "ETF/その他"
            div_rate = info_dict.get(t, {}).get("div_rate", 0.0)
            div_yield = info_dict.get(t, {}).get("div_yield", 0.0)

            if market_type in ["日本株", "米国株"] and t in closes_df.columns:
                series = closes_df[t].dropna()
                if not series.empty:
                    latest_price = series.iloc[-1]
                    fetch_success = True
                    if market_type == "日本株":
                        price_jpy = latest_price; buy_jpy = buy_price_raw
                    else:
                        price_jpy = latest_price * jpy_usd_rate
                        buy_jpy = buy_price_raw * jpy_usd_rate
                        # ★ 為替損益の分離（取得時為替が入力されている場合）
                        if buy_fx_rate > 0:
                            # 株価損益 = (現在USD価格 - 取得USD価格) × 株数 × 現在為替
                            stock_gain = (latest_price - buy_price_raw) * shares * jpy_usd_rate
                            # 為替損益 = 取得USD価格 × 株数 × (現在為替 - 取得時為替)
                            fx_gain = buy_price_raw * shares * (jpy_usd_rate - buy_fx_rate)
                    if len(series) >= 2:
                        prev = series.iloc[-2]
                        dod_pct = ((latest_price / prev) - 1) * 100 if prev != 0 else None
            else:
                # ★ 投資信託: GASが取得した基準価額を使用
                if market_type == "投資信託" and ticker_code in fund_prices:
                    price_jpy = fund_prices[ticker_code]
                    buy_jpy = buy_price_raw
                    fetch_success = True
                else:
                    # その他資産 or 投信価格が未取得の場合は取得単価をフォールバック
                    price_jpy = buy_price_raw
                    buy_jpy = buy_price_raw
                    fetch_success = True

            value = price_jpy * shares
            buy_total = buy_jpy * shares
            profit = value - buy_total

            if annual_div_per_share > 0:
                # ★ 最優先: 年間配当金(円/株) × 株数（米国株は円換算）
                dividend = annual_div_per_share * shares * (jpy_usd_rate if market_type == "米国株" else 1)
            elif manual_yield > 0:
                dividend = value * (manual_yield / 100.0)
            elif div_rate > 0:
                dividend = div_rate * shares * (jpy_usd_rate if market_type == "米国株" else 1)
            else:
                dividend = value * div_yield

            tax_rate = 0.0 if "NISA" in tax_category else 0.20315
            tax_amount = profit * tax_rate if profit > 0 else 0.0
            net_profit = profit - tax_amount
            
            # 配当の税引後計算（NISA=非課税、特定口座=20.315%）
            div_tax_rate = 0.0 if "NISA" in tax_category else 0.20315
            dividend_after_tax = dividend * (1 - div_tax_rate)

            current_prices_jpy.append(price_jpy)
            buy_prices_jpy.append(buy_jpy)
            total_values.append(value)
            profits.append(profit)
            net_profits.append(net_profit)
            dividends.append(dividend)
            dividends_after_tax.append(dividend_after_tax)
            fx_gain_list.append(fx_gain)
            stock_gain_list.append(stock_gain)
            dod_list.append(dod_pct)
            sector_list.append(sector)
            manual_yield_list.append(manual_yield)
            div_month_list.append(div_month_str)
            update_dates.append(now_str if fetch_success else str(row.get("最新更新日", "-")))

        df["最新更新日"] = update_dates
        display_df = df.copy()
        display_df["セクター"] = sector_list
        display_df["取得単価(円)"] = buy_prices_jpy
        display_df["現在値(円)"] = current_prices_jpy
        display_df["前日比"] = dod_list
        display_df["評価額(円)"] = total_values
        display_df["含み損益(円)"] = profits
        display_df["税引後損益(円)"] = net_profits
        display_df["予想配当(円)"] = dividends
        display_df["税引後配当(円)"] = dividends_after_tax
        display_df["株価損益(円)"] = stock_gain_list
        display_df["為替損益(円)"] = fx_gain_list
        display_df["手動配当利回り(%)"] = manual_yield_list
        display_df["配当月"] = div_month_list

        total_asset = sum(total_values)
        total_net_profit = sum(net_profits)
        total_dividend = sum(dividends)
        total_dividend_after_tax = sum(dividends_after_tax)
        total_fx_gain = sum(fx_gain_list)
        total_stock_gain = sum(stock_gain_list)
        avg_dividend_yield = (total_dividend / total_asset * 100) if total_asset > 0 else 0.0
        stock_count = len(df)
else:
    total_asset = total_net_profit = total_dividend = total_dividend_after_tax = avg_dividend_yield = stock_count = 0
    total_fx_gain = total_stock_gain = 0
    jpy_usd_rate = 150.0
    display_df = pd.DataFrame()

# ==========================================
# 🏠 ヘッダー
# ==========================================
h1, h2 = st.columns([4, 1.5])
with h1:
    st.markdown(f"""
        <div class='logo-text'>P<span>ORTFOLIO</span></div>
        <div class='logo-sub'>{datetime.now().strftime('%Y/%m/%d %H:%M')} · {stock_count}銘柄 · $1 = ¥{jpy_usd_rate:.1f}</div>
    """, unsafe_allow_html=True)
with h2:
    if st.button("💾 本日の資産を記録", use_container_width=True) and total_asset > 0:
        save_history(datetime.now().strftime("%Y/%m/%d"), total_asset)
        st.toast("✓ 記録しました")
        st.rerun()

# ==========================================
# 💳 ステータスカード（常時表示）
# ==========================================
# 前回記録との比較
prev_asset = 0
prev_diff = 0
prev_diff_pct = 0
prev_date_str = ""
try:
    _hdf = load_history()
    if not _hdf.empty and len(_hdf) >= 1:
        _hdf["総資産額(円)"] = pd.to_numeric(_hdf["総資産額(円)"], errors='coerce')
        prev_asset = _hdf["総資産額(円)"].iloc[-1]
        prev_date_str = str(_hdf["日付"].iloc[-1])
        if prev_asset > 0 and total_asset > 0:
            prev_diff = total_asset - prev_asset
            prev_diff_pct = (prev_diff / prev_asset) * 100
except:
    pass

c1, c2, c3, c4 = st.columns(4)
with c1:
    # 評価額 + 前回比
    prev_html = ""
    if prev_asset > 0:
        dc = "#00E676" if prev_diff >= 0 else "#FF5252"
        ds = "+" if prev_diff >= 0 else ""
        prev_html = f"<p class='sv' style='color:{dc}'>{ds}{prev_diff:,.0f}円 ({ds}{prev_diff_pct:.2f}%) <span style='color:#7A8A9A'>vs {prev_date_str}</span></p>"
    else:
        prev_html = f"<p class='sv'>{stock_count}銘柄</p>"
    st.markdown(f"<div class='status-card card-total c1'><h4>評価額合計</h4><p class='mv'>{total_asset:,.0f}<span>円</span></p>{prev_html}</div>", unsafe_allow_html=True)
with c2:
    pc = "#00E676" if total_net_profit >= 0 else "#FF5252"
    ps = "+" if total_net_profit >= 0 else ""
    pp = (total_net_profit / (total_asset - total_net_profit) * 100) if (total_asset - total_net_profit) > 0 else 0
    st.markdown(f"<div class='status-card card-profit c2'><h4>税引後 含み損益</h4><p class='mv' style='color:{pc}'>{ps}{total_net_profit:,.0f}<span>円</span></p><p class='sv'>{ps}{pp:.2f}%</p></div>", unsafe_allow_html=True)
with c3:
    monthly_div_at = total_dividend_after_tax / 12 if total_dividend_after_tax > 0 else 0
    st.markdown(f"<div class='status-card card-dividend c3'><h4>年間予想配当</h4><p class='mv'>{total_dividend_after_tax:,.0f}<span>円</span></p><p class='sv'>税引後 · 利回り {avg_dividend_yield:.2f}% · 月平均 {monthly_div_at:,.0f}円</p></div>", unsafe_allow_html=True)
with c4:
    progress = min(total_asset / goal_amount * 100, 100.0) if goal_amount > 0 else 100.0
    remaining = max(goal_amount - total_asset, 0)
    st.markdown(f"<div class='status-card card-goal c4'><h4>{goal_oku}億円ゴール</h4><p class='mv'>{progress:.1f}<span>%</span></p><p class='sv'>残り {remaining/1e8:,.2f}億円</p></div>", unsafe_allow_html=True)

# ゴール進捗バー
pv = min(total_asset / goal_amount * 100, 100.0) if goal_amount > 0 else 0
st.markdown(f"""
<div class='goal-bar-wrap'>
  <div class='goal-bar-bg'><div class='goal-bar-fill' style='width:{pv}%'></div></div>
  <div class='goal-bar-labels'><span>¥0</span><span style='color:#00D2FF'>{pv:.1f}% 達成</span><span>{goal_oku}億円</span></div>
</div>""", unsafe_allow_html=True)

# ★ 為替損益サマリー（米国株の取得時為替が入力されている場合のみ）
if total_fx_gain != 0 or total_stock_gain != 0:
    fx_c1, fx_c2 = st.columns(2)
    with fx_c1:
        sg_color = "#00E676" if total_stock_gain >= 0 else "#FF5252"
        sg_sign = "+" if total_stock_gain >= 0 else ""
        st.markdown(f"""<div class='status-card' style='padding:0.6rem;border-left:3px solid #00D2FF'>
            <h4>米国株 株価損益</h4>
            <p class='mv' style='font-size:1rem;color:{sg_color}'>{sg_sign}{total_stock_gain:,.0f}<span>円</span></p>
            <p class='sv'>株価の値動きによる損益</p>
        </div>""", unsafe_allow_html=True)
    with fx_c2:
        fg_color = "#00E676" if total_fx_gain >= 0 else "#FF5252"
        fg_sign = "+" if total_fx_gain >= 0 else ""
        st.markdown(f"""<div class='status-card' style='padding:0.6rem;border-left:3px solid #FFD54F'>
            <h4>米国株 為替損益</h4>
            <p class='mv' style='font-size:1rem;color:{fg_color}'>{fg_sign}{total_fx_gain:,.0f}<span>円</span></p>
            <p class='sv'>為替変動（$1=¥{jpy_usd_rate:.1f}）による損益</p>
        </div>""", unsafe_allow_html=True)

# ★ 大幅変動アラート
if not display_df.empty and '前日比' in display_df.columns:
    big_movers = display_df[display_df['前日比'].apply(lambda x: abs(x) >= 3.0 if pd.notna(x) else False)]
    for _, mv in big_movers.iterrows():
        d = mv['前日比']
        cls = "alert-up" if d > 0 else "alert-down"
        arrow = "▲" if d > 0 else "▼"
        st.markdown(f"<div class='alert-bar {cls}'>{arrow} <b>{mv['銘柄名']}</b>（{mv['銘柄コード']}）が前日比 {d:+.2f}% の大幅変動</div>", unsafe_allow_html=True)

# ==========================================
# 📑 メインタブ
# ==========================================
tab_pf, tab_an, tab_div, tab_sim, tab_mkt, tab_ai = st.tabs(["📊 ポートフォリオ", "🔍 分析", "💰 配当", "🚀 シミュレーション", "🌍 世界指標", "🤖 AI総評"])

# ── TAB 1: ポートフォリオ ──
with tab_pf:
    st.markdown("#### ➕ 銘柄を追加")
    r1a, r1b, r1c = st.columns([1, 1, 2])
    with r1a: market = st.selectbox("市場", ["日本株", "米国株", "投資信託", "その他資産"], key="form_market")
    with r1b: code = st.text_input("証券コード", placeholder="例: 7203", key="form_code")
    with r1c:
        # ★ 証券コードを入れたら自動で銘柄名を取得して表示
        if code and market in ["日本株", "米国株"]:
            with st.spinner("銘柄名を取得中..."):
                auto_name = get_ticker_name(code, market)
            if auto_name and auto_name not in ["取得失敗", "入力で損益計算", ""]:
                st.markdown(f"<p style='color:#00D2FF;font-size:0.85rem;margin:0 0 4px'>🔍 {auto_name}</p>", unsafe_allow_html=True)
                manual_name = st.text_input("銘柄名（変更可）", value=auto_name, key="form_name")
            else:
                st.markdown(f"<p style='color:#FF5252;font-size:0.85rem;margin:0 0 4px'>⚠ 銘柄名を取得できませんでした</p>", unsafe_allow_html=True)
                manual_name = st.text_input("銘柄名（手動入力）", value="", key="form_name")
        else:
            auto_name = ""
            manual_name = st.text_input("銘柄名", value="", key="form_name", placeholder="手動入力してください")

    r2a, r2b, r2c, r2d, r2e = st.columns([1, 1, 1, 1, 1])
    with r2a: shares = st.number_input("保有数", min_value=0.0001, value=100.0, key="form_shares")
    with r2b: avg_price = st.number_input("取得単価", min_value=0.0, value=0.0, key="form_price")
    with r2c: annual_div_input = st.number_input("年間配当金(円/株)", min_value=0.0, value=0.0, step=1.0, help="1株あたりの年間配当金額。米国株はドル建て", key="form_div")
    with r2d: broker_type = st.selectbox("口座", ["SBI証券", "楽天証券", "持ち株会(野村證券)"], key="form_broker")
    with r2e: tax_type = st.selectbox("口座区分", ["特定口座", "NISA(成長投資枠)", "NISA(積立投資枠)"], key="form_tax")

    r3a, r3b, r3c = st.columns([1.5, 1.5, 2])
    with r3a: div_months = st.text_input("配当月 (例: 3,9)", placeholder="3,6,9,12", help="カンマ区切りで入力", key="form_divmonth")
    with r3b: buy_fx = st.number_input("取得時為替 (米国株)", min_value=0.0, value=0.0, step=0.1, help="米国株のみ。購入時の$/¥レート", key="form_buyfx")
    with r3c: st.write("")

    if st.button("＋ 追加", key="add_btn") and code:
        final_name = manual_name if manual_name else (auto_name if auto_name else code)
        new_data = pd.DataFrame({
            "銘柄コード": [code], "銘柄名": [final_name], "市場": [market],
            "保有株数": [shares], "取得単価": [avg_price], "口座": [broker_type], "口座区分": [tax_type],
            "手動配当利回り(%)": [0.0], "配当月": [div_months], "年間配当金(円/株)": [annual_div_input], "取得時為替": [buy_fx],
            "最新更新日": [datetime.now().strftime("%Y/%m/%d %H:%M")]
        })
        df = pd.concat([df, new_data], ignore_index=True)
        save_data(df)
        st.cache_data.clear()
        st.success(f"✓ {final_name} を追加しました")
        st.rerun()

    # ★ 口座別サマリー
    if not df.empty and not display_df.empty:
        st.markdown("---")
        st.markdown("#### 🏦 口座別サマリー")
        
        # 口座列がない場合のフォールバック
        if "口座" not in display_df.columns:
            display_df["口座"] = "SBI証券"
        if "口座区分" not in display_df.columns:
            display_df["口座区分"] = "特定口座"
        
        acct_map = {
            "SBI証券": "acct-sbi", "楽天証券": "acct-rakuten",
            "持ち株会(野村證券)": "acct-nomura",
        }
        acct_groups = display_df.groupby("口座").agg({"評価額(円)": "sum", "税引後損益(円)": "sum", "予想配当(円)": "sum", "銘柄コード": "count"}).reset_index()
        n_accts = len(acct_groups)
        acct_cols = st.columns(min(n_accts, 3)) if n_accts > 0 else []
        for i, (_, ag) in enumerate(acct_groups.iterrows()):
            with acct_cols[i % len(acct_cols)]:
                badge_cls = acct_map.get(ag["口座"], "acct-other")
                pnl_color = "#00E676" if ag["税引後損益(円)"] >= 0 else "#FF5252"
                pnl_sign = "+" if ag["税引後損益(円)"] >= 0 else ""
                st.markdown(f"""
                <div class='status-card' style='padding:0.8rem'>
                    <h4><span class='acct-badge {badge_cls}'>{ag['口座']}</span> {int(ag['銘柄コード'])}銘柄</h4>
                    <p class='mv' style='font-size:1.2rem'>{ag['評価額(円)']:,.0f}<span>円</span></p>
                    <p class='sv' style='color:{pnl_color}'>{pnl_sign}{ag['税引後損益(円)']:,.0f}円 · 配当 {ag['予想配当(円)']:,.0f}円</p>
                </div>""", unsafe_allow_html=True)

        # NISA / 特定口座の内訳
        nisa_df = display_df[display_df["口座区分"].str.contains("NISA", na=False)]
        tokutei_df = display_df[~display_df["口座区分"].str.contains("NISA", na=False)]
        nc1, nc2 = st.columns(2)
        with nc1:
            nisa_val = nisa_df["評価額(円)"].sum() if not nisa_df.empty else 0
            nisa_growth = nisa_df[nisa_df["口座区分"].str.contains("成長", na=False)]["評価額(円)"].sum()
            nisa_tsumitate = nisa_df[nisa_df["口座区分"].str.contains("積立", na=False)]["評価額(円)"].sum()
            st.markdown(f"""<div class='status-card' style='padding:0.7rem;border-left:3px solid #69F0AE'>
                <h4>NISA合計（非課税）</h4>
                <p class='mv' style='font-size:1.1rem'>{nisa_val:,.0f}<span>円</span></p>
                <p class='sv'>成長枠 {nisa_growth:,.0f}円 · 積立枠 {nisa_tsumitate:,.0f}円 · {len(nisa_df)}銘柄</p>
            </div>""", unsafe_allow_html=True)
        with nc2:
            tok_val = tokutei_df["評価額(円)"].sum() if not tokutei_df.empty else 0
            st.markdown(f"""<div class='status-card' style='padding:0.7rem;border-left:3px solid #FF8F00'>
                <h4>特定口座合計（課税）</h4>
                <p class='mv' style='font-size:1.1rem'>{tok_val:,.0f}<span>円</span></p>
                <p class='sv'>{len(tokutei_df)}銘柄</p>
            </div>""", unsafe_allow_html=True)

    # 保有一覧
    if not df.empty and not display_df.empty:
        st.markdown("---")
        st.markdown("#### 📋 保有銘柄一覧")
        def cpf(v): return f"color: {'#00E676' if v >= 0 else '#FF5252'}"
        def cpc(v): return "" if pd.isna(v) else f"color: {'#00E676' if v > 0 else '#FF5252' if v < 0 else '#E0E0E0'}"
        def fp(v): return "-" if pd.isna(v) else (f"+{v:.1f}%" if v > 0 else f"{v:.1f}%")
        sc = ["銘柄コード","銘柄名","市場","口座","口座区分","保有株数","取得単価(円)","現在値(円)","前日比","評価額(円)","税引後損益(円)","予想配当(円)"]
        ac = [c for c in sc if c in display_df.columns]
        fd = {"保有株数": round_up_3, "取得単価(円)": round_up_3, "現在値(円)": round_up_3, "前日比": fp, "評価額(円)": "{:,.0f}", "税引後損益(円)": "{:,.0f}", "予想配当(円)": "{:,.0f}"}
        sdf = display_df[ac].style
        if '税引後損益(円)' in ac: sdf = sdf.applymap(cpf, subset=['税引後損益(円)'])
        if '前日比' in ac: sdf = sdf.applymap(cpc, subset=['前日比'])
        sdf = sdf.format({k: v for k, v in fd.items() if k in ac})
        st.dataframe(sdf, use_container_width=True, hide_index=True)
        
        # ★ CSV出力ボタン
        st.markdown("---")
        st.markdown("#### 📥 データエクスポート")
        csv_c1, csv_c2, csv_c3 = st.columns(3)
        with csv_c1:
            # 保有銘柄一覧CSV
            csv_cols = ["銘柄コード","銘柄名","市場","口座","口座区分","保有株数","取得単価(円)","現在値(円)","評価額(円)","含み損益(円)","税引後損益(円)","予想配当(円)","税引後配当(円)","セクター"]
            csv_ac = [c for c in csv_cols if c in display_df.columns]
            csv_data = display_df[csv_ac].to_csv(index=False).encode('utf-8-sig')
            st.download_button(
                "📋 保有銘柄一覧 CSV",
                data=csv_data,
                file_name=f"portfolio_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with csv_c2:
            # 配当明細CSV
            div_rows = []
            for _, r in display_df.iterrows():
                if r.get("予想配当(円)", 0) > 0:
                    div_rows.append({
                        "銘柄コード": r["銘柄コード"],
                        "銘柄名": r["銘柄名"],
                        "口座": r.get("口座", ""),
                        "口座区分": r.get("口座区分", ""),
                        "予想配当(税引前)": round(r["予想配当(円)"]),
                        "税引後配当": round(r.get("税引後配当(円)", 0)),
                        "配当月": r.get("配当月", ""),
                    })
            if div_rows:
                div_csv = pd.DataFrame(div_rows).to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    "💰 配当明細 CSV",
                    data=div_csv,
                    file_name=f"dividends_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.button("💰 配当明細 CSV", disabled=True, use_container_width=True, help="配当データなし")
        with csv_c3:
            # 資産推移CSV
            hist_csv_df = load_history()
            if not hist_csv_df.empty:
                hist_csv = hist_csv_df.to_csv(index=False).encode('utf-8-sig')
                st.download_button(
                    "📈 資産推移 CSV",
                    data=hist_csv,
                    file_name=f"asset_history_{datetime.now().strftime('%Y%m%d')}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            else:
                st.button("📈 資産推移 CSV", disabled=True, use_container_width=True, help="履歴データなし")

    # 修正・削除
    if not df.empty:
        with st.expander("✏️ 銘柄の修正・削除", expanded=False):
            edf = df.copy(); edf["削除"] = False
            broker_options = ["SBI証券", "楽天証券", "持ち株会(野村證券)"]
            tax_options = ["特定口座", "NISA(成長投資枠)", "NISA(積立投資枠)"]
            market_options = ["日本株", "米国株", "投資信託", "その他資産"]
            edited = st.data_editor(
                edf,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True,
                column_config={
                    "口座": st.column_config.SelectboxColumn(
                        "口座",
                        options=broker_options,
                        required=True,
                    ),
                    "口座区分": st.column_config.SelectboxColumn(
                        "口座区分",
                        options=tax_options,
                        required=True,
                    ),
                    "市場": st.column_config.SelectboxColumn(
                        "市場",
                        options=market_options,
                        required=True,
                    ),
                    "保有株数": st.column_config.NumberColumn("保有株数", min_value=0, format="%.4f"),
                    "取得単価": st.column_config.NumberColumn("取得単価", min_value=0, format="%.2f"),
                    "手動配当利回り(%)": st.column_config.NumberColumn("手動利回り(%)", min_value=0, format="%.2f"),
                    "年間配当金(円/株)": st.column_config.NumberColumn("年間配当(円/株)", min_value=0, format="%.2f"),
                    "取得時為替": st.column_config.NumberColumn("取得時為替($/¥)", min_value=0, format="%.1f", help="米国株のみ"),
                    "削除": st.column_config.CheckboxColumn("削除", default=False),
                },
            )
            if st.button("💾 変更を保存", key="sv_edit"):
                save_data(edited[edited["削除"] == False].drop(columns=["削除"]))
                st.cache_data.clear(); st.success("更新しました！"); st.rerun()

    # 資産推移
    if total_asset > 0:
        st.markdown("---")
        st.markdown("#### 📈 資産推移")
        hdf = load_history()
        if not hdf.empty and len(hdf) > 0:
            fh = px.line(hdf, x="日付", y="総資産額(円)", markers=True)
            fh.update_traces(line_color="#00E676", marker=dict(size=8, color="#FFFFFF"))
            fh.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(t=10, b=10, l=10, r=10), height=300, xaxis=dict(showgrid=True, gridcolor='#1E232F'), yaxis=dict(showgrid=True, gridcolor='#1E232F', tickformat=","))
            st.plotly_chart(fh, use_container_width=True)
        else:
            st.info("ヘッダーの「💾 本日の資産を記録」ボタンで記録を開始してください。")

# ── TAB 2: 分析 ──
with tab_an:
    if not df.empty and total_asset > 0 and not display_df.empty:
        display_df["円グラフ表示名"] = display_df["銘柄コード"].astype(str) + " " + display_df["銘柄名"].astype(str)
        st.markdown("#### 🍩 銘柄別割合")
        ac1, ac2 = st.columns([1.2, 1])
        with ac1:
            fp1 = px.pie(display_df, values="評価額(円)", names="円グラフ表示名", hole=0.4)
            fp1.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fp1, use_container_width=True)
        with ac2:
            tld = display_df[display_df["評価額(円)"] > 0].groupby("円グラフ表示名", as_index=False)["評価額(円)"].sum().sort_values("評価額(円)", ascending=False)
            tld["割合"] = (tld["評価額(円)"] / total_asset * 100).apply(lambda x: f"{x:.1f}%")
            tld["評価額(円)"] = tld["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            tld.rename(columns={"円グラフ表示名": "銘柄"}, inplace=True)
            st.dataframe(tld, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 🏢 セクター別割合")
        sc1, sc2 = st.columns([1.2, 1])
        with sc1:
            fp2 = px.pie(display_df, values="評価額(円)", names="セクター", hole=0.4)
            fp2.update_traces(textposition='inside', textinfo='percent+label')
            fp2.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fp2, use_container_width=True)
        with sc2:
            sld = display_df[display_df["評価額(円)"] > 0].groupby("セクター", as_index=False)["評価額(円)"].sum().sort_values("評価額(円)", ascending=False)
            sld["割合"] = (sld["評価額(円)"] / total_asset * 100).apply(lambda x: f"{x:.1f}%")
            sld["評価額(円)"] = sld["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            st.dataframe(sld, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.markdown("#### 🗺️ ヒートマップ")
        st.caption("四角の大きさ＝評価額、色＝前日比。手動入力資産は除外。")
        tdf = display_df[(display_df["市場"].isin(["日本株", "米国株"])) & (display_df["評価額(円)"] > 0)].copy()
        if not tdf.empty:
            tdf["前日比(数値)"] = tdf["前日比"].apply(lambda x: x if pd.notna(x) else 0.0)
            tdf["Treemap Label"] = tdf["銘柄名"].astype(str) + "<br>" + tdf["前日比(数値)"].apply(lambda x: f"+{x:.2f}%" if x > 0 else f"{x:.2f}%")
            ft = px.treemap(tdf, path=["市場", "セクター", "Treemap Label"], values="評価額(円)", color="前日比(数値)", color_continuous_scale="RdYlGn", color_continuous_midpoint=0, hover_data=["含み損益(円)", "予想配当(円)"])
            ft.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=500, paper_bgcolor='#0A0E13')
            ft.data[0].textfont.color = "black"
            st.plotly_chart(ft, use_container_width=True)
        else:
            st.info("ヒートマップ用データがありません。")

        # ==========================================
        # ⚖️ リバランス提案
        # ==========================================
        st.markdown("---")
        st.markdown("#### ⚖️ リバランス提案")
        st.caption("目標配分を設定すると、現在のポートフォリオとの乖離と調整案を表示します。")
        
        # 現在のセクター配分を取得
        sector_current = display_df[display_df["評価額(円)"] > 0].groupby("セクター", as_index=False)["評価額(円)"].sum()
        sector_current["現在(%)"] = (sector_current["評価額(円)"] / total_asset * 100)
        all_sectors = sorted(sector_current["セクター"].tolist())
        
        if all_sectors:
            # 目標配分の入力UI
            with st.expander("🎯 目標配分を設定（%）", expanded=False):
                st.caption("合計が100%になるように設定してください。0%のセクターは「売却候補」として表示されます。")
                target_pcts = {}
                # セクター数に応じて列を分ける
                n_cols = min(len(all_sectors), 4)
                target_cols = st.columns(n_cols)
                for i, sec in enumerate(all_sectors):
                    current_pct = sector_current[sector_current["セクター"] == sec]["現在(%)"].values
                    current_val = current_pct[0] if len(current_pct) > 0 else 0
                    with target_cols[i % n_cols]:
                        target_pcts[sec] = st.number_input(
                            f"{sec}", 
                            min_value=0.0, max_value=100.0, 
                            value=round(current_val, 1),  # デフォルトは現在配分
                            step=1.0, key=f"target_{sec}"
                        )
                
                total_target = sum(target_pcts.values())
                if abs(total_target - 100.0) > 0.5:
                    st.warning(f"⚠ 目標合計: {total_target:.1f}%（100%と{total_target - 100:.1f}%の差があります）")
                else:
                    st.success(f"✓ 目標合計: {total_target:.1f}%")
            
            # 乖離の計算と表示
            rebal_data = []
            for sec in all_sectors:
                current_pct = sector_current[sector_current["セクター"] == sec]["現在(%)"].values
                c_pct = current_pct[0] if len(current_pct) > 0 else 0
                t_pct = target_pcts.get(sec, 0)
                diff_pct = c_pct - t_pct
                current_amt = sector_current[sector_current["セクター"] == sec]["評価額(円)"].values
                c_amt = current_amt[0] if len(current_amt) > 0 else 0
                t_amt = total_asset * (t_pct / 100)
                diff_amt = c_amt - t_amt
                rebal_data.append({
                    "セクター": sec,
                    "現在(%)": c_pct,
                    "目標(%)": t_pct,
                    "乖離(%)": diff_pct,
                    "現在(円)": c_amt,
                    "目標(円)": t_amt,
                    "調整額(円)": diff_amt,
                })
            
            rebal_df = pd.DataFrame(rebal_data).sort_values("乖離(%)", key=abs, ascending=False)
            
            # 乖離バーチャート
            fig_rebal = go.Figure()
            for _, r in rebal_df.iterrows():
                color = "#FF5252" if r["乖離(%)"] > 1 else "#00E676" if r["乖離(%)"] < -1 else "#9E9E9E"
                fig_rebal.add_trace(go.Bar(
                    x=[r["乖離(%)"]], y=[r["セクター"]], orientation='h',
                    marker_color=color, text=f"{r['乖離(%)']:+.1f}%", textposition='auto',
                    showlegend=False
                ))
            fig_rebal.update_layout(
                plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0',
                margin=dict(t=10, b=10, l=10, r=10), height=max(len(all_sectors) * 40, 200),
                xaxis=dict(title="乖離（%）", showgrid=True, gridcolor='#1E232F', zeroline=True, zerolinecolor='#4A5060'),
                yaxis=dict(showgrid=False),
            )
            st.plotly_chart(fig_rebal, use_container_width=True)
            st.caption("🔴 赤 = 比重オーバー（売却候補） / 🟢 緑 = 比重不足（買い増し候補） / 灰 = 適正範囲(±1%)")
            
            # 具体的な調整提案テーブル
            has_action = rebal_df[abs(rebal_df["乖離(%)"]) > 1.0]
            if not has_action.empty:
                st.markdown("##### 📋 調整アクション")
                for _, r in has_action.iterrows():
                    adj = r["調整額(円)"]
                    if adj > 0:
                        # 比重オーバー → 売却
                        st.markdown(f"""
                        <div class='alert-bar alert-down'>
                            📉 <b>{r['セクター']}</b>　現在 {r['現在(%)']:.1f}% → 目標 {r['目標(%)']:.1f}%　
                            <span style='color:#FF5252;font-weight:bold'>約 ¥{abs(adj):,.0f} 売却</span>
                        </div>""", unsafe_allow_html=True)
                    else:
                        # 比重不足 → 買い増し
                        st.markdown(f"""
                        <div class='alert-bar alert-up'>
                            📈 <b>{r['セクター']}</b>　現在 {r['現在(%)']:.1f}% → 目標 {r['目標(%)']:.1f}%　
                            <span style='color:#69F0AE;font-weight:bold'>約 ¥{abs(adj):,.0f} 買い増し</span>
                        </div>""", unsafe_allow_html=True)
            else:
                st.success("✓ 全セクターが目標配分の±1%以内に収まっています。リバランス不要です。")
    else:
        st.info("銘柄を追加すると分析が表示されます。")

# ── TAB 3: 配当カレンダー ──
with tab_div:
    if not df.empty and total_asset > 0 and not display_df.empty:
        st.markdown("#### 💰 月別配当カレンダー")
        st.caption("各月をクリックすると銘柄ごとの配当額が確認できます。")

        # 月別配当集計（銘柄ごとの金額も保持）
        monthly_dividends = {m: 0 for m in range(1, 13)}
        monthly_dividends_at = {m: 0 for m in range(1, 13)}  # 税引後
        monthly_detail = {m: [] for m in range(1, 13)}

        for _, row in display_df.iterrows():
            div_amount = row.get("予想配当(円)", 0)
            div_amount_at = row.get("税引後配当(円)", 0)
            div_month_str = str(row.get("配当月", ""))
            if div_amount > 0 and div_month_str:
                try:
                    months_list = [int(m.strip()) for m in div_month_str.split(",") if m.strip().isdigit()]
                    per_payment = div_amount / len(months_list) if months_list else 0
                    per_payment_at = div_amount_at / len(months_list) if months_list else 0
                    tax_label = "非課税" if "NISA" in str(row.get("口座区分", "")) else "課税"
                    for m in months_list:
                        if 1 <= m <= 12:
                            monthly_dividends[m] += per_payment
                            monthly_dividends_at[m] += per_payment_at
                            monthly_detail[m].append({
                                "銘柄": f"{row['銘柄コード']} {row['銘柄名']}",
                                "税引前": per_payment,
                                "税引後": per_payment_at,
                                "税区分": tax_label,
                            })
                except:
                    pass

        # カレンダー表示（4列×3行）
        total_calendar_div = sum(monthly_dividends.values())
        total_calendar_div_at = sum(monthly_dividends_at.values())
        month_names = ["1月","2月","3月","4月","5月","6月","7月","8月","9月","10月","11月","12月"]
        
        for row_start in range(0, 12, 4):
            cols = st.columns(4)
            for i in range(4):
                m = row_start + i + 1
                with cols[i]:
                    amt = monthly_dividends[m]
                    amt_at = monthly_dividends_at[m]
                    details = monthly_detail[m]
                    
                    if amt > 0:
                        with st.popover(f"📅 {month_names[m-1]}", use_container_width=True):
                            st.markdown(f"**{month_names[m-1]}の配当明細**")
                            st.markdown(f"税引前合計: **¥{amt:,.0f}** → 手取り: **¥{amt_at:,.0f}**")
                            st.markdown("---")
                            for d in sorted(details, key=lambda x: x["税引前"], reverse=True):
                                tax_badge = "🟢" if d["税区分"] == "非課税" else "🟡"
                                st.markdown(f"""
                                <div style='display:flex;justify-content:space-between;align-items:center;padding:5px 0;border-bottom:1px solid #1E232F;font-size:0.85rem'>
                                    <span style='color:#B0B8C0'>{tax_badge} {d['銘柄']}</span>
                                    <span style='text-align:right'>
                                        <span style='color:#FFD54F;font-weight:bold'>¥{d['税引後']:,.0f}</span>
                                        <span style='color:#7A8A9A;font-size:0.7rem;margin-left:4px'>({d['税区分']})</span>
                                    </span>
                                </div>""", unsafe_allow_html=True)
                        
                        st.markdown(f"""
                        <div style='text-align:center;margin-top:-8px;margin-bottom:8px'>
                            <span style='color:#FFD54F;font-weight:bold;font-size:0.9rem'>¥{amt_at:,.0f}</span>
                            <span style='color:#7A8A9A;font-size:0.6rem;display:block'>手取り · {len(details)}銘柄</span>
                        </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
                        <div class='div-month div-month-empty'>
                            <span class='month-label'>{month_names[m-1]}</span>
                            <span class='month-amount'>—</span>
                        </div>""", unsafe_allow_html=True)

        st.markdown("---")
        
        # 年間サマリー（税引前 / 税引後）
        if total_calendar_div > 0:
            sum_c1, sum_c2, sum_c3, sum_c4 = st.columns(4)
            with sum_c1:
                st.markdown(f"""<div class='status-card' style='padding:0.7rem;border-left:3px solid #FFD54F'>
                    <h4>年間配当（税引前）</h4>
                    <p class='mv' style='font-size:1.1rem'>¥{total_calendar_div:,.0f}</p>
                </div>""", unsafe_allow_html=True)
            with sum_c2:
                st.markdown(f"""<div class='status-card' style='padding:0.7rem;border-left:3px solid #69F0AE'>
                    <h4>年間手取り（税引後）</h4>
                    <p class='mv' style='font-size:1.1rem'>¥{total_calendar_div_at:,.0f}</p>
                </div>""", unsafe_allow_html=True)
            with sum_c3:
                monthly_avg_at = total_calendar_div_at / 12
                st.markdown(f"""<div class='status-card' style='padding:0.7rem;border-left:3px solid #00D2FF'>
                    <h4>月平均手取り</h4>
                    <p class='mv' style='font-size:1.1rem'>¥{monthly_avg_at:,.0f}</p>
                </div>""", unsafe_allow_html=True)
            with sum_c4:
                active_months = sum(1 for v in monthly_dividends.values() if v > 0)
                st.markdown(f"""<div class='status-card' style='padding:0.7rem;border-left:3px solid #BD93F9'>
                    <h4>配当発生月</h4>
                    <p class='mv' style='font-size:1.1rem'>{active_months}<span>/12ヶ月</span></p>
                </div>""", unsafe_allow_html=True)
            
            st.caption("※ カレンダーの金額は配当月が入力されている銘柄のみ。未入力の銘柄は含まれません。")
        else:
            st.info("配当月が入力されている銘柄がありません。「✏️ 銘柄の修正・削除」から配当月（例: 3,9）を入力してください。")

        # 配当ランキング
        st.markdown("---")
        st.markdown("#### 🏆 配当金ランキング")
        div_ranking = display_df[display_df["予想配当(円)"] > 0][["銘柄コード", "銘柄名", "予想配当(円)", "手動配当利回り(%)"]].sort_values("予想配当(円)", ascending=False).head(10)
        if not div_ranking.empty:
            div_ranking["予想配当(円)"] = div_ranking["予想配当(円)"].apply(lambda x: f"¥{int(x):,}")
            div_ranking["手動配当利回り(%)"] = div_ranking["手動配当利回り(%)"].apply(lambda x: f"{x:.2f}%" if x > 0 else "自動")
            st.dataframe(div_ranking, use_container_width=True, hide_index=True)
        else:
            st.info("配当データがありません。")
    else:
        st.info("銘柄を追加すると配当カレンダーが表示されます。")

# ── TAB 4: シミュレーション ──
with tab_sim:
    if not df.empty and total_asset > 0:
        st.markdown(f"#### 🎯 {goal_oku}億円ゴール 年間必要積立額 (年利{interest_rate_pct}%)")
        st.caption("サイドバー（左上の > ）で目標・年利・積立額を変更できます。")
        yl, pm = [10, 15, 20, 25, 30], []
        for y in yl:
            sf = goal_amount - (total_asset * ((1 + interest_rate) ** y))
            pm.append(sf / (((1 + interest_rate) ** y - 1) / interest_rate) if sf > 0 else 0)
        sdb = pd.DataFrame({"達成年数": [f"{y}年後" for y in yl], "年間積立額": pm})
        sdb["表示用金額"] = sdb["年間積立額"].apply(lambda x: f"{int(x):,}円" if x > 0 else "達成確実！")
        fb = px.bar(sdb, x="年間積立額", y="達成年数", orientation='h', text="表示用金額")
        fb.update_traces(textposition='auto', marker_color='#00D2FF')
        fb.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(t=10, b=10), xaxis=dict(tickformat=",", ticksuffix="円"))
        st.plotly_chart(fb, use_container_width=True)
        st.markdown("---")
        st.markdown("#### 🚀 未来の資産推移")
        plf = st.select_slider("期間", options=["1年後", "3年後", "5年後", "10年後", "20年後", "30年後"], value="10年後")
        ym = {"1年後": 1, "3年後": 3, "5年後": 5, "10年後": 10, "20年後": 20, "30年後": 30}
        sdl = get_future_simulation(total_asset, interest_rate, ym[plf], yearly_add)
        
        # 年単位に集約（棒グラフ用）
        sdl["年"] = sdl["日時"].dt.year
        yearly_data = sdl.groupby("年").last().reset_index()
        # 現在年からの経過年数ラベル
        base_year = yearly_data["年"].iloc[0]
        yearly_data["経過年数"] = yearly_data["年"].apply(lambda y: f"{y - base_year}年目" if y > base_year else "現在")
        
        ff = go.Figure()
        ff.add_trace(go.Bar(
            x=yearly_data["経過年数"], y=yearly_data["積立元本(円)"],
            name="積立元本",
            marker_color="#4A90D9",
            hovertemplate="積立元本: %{y:,.0f}円<extra></extra>"
        ))
        ff.add_trace(go.Bar(
            x=yearly_data["経過年数"], y=yearly_data["運用益(円)"],
            name="運用益",
            marker_color="#00D2FF",
            hovertemplate="運用益: %{y:,.0f}円<extra></extra>"
        ))
        if goal_amount > 0:
            ff.add_trace(go.Scatter(
                x=[yearly_data["経過年数"].iloc[0], yearly_data["経過年数"].iloc[-1]],
                y=[goal_amount, goal_amount],
                mode='lines', line=dict(color="#FF1744", width=2, dash='dash'),
                name=f"目標 ({goal_oku}億円)",
                hovertemplate="目標: %{y:,.0f}円<extra></extra>"
            ))
        
        # 最終年の金額を表示
        final_val = yearly_data["予測評価額(円)"].iloc[-1]
        final_principal = yearly_data["積立元本(円)"].iloc[-1]
        final_gain = yearly_data["運用益(円)"].iloc[-1]
        
        fc1, fc2, fc3 = st.columns(3)
        with fc1:
            st.markdown(f"<div class='status-card'><h4>予測評価額</h4><p class='mv' style='color:#00D2FF'>{final_val:,.0f}<span>円</span></p></div>", unsafe_allow_html=True)
        with fc2:
            st.markdown(f"<div class='status-card'><h4>積立元本</h4><p class='mv'>{final_principal:,.0f}<span>円</span></p></div>", unsafe_allow_html=True)
        with fc3:
            st.markdown(f"<div class='status-card'><h4>運用益</h4><p class='mv' style='color:#00E676'>{final_gain:,.0f}<span>円</span></p></div>", unsafe_allow_html=True)
        
        ff.update_layout(
            barmode='stack',
            plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0',
            margin=dict(l=0, r=0, t=20, b=10), height=400,
            xaxis=dict(showgrid=False, tickfont=dict(size=10)),
            yaxis=dict(showgrid=True, gridcolor='#1E232F', tickformat=","),
            legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01, bgcolor="rgba(0,0,0,0)")
        )
        st.plotly_chart(ff, use_container_width=True)
    else:
        st.info("銘柄を追加するとシミュレーションが表示されます。")

# ── TAB 5: 世界指標 ──
with tab_mkt:
    mkt_c1, mkt_c2 = st.columns([3, 1])
    with mkt_c1:
        pil = st.selectbox("チャート期間", ["1週間", "1ヶ月", "3ヶ月", "1年"], index=1, key="idx_period")
    with mkt_c2:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if st.button("🔄 指標を更新", use_container_width=True, key="refresh_mkt"):
            # 世界指標のキャッシュだけクリアして再取得
            get_cached_market_data.clear()
            st.rerun()
    pmi = {"1週間": "5d", "1ヶ月": "1mo", "3ヶ月": "3mo", "1年": "1y"}
    sp = pmi[pil]
    idd = {"日経平均": "^N225", "TOPIX": "1306.T", "S&P 500": "^GSPC", "NASDAQ": "^IXIC", "ドル円": "JPY=X", "米国10年債利回り": "^TNX", "VIX": "^VIX", "金(GOLD)": "GC=F"}
    with st.spinner("指標データを取得中..."):
        ic = get_cached_market_data(tuple(sorted(idd.values())), period=sp)
        items = list(idd.items())
        for i in range(0, len(items), 2):
            rc = st.columns(2)
            for j in range(2):
                if i + j < len(items):
                    iname, tk = items[i + j]
                    with rc[j]:
                        st.markdown("<div class='indicator-card'>", unsafe_allow_html=True)
                        tc_, cc_ = st.columns([1, 1.5])
                        if tk in ic.columns:
                            ser = ic[tk].dropna()
                            if len(ser) >= 2:
                                lc = ser.iloc[-1]; prc = ser.iloc[-2]; pch = (lc / prc - 1) * 100; dif = lc - prc
                                col = "#00E676" if pch >= 0 else "#FF5252"
                                fc = "rgba(0,230,118,0.15)" if pch >= 0 else "rgba(255,82,82,0.15)"
                                sgn = "+" if pch >= 0 else ""
                                with tc_:
                                    st.markdown(f"<div style='display:flex;flex-direction:column;justify-content:center;height:150px'><p style='color:#B0B8C0;margin:0;font-size:14px;font-weight:bold'>{iname}</p><p style='color:#FFF;margin:5px 0 0;font-size:1.4rem;font-weight:bold'>{lc:,.2f}</p><p style='color:{col};margin:0 0 5px;font-size:13px;font-weight:bold'>{sgn}{dif:,.2f}<br>({sgn}{pch:.2f}%)</p></div>", unsafe_allow_html=True)
                                with cc_:
                                    fm = go.Figure(data=[go.Scatter(x=ser.index, y=ser.values, mode='lines', line=dict(color=col, width=2), fill='tozeroy', fillcolor=fc)])
                                    ymx, ymn = ser.max(), ser.min()
                                    ymg = (ymx - ymn) * 0.1 if ymx != ymn else lc * 0.1
                                    xtf = '%Y/%m' if sp == "1y" else '%m/%d'
                                    fm.update_layout(plot_bgcolor='#12161E', paper_bgcolor='#12161E', margin=dict(l=45, r=10, t=10, b=30), height=180, xaxis=dict(showgrid=True, gridcolor='#2B3240', griddash='dot', tickformat=xtf, tickfont=dict(color='#9E9E9E', size=10)), yaxis=dict(showgrid=True, gridcolor='#2B3240', griddash='dot', side='left', tickformat=',', tickfont=dict(color='#9E9E9E', size=10), range=[ymn - ymg, ymx + ymg]), showlegend=False)
                                    st.plotly_chart(fm, use_container_width=True, config={'displayModeBar': False})
                            else:
                                with tc_: st.markdown(f"<p style='color:#B0B8C0;font-weight:bold'>{iname}</p><p style='color:#FF5252'>データ不足</p>", unsafe_allow_html=True)
                        else:
                            with tc_: st.markdown(f"<p style='color:#B0B8C0;font-weight:bold'>{iname}</p><p style='color:#FF5252'>取得失敗</p>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)

# ── TAB 6: AI総評 ──
with tab_ai:
    st.markdown("#### 🤖 Claudeによるポートフォリオ総評")
    st.caption("現在の保有銘柄・損益状況・市場環境を踏まえた総合分析を生成します。")
    
    if not df.empty and total_asset > 0 and not display_df.empty:
        
        # APIキーの確認
        api_key = st.secrets.get("anthropic_api_key", "")
        if not api_key:
            st.warning("⚠ Streamlit Secretsに `anthropic_api_key` を設定してください。")
            st.code('anthropic_api_key = "sk-ant-xxxxx..."', language="toml")
            st.info("設定方法: Streamlit Cloud → Settings → Secrets に上記を追加")
        else:
            # ポートフォリオデータをテキストに変換
            def build_portfolio_summary():
                lines = []
                lines.append(f"■ ポートフォリオ概要")
                lines.append(f"  評価額合計: {total_asset:,.0f}円")
                lines.append(f"  税引後含み損益: {total_net_profit:,.0f}円")
                lines.append(f"  年間予想配当（税引前）: {total_dividend:,.0f}円")
                lines.append(f"  配当利回り: {avg_dividend_yield:.2f}%")
                lines.append(f"  為替レート: $1 = ¥{jpy_usd_rate:.1f}")
                lines.append(f"  銘柄数: {stock_count}")
                lines.append(f"")
                lines.append(f"■ 保有銘柄一覧")
                for _, row in display_df.iterrows():
                    code = row.get("銘柄コード", "")
                    name = row.get("銘柄名", "")
                    market = row.get("市場", "")
                    sector = row.get("セクター", "")
                    val = row.get("評価額(円)", 0)
                    pnl = row.get("税引後損益(円)", 0)
                    dod = row.get("前日比", None)
                    div_amt = row.get("予想配当(円)", 0)
                    pct_of_total = (val / total_asset * 100) if total_asset > 0 else 0
                    dod_str = f"前日比{dod:+.1f}%" if pd.notna(dod) else ""
                    lines.append(f"  {code} {name} [{market}/{sector}] 評価額:{val:,.0f}円({pct_of_total:.1f}%) 損益:{pnl:+,.0f}円 {dod_str} 配当:{div_amt:,.0f}円")
                
                # セクター配分
                lines.append(f"")
                lines.append(f"■ セクター配分")
                sector_grp = display_df[display_df["評価額(円)"] > 0].groupby("セクター")["評価額(円)"].sum().sort_values(ascending=False)
                for sec, val in sector_grp.items():
                    lines.append(f"  {sec}: {val:,.0f}円 ({val/total_asset*100:.1f}%)")
                
                return "\n".join(lines)
            
            portfolio_text = build_portfolio_summary()
            
            # ★ Google Sheetsに永続保存 + session_stateでキャッシュ
            def _load_ai_review_from_sheets():
                """Sheetsから読み込み（APIコール発生）"""
                sh = get_spreadsheet()
                if sh is None: return None, ""
                try:
                    ws = sh.worksheet("AI総評")
                    vals = ws.get_all_values()
                    if len(vals) >= 2 and vals[1][0]:
                        return vals[1][0], vals[1][1]
                except:
                    pass
                return None, ""
            
            def _save_ai_review_to_sheets(dt_str, text):
                """Sheetsに保存"""
                sh = get_spreadsheet()
                if sh is None: return
                try:
                    try:
                        ws = sh.worksheet("AI総評")
                    except:
                        ws = sh.add_worksheet(title="AI総評", rows="5", cols="2")
                        ws.update_cell(1, 1, "生成日時")
                        ws.update_cell(1, 2, "分析レポート")
                    ws.update_cell(2, 1, dt_str)
                    ws.update_cell(2, 2, text)
                except Exception as e:
                    st.warning(f"保存エラー: {e}")
            
            # session_stateに結果がなければSheetsから読み込む（初回のみAPI呼び出し）
            if "ai_review_dt" not in st.session_state:
                st.session_state.ai_review_dt = None
            if "ai_review_text" not in st.session_state:
                st.session_state.ai_review_text = ""
            if "ai_review_loaded" not in st.session_state:
                st.session_state.ai_review_loaded = False
            if "ai_confirm_regen" not in st.session_state:
                st.session_state.ai_confirm_regen = False
            
            # 初回だけSheetsから読み込む
            if not st.session_state.ai_review_loaded:
                try:
                    dt_str, text = _load_ai_review_from_sheets()
                    st.session_state.ai_review_dt = dt_str
                    st.session_state.ai_review_text = text
                except:
                    pass
                st.session_state.ai_review_loaded = True
            
            saved_dt_str = st.session_state.ai_review_dt
            saved_text = st.session_state.ai_review_text
            
            # 前回の結果がある場合は表示
            if saved_text and saved_dt_str:
                try:
                    saved_dt = datetime.strptime(saved_dt_str, "%Y/%m/%d %H:%M")
                    hours_ago = (datetime.now() - saved_dt).total_seconds() / 3600
                    time_label = f"{hours_ago:.1f}時間前" if hours_ago < 48 else f"{hours_ago/24:.0f}日前"
                except:
                    saved_dt = None
                    time_label = ""
                
                st.markdown(f"""
                <div style='background:#12161E;border:1px solid #1E232F;border-radius:12px;padding:1.5rem;border-left:3px solid #00D2FF'>
                    <div style='color:#00D2FF;font-weight:700;margin-bottom:0.8rem;font-size:1rem'>🤖 Claude ポートフォリオ分析レポート</div>
                    <div style='color:#B0B8C0;font-size:0.75rem;margin-bottom:1rem'>{saved_dt_str} 時点の分析（{time_label}）</div>
                </div>
                """, unsafe_allow_html=True)
                st.markdown(saved_text)
                st.caption("⚠ この分析はAIによる参考情報であり、投資助言ではありません。投資判断はご自身の責任で行ってください。")
                st.markdown("---")
            
            # 24時間以内かどうか判定
            need_confirm = False
            if saved_dt_str:
                try:
                    saved_dt = datetime.strptime(saved_dt_str, "%Y/%m/%d %H:%M")
                    if (datetime.now() - saved_dt).total_seconds() < 86400:
                        need_confirm = True
                except:
                    pass
            
            if need_confirm and not st.session_state.ai_confirm_regen:
                hours_ago = (datetime.now() - saved_dt).total_seconds() / 3600
                st.info(f"⏱ {hours_ago:.1f}時間前に生成済みです。再生成するとAPIクレジットを消費します。")
                if st.button("🔄 それでも再生成する", use_container_width=True, key="gen_ai_confirm"):
                    st.session_state.ai_confirm_regen = True
                    st.rerun()
            else:
                btn_label = "🔄 AI総評を再生成する" if saved_text else "📝 AI総評を生成する"
                if st.button(btn_label, use_container_width=True, key="gen_ai"):
                    st.session_state.ai_confirm_regen = False
                    with st.spinner("Claudeが分析中... （20〜30秒かかります）"):
                        try:
                            import requests as req
                            
                            prompt = f"""あなたは日本の個人投資家向けのポートフォリオアドバイザーです。
以下のポートフォリオデータを分析して、日本語で総合的な評価レポートを作成してください。

{portfolio_text}

以下の5つの観点で分析してください。各セクションは見出しを付けて整理してください。

1. **全体評価** — ポートフォリオの健全度（分散度合い、リスク水準）を5段階で評価し、理由を述べてください。

2. **強みと弱み** — このポートフォリオの良い点と改善すべき点を具体的に挙げてください。特に集中リスクや特定セクターへの偏りに言及してください。

3. **市場環境との整合性** — 現在の世界経済・日本経済の状況（金利動向、為替、地政学リスク等）を踏まえ、このポートフォリオの妥当性を評価してください。

4. **配当戦略の評価** — 配当利回りと配当月の分散度合いを評価してください。キャッシュフローの安定性についてコメントしてください。

5. **アクション提案** — 具体的な改善アクションを3〜5つ、優先度付きで提案してください。「○○セクターを○%まで引き上げ」のように具体的な数字を入れてください。

注意: 投資助言ではなく、あくまで参考情報としての分析です。最終的な投資判断は本人が行うものです。"""

                            response = req.post(
                                "https://api.anthropic.com/v1/messages",
                                headers={
                                    "Content-Type": "application/json",
                                    "x-api-key": api_key,
                                    "anthropic-version": "2023-06-01",
                                },
                                json={
                                    "model": "claude-sonnet-4-20250514",
                                    "max_tokens": 2000,
                                    "messages": [{"role": "user", "content": prompt}],
                                },
                                timeout=60,
                            )
                            
                            if response.status_code == 200:
                                data = response.json()
                                ai_text = "".join([b["text"] for b in data["content"] if b["type"] == "text"])
                                
                                # session_state + Google Sheetsに保存
                                now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
                                st.session_state.ai_review_dt = now_str
                                st.session_state.ai_review_text = ai_text
                                _save_ai_review_to_sheets(now_str, ai_text)
                                st.rerun()
                            else:
                                error_detail = response.json().get("error", {}).get("message", response.text)
                                st.error(f"API エラー (HTTP {response.status_code}): {error_detail}")
                        
                        except Exception as e:
                            st.error(f"エラーが発生しました: {e}")
            
            # 入力データのプレビュー
            with st.expander("📄 Claudeに送信されるデータ（プレビュー）", expanded=False):
                st.code(portfolio_text, language="text")
    else:
        st.info("銘柄を追加するとAI総評を利用できます。")