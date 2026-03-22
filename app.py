import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os
import math
from datetime import datetime
import json
import gspread
from google.oauth2.service_account import Credentials

st.set_page_config(page_title="PORTFOLIO資産管理", layout="wide", initial_sidebar_state="collapsed")

# --- 🚀スプレッドシート接続の初期化 ---
@st.cache_resource
def init_gspread():
    try:
        creds_json = json.loads(st.secrets["gcp_credentials"])
        scopes = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
        credentials = Credentials.from_service_account_info(creds_json, scopes=scopes)
        gc = gspread.authorize(credentials)
        return gc
    except Exception as e:
        st.error(f"認証エラー: Secretsの設定を確認してください。詳細: {e}")
        return None

def load_data():
    gc = init_gspread()
    expected_cols = ["銘柄コード", "銘柄名", "市場", "保有株数", "取得単価", "口座", "最新更新日"]
    if gc is None:
        return pd.DataFrame(columns=expected_cols)
        
    try:
        sh = gc.open("PortfolioData") 
        worksheet = sh.sheet1
        data = worksheet.get_all_records()
        if data:
            df = pd.DataFrame(data)
        else:
            df = pd.DataFrame(columns=expected_cols)
            
        for col in expected_cols:
            if col not in df.columns:
                df[col] = "-"
        
        df["銘柄コード"] = df["銘柄コード"].astype(str)
        df["銘柄名"] = df["銘柄名"].astype(str)
        
        df["保有株数"] = pd.to_numeric(df["保有株数"], errors='coerce').fillna(0)
        df["取得単価"] = pd.to_numeric(df["取得単価"], errors='coerce').fillna(0)
        return df
        
    except Exception as e:
        st.error("スプレッドシートの読み込みに失敗しました。「PortfolioData」という名前か、共有設定ができているか確認してください。")
        return pd.DataFrame(columns=expected_cols)

def save_data(df):
    gc = init_gspread()
    if gc is None: return
    try:
        sh = gc.open("PortfolioData")
        worksheet = sh.sheet1
        worksheet.clear()
        save_df = df.fillna("")
        worksheet.update([save_df.columns.values.tolist()] + save_df.values.tolist())
    except Exception as e:
        st.error(f"スプレッドシートへの保存に失敗しました。詳細: {e}")

# --- ★新規：未来の資産推移シミュレーション関数 ---
def get_future_simulation(current_asset, annual_rate, years):
    months = years * 12
    today = datetime.now()
    dates = [today + pd.DateOffset(months=i) for i in range(months + 1)]
    # 月複利で計算
    values = [current_asset * ((1 + annual_rate) ** (i / 12)) for i in range(months + 1)]
    return pd.DataFrame({"日時": dates, "予測評価額(円)": values})

# --------------------------------------------------------

def get_ticker_name(code, market_type):
    if not code: return "入力で損益計算"
    if market_type in ["投資信託", "その他資産"]: return "手動入力"
    try:
        full_code = f"{code}.T" if market_type == "日本株" else code
        ticker = yf.Ticker(full_code)
        return ticker.info.get('longName', ticker.info.get('shortName', '名称不明'))
    except:
        return "取得失敗"

def get_exchange_rate():
    try:
        ticker = yf.Ticker("JPY=X")
        return ticker.history(period="5d")['Close'].iloc[-1]
    except:
        return 150.0

def round_up_3(val):
    try:
        val = float(val)
        rounded = math.ceil(val * 1000) / 1000
        if rounded.is_integer(): return f"{int(rounded):,}"
        else: return f"{rounded:,.3f}".rstrip('0').rstrip('.')
    except:
        return val

df = load_data()

with st.spinner('最新の為替レートを取得中...'):
    jpy_usd_rate = get_exchange_rate() if not df.empty else 150.0

