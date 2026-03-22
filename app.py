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
            div_rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0.0
            div_yield = info.get("trailingAnnualDividendYield") or info.get("dividendYield") or 0.0
            if div_yield > 0.2: div_yield = 0.0
            sec = info.get("sector") or "ETF/その他"
            info_dict[t] = {"sector": sector_map.get(sec, sec), "div_rate": float(div_rate), "div_yield": float(div_yield)}
        except:
            info_dict[t] = {"sector": "不明", "div_rate": 0.0, "div_yield": 0.0}
    return info_dict

# ==========================================
# 📊 データ読み書き ＆ ヘルパー関数
# ==========================================
def load_data():
    gc = init_gspread()
    expected_cols = ["銘柄コード", "銘柄名", "市場", "保有株数", "取得単価", "口座", "口座区分", "手動配当利回り(%)", "最新更新日"]
    if gc is None: return pd.DataFrame(columns=expected_cols)
    try:
        sh = gc.open("PortfolioData") 
        data = sh.sheet1.get_all_records()
        df = pd.DataFrame(data) if data else pd.DataFrame(columns=expected_cols)
        for col in expected_cols:
            if col not in df.columns: 
                if col == "口座区分": df[col] = "特定口座"
                elif col == "手動配当利回り(%)": df[col] = 0.0
                else: df[col] = "-"
        df["銘柄コード"] = df["銘柄コード"].astype(str)
        df["銘柄名"] = df["銘柄名"].astype(str)
        df["保有株数"] = pd.to_numeric(df["保有株数"], errors='coerce').fillna(0)
        df["取得単価"] = pd.to_numeric(df["取得単価"], errors='coerce').fillna(0)
        df["手動配当利回り(%)"] = pd.to_numeric(df["手動配当利回り(%)"], errors='coerce').fillna(0.0)
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

def load_history():
    gc = init_gspread()
    if gc is None: return pd.DataFrame(columns=["日付", "総資産額(円)"])
    try:
        sh = gc.open("PortfolioData")
        try:
            worksheet = sh.worksheet("HistoryData")
        except:
            worksheet = sh.add_worksheet(title="HistoryData", rows="1000", cols="2")
            worksheet.append_row(["日付", "総資産額(円)"])
        data = worksheet.get_all_records()
        return pd.DataFrame(data) if data else pd.DataFrame(columns=["日付", "総資産額(円)"])
    except:
        return pd.DataFrame(columns=["日付", "総資産額(円)"])

def save_history(date_str, total_asset):
    gc = init_gspread()
    if gc is None: return
    try:
        sh = gc.open("PortfolioData")
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
st.markdown("""<style>
html, body, .stApp { overflow-y: auto !important; }
.stApp { background-color: #0A0E13; color: #E0E0E0; font-family: sans-serif; }
.logo-text { color: #00D2FF; font-weight: bold; font-size: 2.2rem; letter-spacing: 0.1rem; }
.logo-text span { color: #E0E0E0; }
.status-card { background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px; padding: 1.2rem; box-shadow: 0 4px 6px rgba(0,0,0,0.3); margin-bottom: 0.8rem; position: relative; }
.status-card h4 { color: #BDBDBD; font-size: 0.85rem; margin: 0 0 0.4rem 0; }
.status-card p.main-value { color: #FFFFFF; font-size: 1.6rem; font-weight: bold; margin: 0; }
.status-card p.main-value span { color: #00D2FF; font-size: 1.1rem; margin-left: 0.2rem; }
.status-card p.sub-value { color: #9E9E9E; font-size: 0.8rem; margin: 0.2rem 0 0 0; }
.status-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; border-radius: 10px 10px 0 0; }
.card-total::before { background: linear-gradient(90deg, #00D2FF, #3A7BD5); }
.card-profit::before { background: linear-gradient(90deg, #00E676, #C0CA33); }
.card-dividend::before { background: linear-gradient(90deg, #FFD54F, #FF8F00); }
.card-goal::before { background: linear-gradient(90deg, #9C27B0, #D81B60); }
.stButton > button { background-color: #12161E; color: #BDBDBD; border: 1px solid #1E232F; border-radius: 20px; padding: 0.5rem 1.2rem; font-size: 0.9rem; }
.stButton > button:hover { background-color: #1E232F; color: #FFFFFF; border: 1px solid #00D2FF; }
.indicator-card { background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; }
.streamlit-expanderHeader { background-color: #12161E; border-radius: 10px; color: #FFFFFF; font-weight: bold; font-size: 1.1rem; border: 1px solid #1E232F; }
th { background-color: #1E232F !important; color: #FFFFFF !important; }
.goal-bar-bg { background: #1E232F; border-radius: 6px; height: 10px; width: 100%; overflow: hidden; margin: 0.3rem 0; }
.goal-bar-fill { height: 100%; border-radius: 6px; background: linear-gradient(90deg, #00D2FF, #00E676); transition: width 0.8s ease; }
.goal-bar-labels { display: flex; justify-content: space-between; font-size: 0.7rem; color: #9E9E9E; }
.stTabs [data-baseweb="tab-list"] { gap: 0px; }
.stTabs [data-baseweb="tab"] { background-color: #12161E; border: 1px solid #1E232F; border-radius: 8px 8px 0 0; padding: 0.6rem 1.2rem; color: #BDBDBD; font-weight: bold; }
.stTabs [aria-selected="true"] { background-color: #1E232F; color: #00D2FF; border-bottom: 2px solid #00D2FF; }
@media (max-width: 768px) {
    .status-card p.main-value { font-size: 1.2rem; }
    .status-card h4 { font-size: 0.75rem; }
    .logo-text { font-size: 1.6rem; }
}
</style>""", unsafe_allow_html=True)

