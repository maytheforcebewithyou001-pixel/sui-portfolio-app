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

@st.cache_data(ttl=3600, show_spinner=False)
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
def load_data():
    sh = get_spreadsheet()
    expected_cols = ["銘柄コード", "銘柄名", "市場", "保有株数", "取得単価", "口座", "口座区分", "手動配当利回り(%)", "配当月", "最新更新日"]
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
                elif col == "配当月": df[col] = ""
                else: df[col] = "-"
        
        df["銘柄コード"] = df["銘柄コード"].astype(str)
        df["銘柄名"] = df["銘柄名"].astype(str)
        df["保有株数"] = pd.to_numeric(df["保有株数"], errors='coerce').fillna(0)
        df["取得単価"] = pd.to_numeric(df["取得単価"], errors='coerce').fillna(0)
        df["手動配当利回り(%)"] = pd.to_numeric(df["手動配当利回り(%)"], errors='coerce').fillna(0.0)
        
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
    dates, values = [], []
    current_val = current_asset
    for i in range(months + 1):
        dates.append(today + pd.DateOffset(months=i))
        values.append(current_val)
        current_val = current_val * (1 + monthly_rate) + monthly_add
    return pd.DataFrame({"日時": dates, "予測評価額(円)": values})

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
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

        for _, row in df.iterrows():
            ticker_code, market_type = str(row["銘柄コード"]), row["市場"]
            shares, buy_price_raw = float(row["保有株数"]), float(row["取得単価"])
            tax_category = str(row.get("口座区分", "特定口座"))
            manual_yield = float(row.get("手動配当利回り(%)", 0.0))
            div_month_str = str(row.get("配当月", ""))

            fetch_success = False
            dod_pct = None
            price_jpy = value = buy_jpy = dividend = net_profit = 0

            t = f"{ticker_code}.T" if market_type == "日本株" else ticker_code
            sector = info_dict.get(t, {}).get("sector", "手動入力/その他")
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
                        price_jpy = latest_price * jpy_usd_rate; buy_jpy = buy_price_raw * jpy_usd_rate
                    if len(series) >= 2:
                        prev = series.iloc[-2]
                        dod_pct = ((latest_price / prev) - 1) * 100 if prev != 0 else None
            else:
                price_jpy = buy_price_raw; buy_jpy = buy_price_raw; fetch_success = True

            value = price_jpy * shares
            buy_total = buy_jpy * shares
            profit = value - buy_total

            if manual_yield > 0:
                dividend = value * (manual_yield / 100.0)
            elif div_rate > 0:
                dividend = div_rate * shares * (jpy_usd_rate if market_type == "米国株" else 1)
            else:
                dividend = value * div_yield

            tax_rate = 0.0 if "NISA" in tax_category else 0.20315
            tax_amount = profit * tax_rate if profit > 0 else 0.0
            net_profit = profit - tax_amount

            current_prices_jpy.append(price_jpy)
            buy_prices_jpy.append(buy_jpy)
            total_values.append(value)
            profits.append(profit)
            net_profits.append(net_profit)
            dividends.append(dividend)
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
        display_df["手動配当利回り(%)"] = manual_yield_list
        display_df["配当月"] = div_month_list

        total_asset = sum(total_values)
        total_net_profit = sum(net_profits)
        total_dividend = sum(dividends)
        avg_dividend_yield = (total_dividend / total_asset * 100) if total_asset > 0 else 0.0
        stock_count = len(df)
else:
    total_asset = total_net_profit = total_dividend = avg_dividend_yield = stock_count = 0
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
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown(f"<div class='status-card card-total c1'><h4>評価額合計</h4><p class='mv'>{total_asset:,.0f}<span>円</span></p><p class='sv'>{stock_count}銘柄</p></div>", unsafe_allow_html=True)
with c2:
    pc = "#00E676" if total_net_profit >= 0 else "#FF5252"
    ps = "+" if total_net_profit >= 0 else ""
    pp = (total_net_profit / (total_asset - total_net_profit) * 100) if (total_asset - total_net_profit) > 0 else 0
    st.markdown(f"<div class='status-card card-profit c2'><h4>税引後 含み損益</h4><p class='mv' style='color:{pc}'>{ps}{total_net_profit:,.0f}<span>円</span></p><p class='sv'>{ps}{pp:.2f}%</p></div>", unsafe_allow_html=True)
with c3:
    monthly_div = total_dividend / 12 if total_dividend > 0 else 0
    st.markdown(f"<div class='status-card card-dividend c3'><h4>年間予想配当</h4><p class='mv'>{total_dividend:,.0f}<span>円</span></p><p class='sv'>利回り {avg_dividend_yield:.2f}% · 月平均 {monthly_div:,.0f}円</p></div>", unsafe_allow_html=True)
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
tab_pf, tab_an, tab_div, tab_sim, tab_mkt = st.tabs(["📊 ポートフォリオ", "🔍 分析", "💰 配当", "🚀 シミュレーション", "🌍 世界指標"])