# --- カスタムCSS ---
st.markdown(
    """
    <style>
    html, body, .stApp { overflow-y: auto !important; }
    .stApp { background-color: #0A0E13; color: #E0E0E0; font-family: sans-serif; }
    .logo-text { color: #00D2FF; font-weight: bold; font-size: 2.5rem; letter-spacing: 0.1rem; }
    .logo-text span { color: #E0E0E0; }
    .status-card { background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px; padding: 1.5rem; box-shadow: 0 4px 6px rgba(0,0,0,0.3); margin-bottom: 1rem; position: relative; }
    .status-card h4 { color: #BDBDBD; font-size: 1rem; margin: 0 0 0.5rem 0; }
    .status-card p.main-value { color: #FFFFFF; font-size: 1.8rem; font-weight: bold; margin: 0; }
    .status-card p.main-value span { color: #00D2FF; font-size: 1.2rem; margin-left: 0.2rem; }
    .status-card p.sub-value { color: #9E9E9E; font-size: 0.9rem; margin: 0.2rem 0 0 0; }
    .status-card p.no-value { color: #00E676; font-size: 1.2rem; margin: 0; }
    .status-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; border-radius: 10px 10px 0 0; }
    .card-total::before { background: linear-gradient(90deg, #00D2FF 0%, #3A7BD5 100%); }
    .card-profit::before { background: linear-gradient(90deg, #00E676 0%, #C0CA33 100%); }
    .card-goal::before { background: linear-gradient(90deg, #00D2FF 0%, #9C27B0 100%); }
    .card-count::before { background: linear-gradient(90deg, #9C27B0 0%, #D81B60 100%); }
    .stButton > button { background-color: #12161E; color: #BDBDBD; border: 1px solid #1E232F; border-radius: 20px; padding: 0.5rem 1.2rem; font-size: 0.9rem; }
    .stButton > button:hover { background-color: #1E232F; color: #FFFFFF; border: 1px solid #00D2FF; }
    .indicator-card { background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; }
    </style>
    """, unsafe_allow_html=True
)

header_col1, header_col2, header_col3 = st.columns([3, 1, 1.5])
with header_col1: st.markdown("<div class='logo-text'>P<span>ORTFOLIO</span></div>", unsafe_allow_html=True)
with header_col2: st.write(f"\n資産管理 ・ {datetime.now().strftime('%Y/%m/%d')}")
with header_col3:
    if st.button("🔄 全データ 最新化"): st.rerun()

st.markdown("<hr style='border-top: 1px solid #1E232F; margin: 0 0 1rem 0;'>", unsafe_allow_html=True)

slider_col1, slider_col2, _ = st.columns([1, 1, 1])
with slider_col1:
    goal_oku = st.slider("🎯 目標金額を設定 (億円)", min_value=0.5, max_value=10.0, value=1.5, step=0.1)
    goal_amount = goal_oku * 1e8
with slider_col2:
    interest_rate_pct = st.slider("📈 想定年利 (%)", min_value=1.0, max_value=20.0, value=5.0, step=0.5)
    interest_rate = interest_rate_pct / 100.0