# ==========================================
# 🔝 ヘッダー
# ==========================================
header_col1, header_col2, header_col3 = st.columns([3, 1.5, 1.5])
with header_col1: st.markdown("<div class='logo-text'>P<span>ORTFOLIO</span></div>", unsafe_allow_html=True)
with header_col2: st.write(f"\n資産管理 ・ {datetime.now().strftime('%Y/%m/%d')}")
with header_col3:
    if st.button("🔄 全データ最新化", use_container_width=True):
        st.cache_data.clear(); st.rerun()

# ==========================================
# ⚙️ 目標設定
# ==========================================
with st.expander("⚙️ 目標・シミュレーション設定", expanded=False):
    s1, s2, s3 = st.columns(3)
    with s1: goal_oku = st.slider("🎯 目標金額 (億円)", 0.5, 10.0, 1.2, 0.1); goal_amount = goal_oku * 1e8
    with s2: interest_rate_pct = st.slider("📈 想定年利 (%)", 1.0, 20.0, 6.0, 0.5); interest_rate = interest_rate_pct / 100.0
    with s3: yearly_add_man = st.number_input("💰 年間積立額 (万円)", 0, value=120, step=10); yearly_add = yearly_add_man * 10000

# ==========================================
# 📊 データ一括処理
# ==========================================
df = load_data()

