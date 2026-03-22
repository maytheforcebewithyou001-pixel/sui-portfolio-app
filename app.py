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

# ==========================================
# 🚀 高速化エンジン ＆ データ取得（キャッシュ機能）
# ==========================================
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

@st.cache_data(ttl=3600, show_spinner=False)
def get_cached_market_data(tickers, period="1y"):
    if not tickers: return pd.DataFrame()
    try:
        data = yf.download(tickers, period=period, progress=False)
        if isinstance(data.columns, pd.MultiIndex):
            closes = data['Close']
        else:
            closes = data[['Close']]
            closes.columns = [tickers[0]]
        return closes.ffill().bfill()
    except:
        return pd.DataFrame()

# ★修正：配当金の計算を「利回り」から「1株あたりの現金(Rate)」に変更して正確に！
@st.cache_data(ttl=86400, show_spinner=False)
def get_cached_ticker_info(tickers):
    info_dict = {}
    sector_map = {
        "Technology": "テクノロジー", "Financial Services": "金融", "Healthcare": "ヘルスケア", 
        "Consumer Cyclical": "一般消費財", "Industrials": "資本財", "Communication Services": "通信",
        "Consumer Defensive": "生活必需品", "Energy": "エネルギー", "Basic Materials": "素材", 
        "Real Estate": "不動産", "Utilities": "公益事業"
    }
    for t in tickers:
        if t == "JPY=X": continue
        try:
            info = yf.Ticker(t).info
            # 1株あたりの配当額（現金）を最優先で取得
            div_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0
            div_yield = info.get("dividendYield") or info.get("trailingAnnualDividendYield") or 0.0
            sec = info.get("sector") or "ETF/その他"
            info_dict[t] = {
                "sector": sector_map.get(sec, sec), 
                "div_rate": float(div_rate),
                "div_yield": float(div_yield)
            }
        except:
            info_dict[t] = {"sector": "不明", "div_rate": 0.0, "div_yield": 0.0}
    return info_dict

# ==========================================
# データ読み書き ＆ ヘルパー関数
# ==========================================
def load_data():
    gc = init_gspread()
    expected_cols = ["銘柄コード", "銘柄名", "市場", "保有株数", "取得単価", "口座", "口座区分", "最新更新日"]
    if gc is None: return pd.DataFrame(columns=expected_cols)
    try:
        sh = gc.open("PortfolioData") 
        data = sh.sheet1.get_all_records()
        df = pd.DataFrame(data) if data else pd.DataFrame(columns=expected_cols)
        for col in expected_cols:
            if col not in df.columns: df[col] = "特定口座" if col == "口座区分" else "-"
        df["銘柄コード"] = df["銘柄コード"].astype(str)
        df["銘柄名"] = df["銘柄名"].astype(str)
        df["保有株数"] = pd.to_numeric(df["保有株数"], errors='coerce').fillna(0)
        df["取得単価"] = pd.to_numeric(df["取得単価"], errors='coerce').fillna(0)
        return df
    except:
        return pd.DataFrame(columns=expected_cols)