if not df.empty:
    with st.spinner('各銘柄の最新データを取得・計算中...'):
        current_prices_jpy, total_values, profits, buy_prices_jpy, update_dates = [], [], [], [], []
        dod_list, mom_list, yoy_list = [], [], []
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
        
        for index, row in df.iterrows():
            ticker_code, market_type = str(row["銘柄コード"]), row["市場"]
            shares, buy_price_raw = float(row["保有株数"]), float(row["取得単価"])
            fetch_success = False
            dod_pct = mom_pct = yoy_pct = None
            
            try:
                if market_type == "日本株":
                    ticker = yf.Ticker(f"{ticker_code}.T")
                    hist = ticker.history(period="1y")
                    if not hist.empty:
                        closes = hist['Close']
                        price_jpy = closes.iloc[-1]
                        buy_jpy = buy_price_raw
                        fetch_success = True
                        if len(closes) >= 2: dod_pct = (price_jpy / closes.iloc[-2] - 1) * 100
                        if len(closes) >= 21: mom_pct = (price_jpy / closes.iloc[-22] - 1) * 100
                        if len(closes) >= 250: yoy_pct = (price_jpy / closes.iloc[0] - 1) * 100

                elif market_type == "米国株":
                    ticker = yf.Ticker(ticker_code)
                    hist = ticker.history(period="1y")
                    if not hist.empty:
                        closes = hist['Close']
                        price_usd = closes.iloc[-1]
                        price_jpy = price_usd * jpy_usd_rate 
                        buy_jpy = buy_price_raw * jpy_usd_rate
                        fetch_success = True
                        if len(closes) >= 2: dod_pct = (price_usd / closes.iloc[-2] - 1) * 100
                        if len(closes) >= 21: mom_pct = (price_usd / closes.iloc[-22] - 1) * 100
                        if len(closes) >= 250: yoy_pct = (price_usd / closes.iloc[0] - 1) * 100
                else:
                    price_jpy = buy_price_raw
                    buy_jpy = buy_price_raw
                    fetch_success = True
                
                value = price_jpy * shares
                buy_total = buy_jpy * shares
                
            except Exception as e:
                price_jpy = value = buy_total = buy_jpy = 0
            
            profit = value - buy_total
            current_prices_jpy.append(price_jpy)
            buy_prices_jpy.append(buy_jpy)
            total_values.append(value)
            profits.append(profit)
            
            dod_list.append(dod_pct)
            mom_list.append(mom_pct)
            yoy_list.append(yoy_pct)
            
            if fetch_success: update_dates.append(now_str)
            else: update_dates.append(str(row.get("最新更新日", "-")))
                
        df["最新更新日"] = update_dates
        save_data(df)
            
        display_df = df.copy()
        display_df["取得単価(円)"] = buy_prices_jpy
        display_df["現在値(円)"] = current_prices_jpy
        display_df["前日比"] = dod_list
        display_df["前月比"] = mom_list
        display_df["前年比"] = yoy_list
        display_df["評価額(円)"] = total_values
        display_df["含み損益(円)"] = profits
        
        total_asset = sum(total_values)
        total_profit = sum(profits)
        stock_count = len(df)
else:
    total_asset = total_profit = stock_count = 0
    display_df = pd.DataFrame()

card_col1, card_col2, card_col3, card_col4 = st.columns(4)
with card_col1: st.markdown(f"<div class='status-card card-total'><h4>評価額合計</h4><p class='main-value'>{total_asset:,.0f}円</p><p class='sub-value'>{stock_count}銘柄</p></div>", unsafe_allow_html=True)
with card_col2:
    profit_color = "#00E676" if total_profit >= 0 else "#FF1744"
    st.markdown(f"<div class='status-card card-profit'><h4>含み損益</h4><p class='main-value' style='color:{profit_color}'>{total_profit:,.0f}円</p><p class='sub-value'>1ドル {jpy_usd_rate:.2f}円 (最新)</p></div>", unsafe_allow_html=True)
with card_col3:
    progress = min(total_asset / goal_amount * 100, 100.0) if goal_amount > 0 else 100.0
    st.markdown(f"<div class='status-card card-goal'><h4>{goal_oku}億円ゴール</h4><p class='main-value'>{progress:.1f}<span>%</span></p><p class='sub-value'>残り {max((goal_amount - total_asset)/1e8, 0):,.2f}億円</p></div>", unsafe_allow_html=True)
with card_col4: st.markdown(f"<div class='status-card card-count'><h4>銘柄数</h4><p class='main-value'>{stock_count}</p><p class='sub-value'>投資信託含む</p></div>", unsafe_allow_html=True)

# --- ★新規：未来の資産推移シミュレーション ---
if total_asset > 0:
    st.markdown("---")
    st.markdown("### 📈 未来の資産推移シミュレーション")
    st.caption("※今日を起点とし、現在の評価額が上の「想定年利」で運用できた場合の未来予測（複利計算）です。")
    
    period_label_future = st.select_slider("シミュレーション期間", options=["1年後", "