if not df.empty:
    with st.spinner('市場データと配当・業種情報を取得中...'):
        tickers_to_fetch = ["JPY=X"]
        for _, row in df.iterrows():
            code, mkt = str(row["銘柄コード"]), row["市場"]
            if mkt == "日本株": tickers_to_fetch.append(f"{code}.T")
            elif mkt == "米国株": tickers_to_fetch.append(code)
        closes_df = get_cached_market_data(list(set(tickers_to_fetch)), period="1y")
        info_dict = get_cached_ticker_info(list(set(tickers_to_fetch)))
        jpy_usd_rate = closes_df["JPY=X"].dropna().iloc[-1] if "JPY=X" in closes_df.columns and not closes_df["JPY=X"].dropna().empty else 150.0

        current_prices_jpy, total_values, profits, net_profits, dividends, buy_prices_jpy, update_dates = [], [], [], [], [], [], []
        dod_list, mom_list, yoy_list, sector_list, manual_yield_list = [], [], [], [], []
        now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
        
        for _, row in df.iterrows():
            tc, mt = str(row["銘柄コード"]), row["市場"]
            sh_n, bp = float(row["保有株数"]), float(row["取得単価"])
            tc_cat = str(row.get("口座区分", "特定口座"))
            my = float(row.get("手動配当利回り(%)", 0.0))
            fetch_ok = False; dod_pct = mom_pct = yoy_pct = None
            pj = val = bt = bj = div = np_ = 0
            t = f"{tc}.T" if mt == "日本株" else tc
            sec = info_dict.get(t, {}).get("sector", "手動入力/その他")
            dr = info_dict.get(t, {}).get("div_rate", 0.0)
            dy = info_dict.get(t, {}).get("div_yield", 0.0)
            
            if mt in ["日本株", "米国株"] and t in closes_df.columns:
                ser = closes_df[t].dropna()
                if not ser.empty:
                    lp = ser.iloc[-1]; fetch_ok = True
                    if mt == "日本株":
                        pj, bj = lp, bp
                        if len(ser) >= 2: dod_pct = (pj / ser.iloc[-2] - 1) * 100
                        if len(ser) >= 22: mom_pct = (pj / ser.iloc[-22] - 1) * 100
                        if len(ser) >= 250: yoy_pct = (pj / ser.iloc[0] - 1) * 100
                    else:
                        pj, bj = lp * jpy_usd_rate, bp * jpy_usd_rate
                        if len(ser) >= 2: dod_pct = (lp / ser.iloc[-2] - 1) * 100
                        if len(ser) >= 22: mom_pct = (lp / ser.iloc[-22] - 1) * 100
                        if len(ser) >= 250: yoy_pct = (lp / ser.iloc[0] - 1) * 100
            else:
                pj = bj = bp; fetch_ok = True

            val = pj * sh_n; bt = bj * sh_n; profit = val - bt
            if my > 0: div = val * (my / 100.0)
            elif dr > 0:
                if mt == "日本株": div = dr * sh_n
                elif mt == "米国株": div = dr * sh_n * jpy_usd_rate
                else: div = val * dy
            else: div = val * dy
            tr = 0.0 if "NISA" in tc_cat else 0.20315
            ta = profit * tr if profit > 0 else 0.0; np_ = profit - ta
            
            current_prices_jpy.append(pj); buy_prices_jpy.append(bj)
            total_values.append(val); profits.append(profit); net_profits.append(np_); dividends.append(div)
            dod_list.append(dod_pct); mom_list.append(mom_pct); yoy_list.append(yoy_pct)
            sector_list.append(sec); manual_yield_list.append(my)
            update_dates.append(now_str if fetch_ok else str(row.get("最新更新日", "-")))
                
        df["最新更新日"] = update_dates
        display_df = df.copy()
        display_df["セクター"] = sector_list; display_df["取得単価(円)"] = buy_prices_jpy
        display_df["現在値(円)"] = current_prices_jpy; display_df["前日比"] = dod_list
        display_df["前月比"] = mom_list; display_df["前年比"] = yoy_list
        display_df["評価額(円)"] = total_values; display_df["含み損益(円)"] = profits
        display_df["税引後損益(円)"] = net_profits; display_df["予想配当(円)"] = dividends
        display_df["手動配当利回り(%)"] = manual_yield_list
        total_asset = sum(total_values); total_net_profit = sum(net_profits)
        total_dividend = sum(dividends); avg_dividend_yield = (total_dividend / total_asset * 100) if total_asset > 0 else 0.0
        stock_count = len(df)
else:
    total_asset = total_net_profit = total_dividend = avg_dividend_yield = stock_count = 0
    jpy_usd_rate = 150.0; display_df = pd.DataFrame()

# ==========================================
# 💳 ステータスカード（常時表示・最上部）
# ==========================================
c1, c2, c3, c4 = st.columns(4)
with c1: st.markdown(f"<div class='status-card card-total'><h4>評価額合計</h4><p class='main-value'>{total_asset:,.0f}円</p><p class='sub-value'>{stock_count}銘柄</p></div>", unsafe_allow_html=True)
with c2:
    pc = "#00E676" if total_net_profit >= 0 else "#FF1744"
    st.markdown(f"<div class='status-card card-profit'><h4>税引後 含み損益</h4><p class='main-value' style='color:{pc}'>{total_net_profit:,.0f}円</p><p class='sub-value'>1ドル {jpy_usd_rate:.2f}円</p></div>", unsafe_allow_html=True)