# ── TAB 1: ポートフォリオ ──
with tab_pf:
    st.markdown("#### ➕ 銘柄を追加")
    r1a, r1b, r1c = st.columns([1, 1, 2])
    with r1a: market = st.selectbox("市場", ["日本株", "米国株", "投資信託", "その他資産"], key="form_market")
    with r1b: code = st.text_input("証券コード", placeholder="例: 7203", key="form_code")
    with r1c:
        name = get_ticker_name(code, market)
        manual_name = st.text_input("銘柄名", value=name if market in ["日本株", "米国株"] else "", key="form_name")

    r2a, r2b, r2c, r2d, r2e = st.columns([1, 1, 1, 1, 1])
    with r2a: shares = st.number_input("保有数", min_value=0.0001, value=100.0, key="form_shares")
    with r2b: avg_price = st.number_input("取得単価", min_value=0.0, value=0.0, key="form_price")
    with r2c: manual_div = st.number_input("手動利回り(%)", min_value=0.0, value=0.0, step=0.1, help="0=自動取得", key="form_div")
    with r2d: broker_type = st.selectbox("口座", ["SBI証券", "楽天証券", "持ち株会(野村證券)"], key="form_broker")
    with r2e: tax_type = st.selectbox("口座区分", ["特定口座", "NISA(成長投資枠)", "NISA(積立投資枠)"], key="form_tax")

    r3a, r3b = st.columns([1.5, 3.5])
    with r3a: div_months = st.text_input("配当月 (例: 3,9)", placeholder="3,6,9,12", help="カンマ区切りで入力", key="form_divmonth")
    with r3b: st.write("")

    if st.button("＋ 追加", key="add_btn") and code:
        final_name = manual_name if manual_name else name
        new_data = pd.DataFrame({
            "銘柄コード": [code], "銘柄名": [final_name], "市場": [market],
            "保有株数": [shares], "取得単価": [avg_price], "口座": [broker_type], "口座区分": [tax_type],
            "手動配当利回り(%)": [manual_div], "配当月": [div_months],
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
    else:
        st.info("銘柄を追加すると分析が表示されます。")

# ── TAB 3: 配当カレンダー ──
with tab_div:
    if not df.empty and total_asset > 0 and not display_df.empty:
        st.markdown("#### 💰 月別配当カレンダー")
        st.caption("各銘柄の「配当月」に基づいて月別の予想配当を表示します。銘柄追加時に配当月を入力してください。")

        # 月別配当集計
        monthly_dividends = {m: 0 for m in range(1, 13)}
        monthly_stocks = {m: [] for m in range(1, 13)}

        for _, row in display_df.iterrows():
            div_amount = row.get("予想配当(円)", 0)
            div_month_str = str(row.get("配当月", ""))
            if div_amount > 0 and div_month_str:
                try:
                    months_list = [int(m.strip()) for m in div_month_str.split(",") if m.strip().isdigit()]
                    per_payment = div_amount / len(months_list) if months_list else 0
                    for m in months_list:
                        if 1 <= m <= 12:
                            monthly_dividends[m] += per_payment
                            monthly_stocks[m].append(str(row["銘柄名"]))
                except:
                    pass

        # カレンダー表示（3列×4行）
        total_calendar_div = sum(monthly_dividends.values())
        month_names = ["1月", "2月", "3月", "4月", "5月", "6月", "7月", "8月", "9月", "10月", "11月", "12月"]
        for row_start in range(0, 12, 4):
            cols = st.columns(4)
            for i in range(4):
                m = row_start + i + 1
                with cols[i]:
                    amt = monthly_dividends[m]
                    cls = "div-month-active" if amt > 0 else "div-month-empty"
                    stocks_str = ", ".join(monthly_stocks[m][:3])
                    if len(monthly_stocks[m]) > 3:
                        stocks_str += f" 他{len(monthly_stocks[m])-3}"
                    st.markdown(f"""
                    <div class='div-month {cls}'>
                        <span class='month-label'>{month_names[m-1]}</span>
                        <span class='month-amount'>{"¥{:,.0f}".format(amt) if amt > 0 else "—"}</span>
                        <div style='font-size:0.65rem;color:#7A8A9A;margin-top:2px'>{stocks_str if amt > 0 else ""}</div>
                    </div>""", unsafe_allow_html=True)

        st.markdown("---")
        if total_calendar_div > 0:
            st.markdown(f"**カレンダー配当合計: ¥{total_calendar_div:,.0f}** （配当月が未入力の銘柄は含まれません）")
        else:
            st.info("配当月が入力されている銘柄がありません。銘柄追加時に「配当月」欄に 3,9 のように入力してください。")

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
        ff = go.Figure()
        ff.add_trace(go.Scatter(x=sdl["日時"], y=sdl["予測評価額(円)"], mode='lines', line=dict(color="#00D2FF", width=3), fill='tozeroy', fillcolor="rgba(0,210,255,0.15)", name="予測評価額"))
        if goal_amount > 0:
            ff.add_trace(go.Scatter(x=[sdl["日時"].iloc[0], sdl["日時"].iloc[-1]], y=[goal_amount, goal_amount], mode='lines', line=dict(color="#FF1744", width=2, dash='dash'), name=f"目標 ({goal_oku}億円)"))
        ff.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(l=0, r=0, t=20, b=10), height=350, xaxis=dict(showgrid=True, gridcolor='#1E232F'), yaxis=dict(showgrid=True, gridcolor='#1E232F', tickformat=","), legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
        st.plotly_chart(ff, use_container_width=True)
    else:
        st.info("銘柄を追加するとシミュレーションが表示されます。")

# ── TAB 5: 世界指標 ──
with tab_mkt:
    pil = st.selectbox("チャート期間", ["1週間", "1ヶ月", "3ヶ月", "1年"], index=1, key="idx_period")
    pmi = {"1週間": "5d", "1ヶ月": "1mo", "3ヶ月": "3mo", "1年": "1y"}
    sp = pmi[pil]
    idd = {"日経平均": "^N225", "日経先物": "NIY=F", "TOPIX": "1306.T", "NYダウ": "^DJI", "S&P 500": "^GSPC", "S&P先物": "ES=F", "NASDAQ": "^IXIC", "ドル円": "JPY=X"}
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