def save_data(df):
    gc = init_gspread()
    if gc is None: return
    try:
        sh = gc.open("PortfolioData")
        sh.sheet1.clear()
        save_df = df.fillna("")
        sh.sheet1.update([save_df.columns.values.tolist()] + save_df.values.tolist())
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
    if not code: return "入力で損益計算"
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
# 🎨 UIとCSS設定
# ==========================================
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
    .card-dividend::before { background: linear-gradient(90deg, #FFD54F 0%, #FF8F00 100%); }
    .card-goal::before { background: linear-gradient(90deg, #9C27B0 0%, #D81B60 100%); }
    .stButton > button { background-color: #12161E; color: #BDBDBD; border: 1px solid #1E232F; border-radius: 20px; padding: 0.5rem 1.2rem; font-size: 0.9rem; }
    .stButton > button:hover { background-color: #1E232F; color: #FFFFFF; border: 1px solid #00D2FF; }
    .indicator-card { background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; }
    .streamlit-expanderHeader { background-color: #12161E; border-radius: 10px; color: #FFFFFF; font-weight: bold; font-size: 1.1rem; border: 1px solid #1E232F; }
    th { background-color: #1E232F !important; color: #FFFFFF !important; }
    </style>
    """, unsafe_allow_html=True
)

header_col1, header_col2, header_col3 = st.columns([3, 1, 1.5])
with header_col1: st.markdown("<div class='logo-text'>P<span>ORTFOLIO</span></div>", unsafe_allow_html=True)
with header_col2: st.write(f"\n資産管理 ・ {datetime.now().strftime('%Y/%m/%d')}")
with header_col3:
    if st.button("🔄 全データ 最新化 (キャッシュクリア)"):
        st.cache_data.clear() 
        st.rerun()

st.markdown("<hr style='border-top: 1px solid #1E232F; margin: 0 0 1rem 0;'>", unsafe_allow_html=True)

# ==========================================
# ⚙️ 目標・シミュレーション設定
# ==========================================
with st.expander("⚙️ 目標・シミュレーション設定", expanded=True):
    slider_col1, slider_col2, slider_col3 = st.columns([1, 1, 1])
    with slider_col1:
        goal_oku = st.slider("🎯 目標金額を設定 (億円)", min_value=0.5, max_value=10.0, value=1.2, step=0.1)
        goal_amount = goal_oku * 1e8
    with slider_col2:
        interest_rate_pct = st.slider("📈 想定年利 (%)", min_value=1.0, max_value=20.0, value=6.0, step=0.5)
        interest_rate = interest_rate_pct / 100.0
    with slider_col3:
        yearly_add_man = st.number_input("💰 年間の積立額 (万円)", min_value=0, value=120, step=10)
        yearly_add = yearly_add_man * 10000

# ==========================================
# 📊 データ一括処理 ＆ 計算（配当・税金含む）
# ==========================================
df = load_data()

if not df.empty:
    with st.spinner('市場データと配当・業種情報を取得中...'):
        tickers_to_fetch = ["JPY=X"]
        for _, row in df.iterrows():
            code = str(row["銘柄コード"])
            market = row["市場"]
            if market == "日本株": tickers_to_fetch.append(f"{code}.T")
            elif market == "米国株": tickers_to_fetch.append(code)
        
        closes_df = get_cached_market_data(list(set(tickers_to_fetch)), period="1y")
        info_dict = get_cached_ticker_info(list(set(tickers_to_fetch)))
        
        if "JPY=X" in closes_df.columns:
            jpy_usd_series = closes_df["JPY=X"].dropna()
            jpy_usd_rate = jpy_usd_series.iloc[-1] if not jpy_usd_series.empty else 150.0
        else:
            jpy_usd_rate = 150.0

        current_prices_jpy, total_values, profits, net_profits, dividends, buy_prices_jpy, update_dates = [], [], [], [], [], [], []
        dod_list, mom_list, yoy_list, sector_list = [], [], [], []
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
        
        for index, row in df.iterrows():
            ticker_code, market_type = str(row["銘柄コード"]), row["市場"]
            shares, buy_price_raw = float(row["保有株数"]), float(row["取得単価"])
            tax_category = str(row.get("口座区分", "特定口座"))
            
            fetch_success = False
            dod_pct = mom_pct = yoy_pct = None
            price_jpy = value = buy_total = buy_jpy = dividend = net_profit = 0
            
            t = f"{ticker_code}.T" if market_type == "日本株" else ticker_code
            
            # 業種と配当情報を取り出す
            sector = info_dict.get(t, {}).get("sector", "手動入力/その他")
            div_rate = info_dict.get(t, {}).get("div_rate", 0.0)
            div_yield = info_dict.get(t, {}).get("div_yield", 0.0)
            
            if market_type in ["日本株", "米国株"] and t in closes_df.columns:
                series = closes_df[t].dropna()
                if not series.empty:
                    latest_price = series.iloc[-1]
                    fetch_success = True
                    
                    if market_type == "日本株":
                        price_jpy = latest_price
                        buy_jpy = buy_price_raw
                        if len(series) >= 2: dod_pct = (price_jpy / series.iloc[-2] - 1) * 100
                        if len(series) >= 22: mom_pct = (price_jpy / series.iloc[-22] - 1) * 100
                        if len(series) >= 250: yoy_pct = (price_jpy / series.iloc[0] - 1) * 100
                    else:
                        price_jpy = latest_price * jpy_usd_rate
                        buy_jpy = buy_price_raw * jpy_usd_rate
                        if len(series) >= 2: dod_pct = (latest_price / series.iloc[-2] - 1) * 100
                        if len(series) >= 22: mom_pct = (latest_price / series.iloc[-22] - 1) * 100
                        if len(series) >= 250: yoy_pct = (latest_price / series.iloc[0] - 1) * 100
            else:
                price_jpy = buy_price_raw
                buy_jpy = buy_price_raw
                fetch_success = True

            value = price_jpy * shares
            buy_total = buy_jpy * shares
            profit = value - buy_total
            
            # ★修正：配当金の超・正確な計算（1株配当 × 株数）
            if div_rate > 0:
                if market_type == "日本株":
                    dividend = div_rate * shares
                elif market_type == "米国株":
                    dividend = div_rate * shares * jpy_usd_rate
                else:
                    dividend = value * div_yield
            else:
                # 取得できなかった場合のみ、評価額×利回りで代替計算
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
            mom_list.append(mom_pct)
            yoy_list.append(yoy_pct)
            sector_list.append(sector)
            update_dates.append(now_str if fetch_success else str(row.get("最新更新日", "-")))
                
        df["最新更新日"] = update_dates
            
        display_df = df.copy()
        display_df["セクター"] = sector_list
        display_df["取得単価(円)"] = buy_prices_jpy
        display_df["現在値(円)"] = current_prices_jpy
        display_df["前日比"] = dod_list
        display_df["前月比"] = mom_list
        display_df["前年比"] = yoy_list
        display_df["評価額(円)"] = total_values
        display_df["含み損益(円)"] = profits
        display_df["税引後損益(円)"] = net_profits
        display_df["予想配当(円)"] = dividends
        
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
# 💳 ステータスカード 
# ==========================================
card_col1, card_col2, card_col3, card_col4 = st.columns(4)
with card_col1: st.markdown(f"<div class='status-card card-total'><h4>評価額合計</h4><p class='main-value'>{total_asset:,.0f}円</p><p class='sub-value'>{stock_count}銘柄</p></div>", unsafe_allow_html=True)
with card_col2:
    profit_color = "#00E676" if total_net_profit >= 0 else "#FF1744"
    st.markdown(f"<div class='status-card card-profit'><h4>税引後 含み損益</h4><p class='main-value' style='color:{profit_color}'>{total_net_profit:,.0f}円</p><p class='sub-value'>1ドル {jpy_usd_rate:.2f}円</p></div>", unsafe_allow_html=True)
with card_col3:
    st.markdown(f"<div class='status-card card-dividend'><h4>年間予想配当金 (税引前)</h4><p class='main-value'>{total_dividend:,.0f}円</p><p class='sub-value'>平均利回り {avg_dividend_yield:.2f}%</p></div>", unsafe_allow_html=True)
with card_col4:
    progress = min(total_asset / goal_amount * 100, 100.0) if goal_amount > 0 else 100.0
    st.markdown(f"<div class='status-card card-goal'><h4>{goal_oku}億円ゴール</h4><p class='main-value'>{progress:.1f}<span>%</span></p><p class='sub-value'>残り {max((goal_amount - total_asset)/1e8, 0):,.2f}億円</p></div>", unsafe_allow_html=True)

# ==========================================
# 📈 分析 ＆ ヒートマップ
# ==========================================
if not df.empty and total_asset > 0:
    with st.expander("📈 ポートフォリオ分析 ＆ ヒートマップ", expanded=True):
        
        pie_col1, pie_col2 = st.columns(2)
        with pie_col1:
            st.markdown("#### 🍩 銘柄別割合")
            display_df["円グラフ表示名"] = display_df["銘柄コード"].astype(str) + " " + display_df["銘柄名"].astype(str)
            fig_pie1 = px.pie(display_df, values="評価額(円)", names="円グラフ表示名", hole=0.4)
            fig_pie1.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fig_pie1, use_container_width=True)

        with pie_col2:
            st.markdown("#### 🏢 セクター(業種)別割合")
            fig_pie2 = px.pie(display_df, values="評価額(円)", names="セクター", hole=0.4)
            fig_pie2.update_traces(textposition='inside', textinfo='percent+label')
            fig_pie2.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(fig_pie2, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 🗺️ マーケット・ヒートマップ (本日)")
        st.caption("※四角の大きさが「評価額」、色が「本日の値動き(緑=プラス、赤=マイナス)」を表しています。クリックで拡大できます。")
        
        # ★修正：ヒートマップ表示のバグ防止（評価額0円を除外し、確実な階層を作成）
        tree_df = display_df[display_df["評価額(円)"] > 0].copy()
        if not tree_df.empty:
            tree_df["全体"] = "ポートフォリオ" # エラー原因だったpx.Constantを回避
            tree_df["前日比(数値)"] = tree_df["前日比"].apply(lambda x: x if pd.notna(x) else 0.0)
            tree_df["Treemap Label"] = tree_df["銘柄名"].astype(str) + "<br>" + tree_df["前日比(数値)"].apply(lambda x: f"+{x:.2f}%" if x > 0 else f"{x:.2f}%")
            
            fig_tree = px.treemap(
                tree_df,
                path=["全体", "市場", "セクター", "Treemap Label"],
                values="評価額(円)",
                color="前日比(数値)",
                color_continuous_scale="RdYlGn",
                color_continuous_midpoint=0,
                hover_data=["含み損益(円)", "予想配当(円)"]
            )
            fig_tree.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=500, paper_bgcolor='#0A0E13')
            fig_tree.data[0].textfont.color = "white"
            st.plotly_chart(fig_tree, use_container_width=True)
        else:
            st.info("ヒートマップを表示するためのデータがありません。")

# ==========================================
# 🚀 未来シミュレーション
# ==========================================
if not df.empty and total_asset > 0:
    with st.expander("🚀 ゴール逆算 ＆ 未来シミュレーション", expanded=True):
        st.markdown(f"#### 🎯 {goal_oku}億円ゴール 年間必要積立額 (年利{interest_rate_pct}%)")
        years_list, pmts = [10, 15, 20, 25, 30], []
        for y in years_list:
            shortfall = goal_amount - (total_asset * ((1 + interest_rate) ** y))
            pmts.append(shortfall / (((1 + interest_rate) ** y - 1) / interest_rate) if shortfall > 0 else 0)
        
        sim_df_bar = pd.DataFrame({"達成年数": [f"{y}年後" for y in years_list], "年間積立額": pmts})
        sim_df_bar["表示用金額"] = sim_df_bar["年間積立額"].apply(lambda x: f"{int(x):,}円" if x > 0 else "達成確実！")
        
        fig_bar = px.bar(sim_df_bar, x="年間積立額", y="達成年数", orientation='h', text="表示用金額")
        fig_bar.update_traces(textposition='auto', marker_color='#00D2FF')
        fig_bar.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(t=10, b=10), xaxis=dict(tickformat=",", ticksuffix="円"))
        st.plotly_chart(fig_bar, use_container_width=True)

        st.markdown("---")
        st.markdown("#### 🚀 未来の資産推移シミュレーション")
        period_label_future = st.select_slider("シミュレーション期間", options=["1年後", "3年後", "5年後", "10年後", "20年後", "30年後"], value="10年後")
        years_map = {"1年後": 1, "3年後": 3, "5年後": 5, "10年後": 10, "20年後": 20, "30年後": 30}
        
        sim_df_line = get_future_simulation(total_asset, interest_rate, years_map[period_label_future], yearly_add)

        fig_future = go.Figure()
        fig_future.add_trace(go.Scatter(x=sim_df_line["日時"], y=sim_df_line["予測評価額(円)"], mode='lines', line=dict(color="#00D2FF", width=3), fill='tozeroy', fillcolor="rgba(0, 210, 255, 0.15)", name="予測評価額"))
        if goal_amount > 0:
            fig_future.add_trace(go.Scatter(x=[sim_df_line["日時"].iloc[0], sim_df_line["日時"].iloc[-1]], y=[goal_amount, goal_amount], mode='lines', line=dict(color="#FF1744", width=2, dash='dash'), name=f"目標 ({goal_oku}億円)"))

        fig_future.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(l=0, r=0, t=20, b=10), height=350, xaxis=dict(showgrid=True, gridcolor='#1E232F'), yaxis=dict(showgrid=True, gridcolor='#1E232F', tickformat=","), legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
        st.plotly_chart(fig_future, use_container_width=True)

# ==========================================
# 📌 銘柄の追加・修正・一覧
# ==========================================
with st.expander("📌 銘柄データの登録・修正・一覧", expanded=True):
    st.markdown("#### ➕ 新規追加")
    in_c1, in_c2, in_c3, in_c4, in_c5, in_c6, in_c7 = st.columns([1, 1, 1.5, 1, 1.2, 1, 1.2])
    with in_c1: market = st.selectbox("市場", ["日本株", "米国株", "投資信託", "その他資産"])
    with in_c2: code = st.text_input("証券コード", placeholder="例: 7203")
    with in_c3:
        name = get_ticker_name(code, market)
        manual_name = st.text_input("銘柄名", value=name if market in ["日本株", "米国株"] else "")
    with in_c4: shares = st.number_input("保有数", min_value=0.0001, value=100.0)
    with in_c5: avg_price = st.number_input("取得単価", min_value=0.0, value=0.0)
    with in_c6: account_type = st.selectbox("証券会社", ["SBI", "楽天", "マネックス", "その他"])
    with in_c7: tax_type = st.selectbox("口座区分", ["特定口座(課税)", "NISA口座(非課税)"])

    col_btn1, col_btn2 = st.columns([1, 6])
    with col_btn1:
        st.write("\n")
        if st.button("＋ 追加") and code:
            final_name = manual_name if manual_name else name
            now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
            new_data = pd.DataFrame({
                "銘柄コード": [code], "銘柄名": [final_name], "市場": [market], 
                "保有株数": [shares], "取得単価": [avg_price], "口座": [account_type], "口座区分": [tax_type], "最新更新日": [now_str]
            })
            df = pd.concat([df, new_data], ignore_index=True)
            save_data(df)
            st.cache_data.clear()
            st.success("追加しました！")
            st.rerun()

    if not df.empty:
        st.markdown("---")
        st.markdown("#### ✏️ 修正・削除")
        
        edit_df = df.copy()
        edit_df["削除"] = False 
        
        edit_col1, edit_col2 = st.columns([6, 1])
        with edit_col1:
            edited_df = st.data_editor(edit_df, num_rows="dynamic", use_container_width=True, hide_index=True)
        with edit_col2:
            st.write("\n\n")
            if st.button("💾 変更・削除を保存"):
                df_to_save = edited_df[edited_df["削除"] == False].drop(columns=["削除"])
                save_data(df_to_save)
                st.cache_data.clear()
                st.success("更新しました！")
                st.rerun()

        st.markdown("#### 📊 ポートフォリオ詳細一覧")
        def color_profit(val): return f"color: {'#00E676' if val >= 0 else '#FF1744'}"
        def color_pct(val): return "" if pd.isna(val) else f"color: {'#00E676' if val > 0 else '#FF1744' if val < 0 else '#E0E0E0'}"
        def format_pct(val): return "-" if pd.isna(val) else (f"+{val:.1f}%" if val > 0 else f"{val:.1f}%")
        
        show_cols = ["銘柄コード", "銘柄名", "口座区分", "セクター", "保有株数", "取得単価(円)", "現在値(円)", "前日比", "評価額(円)", "税引後損益(円)", "予想配当(円)"]
        format_dict = {"保有株数": round_up_3, "取得単価(円)": round_up_3, "現在値(円)": round_up_3, "前日比": format_pct, "評価額(円)": "{:,.0f}", "税引後損益(円)": "{:,.0f}", "予想配当(円)": "{:,.0f}"}
        
        styled_df = display_df[show_cols].style.applymap(color_profit, subset=['税引後損益(円)']).applymap(color_pct, subset=['前日比']).format(format_dict)
        st.dataframe(styled_df, use_container_width=True, hide_index=True)

# ==========================================
# 🌍 世界の主要指標 (一括キャッシュ取得)
# ==========================================
with st.expander("🌍 世界の主要指標 ＆ トレンド", expanded=True):
    period_idx_label = st.selectbox("チャートの期間を選択", ["1週間前", "1ヶ月前", "3ヶ月前", "1年前"], index=1)
    period_map_idx = {"1週間前": "5d", "1ヶ月前": "1mo", "3ヶ月前": "3mo", "1年前": "1y"}
    selected_period = period_map_idx[period_idx_label]

    indices_dict = {
        "日経平均": "^N225", "日経先物": "NIY=F", "TOPIX": "1306.T", 
        "NYダウ": "^DJI", "S&P 500": "^GSPC", "S&P先物": "ES=F", "NASDAQ": "^IXIC"
    }
    
    with st.spinner("指標データを計算中..."):
        indices_closes = get_cached_market_data(list(indices_dict.values()), period=selected_period)
        
        items = list(indices_dict.items())
        for i in range(0, len(items), 2):
            row_cols = st.columns(2)
            for j in range(2):
                if i + j < len(items):
                    name, ticker = items[i + j]
                    with row_cols[j]:
                        st.markdown("<div class='indicator-card'>", unsafe_allow_html=True)
                        text_col, chart_col = st.columns([1, 1.5])
                        
                        if ticker in indices_closes.columns:
                            series = indices_closes[ticker].dropna()
                            if len(series) >= 2:
                                latest_close = series.iloc[-1]
                                prev_close = series.iloc[-2]
                                pct_change = (latest_close / prev_close - 1) * 100
                                diff = latest_close - prev_close
                                
                                color = "#00E676" if pct_change >= 0 else "#FF1744"
                                fill_color = "rgba(0, 230, 118, 0.15)" if pct_change >= 0 else "rgba(255, 23, 68, 0.15)"
                                sign = "+" if pct_change >= 0 else ""
                                
                                with text_col:
                                    st.markdown(f"""
                                        <div style='display:flex; flex-direction:column; justify-content:center; height:150px;'>
                                            <p style='color:#BDBDBD; margin:0; font-size:14px; font-weight:bold;'>{name}</p>
                                            <p style='color:#FFFFFF; margin:5px 0 0 0; font-size:1.4rem; font-weight:bold;'>{latest_close:,.2f}</p>
                                            <p style='color:{color}; margin:0 0 5px 0; font-size:13px; font-weight:bold;'>{sign}{diff:,.2f}<br>({sign}{pct_change:.2f}%)</p>
                                        </div>
                                    """, unsafe_allow_html=True)
                                
                                with chart_col:
                                    fig_mini = go.Figure(data=[go.Scatter(x=series.index, y=series.values, mode='lines', line=dict(color=color, width=2), fill='tozeroy', fillcolor=fill_color)])
                                    y_max, y_min = series.max(), series.min()
                                    y_margin = (y_max - y_min) * 0.1 if y_max != y_min else latest_close * 0.1
                                    x_tickformat = '%Y/%m' if selected_period == "1y" else '%m/%d'
                                    
                                    fig_mini.update_layout(
                                        plot_bgcolor='#12161E', paper_bgcolor='#12161E', margin=dict(l=45, r=10, t=10, b=30), height=180, 
                                        xaxis=dict(showgrid=True, gridcolor='#2B3240', griddash='dot', visible=True, tickformat=x_tickformat, tickfont=dict(color='#9E9E9E', size=10)),
                                        yaxis=dict(showgrid=True, gridcolor='#2B3240', griddash='dot', visible=True, side='left', tickformat=',', tickfont=dict(color='#9E9E9E', size=10), range=[y_min - y_margin, y_max + y_margin]),
                                        showlegend=False
                                    )
                                    st.plotly_chart(fig_mini, use_container_width=True, config={'displayModeBar': False})
                            else:
                                with text_col: st.markdown(f"<p style='color:#BDBDBD; margin:0; font-size:14px; font-weight:bold;'>{name}</p><p style='color:#FF1744;'>データ不足</p>", unsafe_allow_html=True)
                        else:
                            with text_col: st.markdown(f"<p style='color:#BDBDBD; margin:0; font-size:14px; font-weight:bold;'>{name}</p><p style='color:#FF1744;'>取得失敗</p>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)