with c3: st.markdown(f"<div class='status-card card-dividend'><h4>年間予想配当 (税引前)</h4><p class='main-value'>{total_dividend:,.0f}円</p><p class='sub-value'>平均利回り {avg_dividend_yield:.2f}%</p></div>", unsafe_allow_html=True)
with c4:
    prog = min(total_asset / goal_amount * 100, 100.0) if goal_amount > 0 else 100.0
    st.markdown(f"<div class='status-card card-goal'><h4>{goal_oku}億円ゴール</h4><p class='main-value'>{prog:.1f}<span>%</span></p><p class='sub-value'>残り {max((goal_amount - total_asset)/1e8, 0):,.2f}億円</p></div>", unsafe_allow_html=True)

# ゴール進捗バー
pv = min(total_asset / goal_amount * 100, 100.0) if goal_amount > 0 else 0
st.markdown(f"<div class='goal-bar-bg'><div class='goal-bar-fill' style='width:{pv}%'></div></div><div class='goal-bar-labels'><span>¥0</span><span style='color:#00D2FF'>{pv:.1f}% 達成</span><span>{goal_oku}億円</span></div>", unsafe_allow_html=True)
st.write("")

# ==========================================
# 📑 メインタブ
# ==========================================
tab_pf, tab_an, tab_sim, tab_mkt = st.tabs(["📋 ポートフォリオ", "📊 分析", "🚀 シミュレーション", "🌍 世界指標"])

# ── TAB 1: ポートフォリオ ──
with tab_pf:
    st.markdown("#### ➕ 新規銘柄を追加")
    r1c1, r1c2, r1c3 = st.columns([1, 1, 2])
    with r1c1: market = st.selectbox("市場", ["日本株", "米国株", "投資信託", "その他資産"])
    with r1c2: code = st.text_input("証券コード", placeholder="例: 7203")
    with r1c3:
        nm = get_ticker_name(code, market)
        manual_name = st.text_input("銘柄名", value=nm if market in ["日本株", "米国株"] else "")
    r2c1, r2c2, r2c3, r2c4, r2c5 = st.columns([1, 1, 1, 1.2, 1.2])
    with r2c1: shares = st.number_input("保有数", min_value=0.0001, value=100.0)
    with r2c2: avg_price = st.number_input("取得単価", min_value=0.0, value=0.0)
    with r2c3: manual_div = st.number_input("手動利回り(%)", min_value=0.0, value=0.0, step=0.1, help="0なら自動取得")
    with r2c4: account_type = st.selectbox("証券会社", ["SBI", "楽天", "マネックス", "その他"])
    with r2c5: tax_type = st.selectbox("口座区分", ["特定口座(課税)", "NISA口座(非課税)"])
    st.write("")
    bc1, bc2 = st.columns([1, 4])
    with bc1:
        if st.button("＋ 追加", use_container_width=True, key="add_stock") and code:
            fn = manual_name if manual_name else nm
            new_data = pd.DataFrame({"銘柄コード": [code], "銘柄名": [fn], "市場": [market], "保有株数": [shares], "取得単価": [avg_price], "口座": [account_type], "口座区分": [tax_type], "手動配当利回り(%)": [manual_div], "最新更新日": [datetime.now().strftime("%Y/%m/%d %H:%M")]})
            df = pd.concat([df, new_data], ignore_index=True); save_data(df); st.cache_data.clear(); st.success("追加しました！"); st.rerun()
    st.markdown("---")

    if total_asset > 0:
        hc1, hc2 = st.columns([4, 1])
        with hc1: st.markdown("#### 📈 資産額の推移")
        with hc2:
            st.write("")
            if st.button("💾 本日の資産を記録", use_container_width=True, key="sv_hist"):
                save_history(datetime.now().strftime("%Y/%m/%d"), total_asset); st.success("記録しました！"); st.rerun()
        hdf = load_history()
        if not hdf.empty and len(hdf) > 0:
            fh = px.line(hdf, x="日付", y="総資産額(円)", markers=True)
            fh.update_traces(line_color="#00E676", marker=dict(size=8, color="#FFFFFF"))
            fh.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(t=10,b=10,l=10,r=10), height=300, xaxis=dict(showgrid=True, gridcolor='#1E232F'), yaxis=dict(showgrid=True, gridcolor='#1E232F', tickformat=","))
            st.plotly_chart(fh, use_container_width=True)
        else:
            st.info("まだ履歴データがありません。「本日の資産を記録」ボタンで最初のデータを記録してください。")
    st.markdown("---")

    if not df.empty:
        with st.expander("✏️ 銘柄の修正・削除", expanded=False):
            edf = df.copy(); edf["削除"] = False
            edited = st.data_editor(edf, num_rows="dynamic", use_container_width=True, hide_index=True)
            if st.button("💾 変更・削除を保存", key="sv_edit"):
                save_data(edited[edited["削除"]==False].drop(columns=["削除"])); st.cache_data.clear(); st.success("更新しました！"); st.rerun()

    if not df.empty and not display_df.empty:
        st.markdown("#### 📊 ポートフォリオ詳細一覧")
        def cpf(v): return f"color: {'#00E676' if v >= 0 else '#FF1744'}"
        def cpc(v): return "" if pd.isna(v) else f"color: {'#00E676' if v > 0 else '#FF1744' if v < 0 else '#E0E0E0'}"
        def fp(v): return "-" if pd.isna(v) else (f"+{v:.1f}%" if v > 0 else f"{v:.1f}%")
        sc = ["銘柄コード","銘柄名","市場","口座区分","保有株数","取得単価(円)","現在値(円)","前日比","評価額(円)","税引後損益(円)","手動配当利回り(%)","予想配当(円)"]
        ac = [c for c in sc if c in display_df.columns]
        fd = {"保有株数": round_up_3, "取得単価(円)": round_up_3, "現在値(円)": round_up_3, "前日比": fp, "評価額(円)": "{:,.0f}", "税引後損益(円)": "{:,.0f}", "予想配当(円)": "{:,.0f}"}
        afd = {k:v for k,v in fd.items() if k in ac}
        sdf = display_df[ac].style
        if '税引後損益(円)' in ac: sdf = sdf.applymap(cpf, subset=['税引後損益(円)'])
        if '前日比' in ac: sdf = sdf.applymap(cpc, subset=['前日比'])
        sdf = sdf.format(afd)
        st.dataframe(sdf, use_container_width=True, hide_index=True)

# ── TAB 2: 分析 ──
with tab_an:
    if not df.empty and total_asset > 0:
        display_df["円グラフ表示名"] = display_df["銘柄コード"].astype(str) + " " + display_df["銘柄名"].astype(str)
        st.markdown("#### 🍩 銘柄別割合")
        ac1, ac2 = st.columns([1.2, 1])
        with ac1:
            fp1 = px.pie(display_df, values="評価額(円)", names="円グラフ表示名", hole=0.4)
            fp1.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', showlegend=False, margin=dict(t=10,b=10))
            st.plotly_chart(fp1, use_container_width=True)
        with ac2:
            tld = display_df[display_df["評価額(円)"]>0].groupby("円グラフ表示名",as_index=False)["評価額(円)"].sum().sort_values("評価額(円)",ascending=False)
            tld["割合"] = (tld["評価額(円)"]/total_asset*100).apply(lambda x: f"{x:.1f}%")
            tld["評価額(円)"] = tld["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            tld.rename(columns={"円グラフ表示名":"銘柄"}, inplace=True)
            st.write(""); st.dataframe(tld, use_container_width=True, hide_index=True)
        st.markdown("<hr style='border-top:1px dashed #1E232F;margin:1rem 0'>", unsafe_allow_html=True)
        
        st.markdown("#### 🏢 セクター別割合")
        sc1, sc2 = st.columns([1.2, 1])
        with sc1:
            fp2 = px.pie(display_df, values="評価額(円)", names="セクター", hole=0.4)
            fp2.update_traces(textposition='inside', textinfo='percent+label')
            fp2.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', showlegend=False, margin=dict(t=10,b=10))
            st.plotly_chart(fp2, use_container_width=True)
        with sc2:
            sld = display_df[display_df["評価額(円)"]>0].groupby("セクター",as_index=False)["評価額(円)"].sum().sort_values("評価額(円)",ascending=False)
            sld["割合"] = (sld["評価額(円)"]/total_asset*100).apply(lambda x: f"{x:.1f}%")
            sld["評価額(円)"] = sld["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            st.write(""); st.dataframe(sld, use_container_width=True, hide_index=True)
        st.markdown("---")
        
        st.markdown("#### 🗺️ マーケット・ヒートマップ")
        st.caption("四角の大きさ＝評価額、色＝本日の値動き。手動入力資産は除外。")
        tdf = display_df[(display_df["市場"].isin(["日本株","米国株"])) & (display_df["評価額(円)"]>0)].copy()
        if not tdf.empty:
            tdf["前日比(数値)"] = tdf["前日比"].apply(lambda x: x if pd.notna(x) else 0.0)
            tdf["Treemap Label"] = tdf["銘柄名"].astype(str)+"<br>"+tdf["前日比(数値)"].apply(lambda x: f"+{x:.2f}%" if x>0 else f"{x:.2f}%")
            ft = px.treemap(tdf, path=["市場","セクター","Treemap Label"], values="評価額(円)", color="前日比(数値)", color_continuous_scale="RdYlGn", color_continuous_midpoint=0, hover_data=["含み損益(円)","予想配当(円)"])
            ft.update_layout(margin=dict(t=10,l=10,r=10,b=10), height=500, paper_bgcolor='#0A0E13')
            ft.data[0].textfont.color = "black"
            st.plotly_chart(ft, use_container_width=True)
        else:
            st.info("ヒートマップ用のデータがありません。")
    else:
        st.info("銘柄を追加すると分析が表示されます。")

# ── TAB 3: シミュレーション ──
with tab_sim:
    if not df.empty and total_asset > 0:
        st.markdown(f"#### 🎯 {goal_oku}億円ゴール 年間必要積立額 (年利{interest_rate_pct}%)")
        yl, pm = [10,15,20,25,30], []
        for y in yl:
            sf = goal_amount - (total_asset * ((1+interest_rate)**y))
            pm.append(sf / (((1+interest_rate)**y - 1) / interest_rate) if sf > 0 else 0)
        sdb = pd.DataFrame({"達成年数": [f"{y}年後" for y in yl], "年間積立額": pm})
        sdb["表示用金額"] = sdb["年間積立額"].apply(lambda x: f"{int(x):,}円" if x > 0 else "達成確実！")
        fb = px.bar(sdb, x="年間積立額", y="達成年数", orientation='h', text="表示用金額")
        fb.update_traces(textposition='auto', marker_color='#00D2FF')
        fb.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(t=10,b=10), xaxis=dict(tickformat=",",ticksuffix="円"))
        st.plotly_chart(fb, use_container_width=True)
        st.markdown("---")
        st.markdown("#### 🚀 未来の資産推移シミュレーション")
        plf = st.select_slider("シミュレーション期間", options=["1年後","3年後","5年後","10年後","20年後","30年後"], value="10年後")
        ym = {"1年後":1,"3年後":3,"5年後":5,"10年後":10,"20年後":20,"30年後":30}
        sdl = get_future_simulation(total_asset, interest_rate, ym[plf], yearly_add)
        ff = go.Figure()
        ff.add_trace(go.Scatter(x=sdl["日時"], y=sdl["予測評価額(円)"], mode='lines', line=dict(color="#00D2FF",width=3), fill='tozeroy', fillcolor="rgba(0,210,255,0.15)", name="予測評価額"))
        if goal_amount > 0:
            ff.add_trace(go.Scatter(x=[sdl["日時"].iloc[0],sdl["日時"].iloc[-1]], y=[goal_amount,goal_amount], mode='lines', line=dict(color="#FF1744",width=2,dash='dash'), name=f"目標 ({goal_oku}億円)"))
        ff.update_layout(plot_bgcolor='#0A0E13', paper_bgcolor='#0A0E13', font_color='#E0E0E0', margin=dict(l=0,r=0,t=20,b=10), height=350, xaxis=dict(showgrid=True,gridcolor='#1E232F'), yaxis=dict(showgrid=True,gridcolor='#1E232F',tickformat=","), legend=dict(yanchor="top",y=0.99,xanchor="left",x=0.01))
        st.plotly_chart(ff, use_container_width=True)
    else:
        st.info("銘柄を追加するとシミュレーションが表示されます。")

# ── TAB 4: 世界指標 ──
with tab_mkt:
    pil = st.selectbox("チャートの期間", ["1週間前","1ヶ月前","3ヶ月前","1年前"], index=1, key="idx_period")
    pmi = {"1週間前":"5d","1ヶ月前":"1mo","3ヶ月前":"3mo","1年前":"1y"}
    sp = pmi[pil]
    idd = {"日経平均":"^N225","日経先物":"NIY=F","TOPIX":"1306.T","NYダウ":"^DJI","S&P 500":"^GSPC","S&P先物":"ES=F","NASDAQ":"^IXIC","ドル円":"JPY=X"}
    with st.spinner("指標データを取得中..."):
        ic = get_cached_market_data(list(idd.values()), period=sp)
        items = list(idd.items())
        for i in range(0, len(items), 2):
            rc = st.columns(2)
            for j in range(2):
                if i+j < len(items):
                    iname, tk = items[i+j]
                    with rc[j]:
                        st.markdown("<div class='indicator-card'>", unsafe_allow_html=True)
                        tc_, cc_ = st.columns([1, 1.5])
                        if tk in ic.columns:
                            ser = ic[tk].dropna()
                            if len(ser) >= 2:
                                lc = ser.iloc[-1]; prc = ser.iloc[-2]; pch = (lc/prc-1)*100; dif = lc-prc
                                col = "#00E676" if pch>=0 else "#FF1744"
                                fc = "rgba(0,230,118,0.15)" if pch>=0 else "rgba(255,23,68,0.15)"
                                sgn = "+" if pch>=0 else ""
                                with tc_: st.markdown(f"<div style='display:flex;flex-direction:column;justify-content:center;height:150px'><p style='color:#BDBDBD;margin:0;font-size:14px;font-weight:bold'>{iname}</p><p style='color:#FFF;margin:5px 0 0;font-size:1.4rem;font-weight:bold'>{lc:,.2f}</p><p style='color:{col};margin:0 0 5px;font-size:13px;font-weight:bold'>{sgn}{dif:,.2f}<br>({sgn}{pch:.2f}%)</p></div>", unsafe_allow_html=True)
                                with cc_:
                                    fm = go.Figure(data=[go.Scatter(x=ser.index, y=ser.values, mode='lines', line=dict(color=col,width=2), fill='tozeroy', fillcolor=fc)])
                                    ymx, ymn = ser.max(), ser.min(); ymg = (ymx-ymn)*0.1 if ymx!=ymn else lc*0.1
                                    xtf = '%Y/%m' if sp=="1y" else '%m/%d'
                                    fm.update_layout(plot_bgcolor='#12161E', paper_bgcolor='#12161E', margin=dict(l=45,r=10,t=10,b=30), height=180, xaxis=dict(showgrid=True,gridcolor='#2B3240',griddash='dot',tickformat=xtf,tickfont=dict(color='#9E9E9E',size=10)), yaxis=dict(showgrid=True,gridcolor='#2B3240',griddash='dot',side='left',tickformat=',',tickfont=dict(color='#9E9E9E',size=10),range=[ymn-ymg,ymx+ymg]), showlegend=False)
                                    st.plotly_chart(fm, use_container_width=True, config={'displayModeBar':False})
                            else:
                                with tc_: st.markdown(f"<p style='color:#BDBDBD;font-weight:bold'>{iname}</p><p style='color:#FF1744'>データ不足</p>", unsafe_allow_html=True)
                        else:
                            with tc_: st.markdown(f"<p style='color:#BDBDBD;font-weight:bold'>{iname}</p><p style='color:#FF1744'>取得失敗</p>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
