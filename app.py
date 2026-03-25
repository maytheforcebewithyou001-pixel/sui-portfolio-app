"""
PORTFOLIO 資産管理 — メインUI
  config.py  定数・共通ヘルパー    | data.py    Google Sheets読み書き
  market.py  yfinance市場データ    | calc.py    損益・配当・税金計算
  style.py   CSS定義
"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

from config import BROKER_OPTIONS, TAX_OPTIONS, MARKET_OPTIONS, WORLD_INDICES
from data import (load_data, save_data, load_fund_prices, load_gas_prices, load_history,
                  save_history, load_ai_review, save_ai_review)
from market import get_cached_market_data, get_cached_ticker_info, get_ticker_name
from calc import (calculate_portfolio, get_portfolio_totals, get_future_simulation,
                  round_up_3, build_portfolio_summary_text)
from style import MAIN_CSS, ACCT_BADGE_MAP

st.set_page_config(page_title="FORCE CAPITAL", layout="wide", initial_sidebar_state="collapsed")
st.markdown(MAIN_CSS, unsafe_allow_html=True)

# ─── パスワード認証 ───
def check_password():
    """パスワード認証。正しければTrue、間違っていればFalse。"""
    if st.session_state.get("authenticated"):
        return True

    st.markdown("""
    <div style='display:flex;justify-content:center;align-items:center;min-height:60vh'>
      <div style='text-align:center'>
        <div style='margin-bottom:1rem'>
          <span style='color:rgba(255,255,255,0.35);font-family:Courier New,monospace;font-size:13px;letter-spacing:2px'>&lt;</span>
          <span style='color:#00D2FF;font-family:Courier New,monospace;font-size:24px;font-weight:700;letter-spacing:4px'>FORCE</span>
          <span style='color:rgba(255,255,255,0.35);font-family:Courier New,monospace;font-size:13px;letter-spacing:2px'>&gt;</span>
          <span style='color:rgba(255,255,255,0.18);font-family:monospace;font-size:10px;letter-spacing:2px;margin-left:4px'>CAPITAL</span>
        </div>
        <p style='color:rgba(255,255,255,0.4);font-size:0.85rem;margin-bottom:1.5rem'>アクセスにはパスワードが必要です</p>
      </div>
    </div>
    """, unsafe_allow_html=True)

    password = st.text_input("パスワード", type="password", key="pw_input")
    if st.button("ログイン", use_container_width=True):
        if password == st.secrets.get("app_password", ""):
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error("パスワードが正しくありません")
    return False

if not check_password():
    st.stop()

# ─── サイドバー ───
with st.sidebar:
    st.markdown("### ⚙️ 設定")
    goal_oku = st.slider("🎯 目標金額 (億円)", 0.5, 10.0, 1.2, 0.1)
    goal_amount = goal_oku * 1e8
    interest_rate_pct = st.slider("📈 想定年利 (%)", 1.0, 20.0, 6.0, 0.5)
    interest_rate = interest_rate_pct / 100.0
    yearly_add_man = st.number_input("💰 年間積立額 (万円)", min_value=0, value=120, step=10)
    yearly_add = yearly_add_man * 10000
    st.markdown("---")
    if st.button("🔄 全データ最新化", use_container_width=True):
        st.cache_data.clear()
        st.rerun()
    st.caption("左上の × で閉じる")

# ─── データ一括処理 ───
df = load_data()
fund_prices = load_fund_prices()
gas_prices = load_gas_prices()

if not df.empty:
    with st.spinner("市場データを取得中..."):
        tickers = ["JPY=X"]
        for _, row in df.iterrows():
            c, m = str(row["銘柄コード"]), row["市場"]
            if m == "日本株": tickers.append(f"{c}.T")
            elif m == "米国株": tickers.append(c)
        unique_tickers = tuple(sorted(set(tickers)))
        closes_df = get_cached_market_data(unique_tickers, period="1y")
        info_dict = get_cached_ticker_info(unique_tickers)
        if "JPY=X" in closes_df.columns:
            s = closes_df["JPY=X"].dropna()
            jpy_usd_rate = s.iloc[-1] if not s.empty else 150.0
        else:
            jpy_usd_rate = 150.0
        display_df = calculate_portfolio(df, closes_df, info_dict, fund_prices, jpy_usd_rate, gas_prices)
        totals = get_portfolio_totals(display_df)
else:
    totals = dict(total_asset=0, total_net_profit=0, total_dividend=0,
                  total_dividend_after_tax=0, total_fx_gain=0, total_stock_gain=0,
                  avg_dividend_yield=0.0, stock_count=0)
    jpy_usd_rate = 150.0
    display_df = pd.DataFrame()

TA = totals["total_asset"]
SC = totals["stock_count"]

# ─── Bloomberg Terminal ヘッダー ───
# 前回比の計算
prev_asset = prev_diff = prev_diff_pct = 0; prev_date_str = ""
try:
    _hdf = load_history()
    if not _hdf.empty:
        _hdf["総資産額(円)"] = pd.to_numeric(_hdf["総資産額(円)"], errors="coerce")
        prev_asset = _hdf["総資産額(円)"].iloc[-1]; prev_date_str = str(_hdf["日付"].iloc[-1])
        if prev_asset > 0 and TA > 0:
            prev_diff = TA - prev_asset; prev_diff_pct = (prev_diff / prev_asset) * 100
except Exception: pass

tnp = totals["total_net_profit"]
tda = totals["total_dividend_after_tax"]
prog = min(TA / goal_amount * 100, 100.0) if goal_amount > 0 else 100.0
pnl_color = "#00E676" if tnp >= 0 else "#FF5252"
pnl_sign = "+" if tnp >= 0 else ""
pnl_pct = (tnp / (TA - tnp) * 100) if (TA - tnp) > 0 else 0
now_str = datetime.now().strftime("%Y/%m/%d %H:%M")

# ティッカーバーのデータ（世界指標タブと同じソースから取得）
ticker_bar_html = ""
try:
    idx_closes = get_cached_market_data(tuple(sorted(["^N225", "^GSPC", "JPY=X", "^VIX"])), period="5d")
    _ticker_items = [("N225", "^N225"), ("SPX", "^GSPC"), ("USD/JPY", "JPY=X"), ("VIX", "^VIX")]
    for sym, tk in _ticker_items:
        if tk in idx_closes.columns:
            _s = idx_closes[tk].dropna()
            if len(_s) >= 2:
                _lc = _s.iloc[-1]; _pr = _s.iloc[-2]; _ch = ((_lc / _pr) - 1) * 100
                _chcls = "chg-up" if _ch >= 0 else "chg-dn"
                _chs = "+" if _ch >= 0 else ""
                ticker_bar_html += f"""<div class='term-ticker'><span class='sym'>{sym}</span><span class='val'>{_lc:,.1f}</span><span class='{_chcls}'>{_chs}{_ch:.1f}%</span></div><div class='term-sep'></div>"""
    if ticker_bar_html.endswith("<div class='term-sep'></div>"):
        ticker_bar_html = ticker_bar_html[:-len("<div class='term-sep'></div>")]
except Exception:
    ticker_bar_html = "<span style='color:rgba(255,255,255,0.3);font-size:11px'>指標読込中...</span>"

# 前回比HTML
prev_html = ""
if prev_asset > 0:
    _pc = "#00E676" if prev_diff >= 0 else "#FF5252"
    _ps = "+" if prev_diff >= 0 else ""
    prev_html = f"<span class='val-sm' style='color:{_pc};margin-left:8px'>{_ps}{prev_diff:,.0f} ({_ps}{prev_diff_pct:.1f}%) vs {prev_date_str}</span>"

st.markdown(f"""
<div class='term-header'>
  <div class='term-top'>
    <div class='term-logo'>
      <div class='dot'></div>
      <span class='bracket'>&lt;</span><span class='name'>FORCE</span><span class='bracket'>&gt;</span>
      <span class='sub'>CAPITAL</span>
    </div>
    <div class='term-ticker-bar'>{ticker_bar_html}</div>
    <div class='term-time'>
      <div class='live'>配信中</div>
      <div class='dt'>{now_str} JST</div>
    </div>
  </div>
  <div class='term-bottom'>
    <div class='term-metric'>
      <span class='label'>評価額</span>
      <span class='val-lg' style='color:#00D2FF'>¥{TA:,.0f}</span>
      {prev_html}
    </div>
    <div class='term-vsep'></div>
    <div class='term-metric'>
      <span class='label'>損益</span>
      <span class='val-md' style='color:{pnl_color}'>{pnl_sign}¥{abs(tnp):,.0f}</span>
      <span class='val-sm' style='color:{pnl_color}'>({pnl_sign}{pnl_pct:.1f}%)</span>
    </div>
    <div class='term-vsep'></div>
    <div class='term-metric'>
      <span class='label'>年間配当</span>
      <span class='val-md' style='color:#FFD54F'>¥{tda:,.0f}</span>
      <span class='val-sm' style='color:rgba(255,255,255,0.35)'>{totals["avg_dividend_yield"]:.2f}%</span>
    </div>
    <div class='term-vsep'></div>
    <div class='term-metric'>
      <span class='label'>銘柄</span>
      <span class='val-md' style='color:rgba(255,255,255,0.7)'>{SC}</span>
    </div>
    <div style='flex:1'></div>
    <div class='term-metric'>
      <span class='label'>目標</span>
      <div class='term-goal-bar'><div class='term-goal-fill' style='width:{prog:.1f}%'></div></div>
      <span class='val-sm' style='color:rgba(255,255,255,0.5)'>{prog:.1f}%</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# 記録ボタン（ヘッダー下にコンパクト配置）
_rec1, _rec2 = st.columns([5, 1])
with _rec2:
    if st.button("💾 記録", use_container_width=True) and TA > 0:
        save_history(datetime.now().strftime("%Y/%m/%d"), TA)
        st.toast("✓ 記録しました"); st.rerun()

# 為替損益サマリー
tfx, tsg = totals["total_fx_gain"], totals["total_stock_gain"]
if tfx != 0 or tsg != 0:
    fx1, fx2 = st.columns(2)
    with fx1:
        c = "#00E676" if tsg >= 0 else "#FF5252"; s = "+" if tsg >= 0 else ""
        st.markdown(f"<div class='status-card' style='padding:0.6rem;border-left:3px solid #00D2FF'><h4>米国株 株価損益</h4><p class='mv' style='font-size:1rem;color:{c}'>{s}{tsg:,.0f}<span>円</span></p><p class='sv'>株価の値動きによる損益</p></div>", unsafe_allow_html=True)
    with fx2:
        c = "#00E676" if tfx >= 0 else "#FF5252"; s = "+" if tfx >= 0 else ""
        st.markdown(f"<div class='status-card' style='padding:0.6rem;border-left:3px solid #FFD54F'><h4>米国株 為替損益</h4><p class='mv' style='font-size:1rem;color:{c}'>{s}{tfx:,.0f}<span>円</span></p><p class='sv'>為替変動（$1=¥{jpy_usd_rate:.1f}）による損益</p></div>", unsafe_allow_html=True)

# 大幅変動アラート
if not display_df.empty and "前日比" in display_df.columns:
    for _, mv in display_df[display_df["前日比"].apply(lambda x: abs(x) >= 3.0 if pd.notna(x) else False)].iterrows():
        d = mv["前日比"]; cls = "alert-up" if d > 0 else "alert-down"; arrow = "▲" if d > 0 else "▼"
        st.markdown(f"<div class='alert-bar {cls}'>{arrow} <b>{mv['銘柄名']}</b>（{mv['銘柄コード']}）が前日比 {d:+.2f}% の大幅変動</div>", unsafe_allow_html=True)

# ══════════════════════════════════════════
# メインタブ
# ══════════════════════════════════════════
tab_pf, tab_an, tab_div, tab_sim, tab_mkt, tab_ai = st.tabs(
    ["📊 ポートフォリオ", "🔍 分析", "💰 配当", "🚀 シミュレーション", "🌍 世界指標", "🤖 AI総評"])

# ── TAB 1: ポートフォリオ ──
with tab_pf:
    st.markdown("#### ➕ 銘柄を追加")
    # #4 st.formで囲み、submitまでyfinance呼び出しを抑制
    with st.form("add_stock_form", clear_on_submit=True):
        r1a, r1b, r1c = st.columns([1, 1, 2])
        with r1a: market = st.selectbox("市場", MARKET_OPTIONS, key="fm")
        with r1b: code = st.text_input("証券コード", placeholder="例: 7203", key="fc")
        with r1c: manual_name = st.text_input("銘柄名", key="fn", placeholder="自動取得 or 手動入力")
        r2a, r2b, r2c, r2d, r2e = st.columns(5)
        with r2a: shares = st.number_input("保有数", min_value=0.0001, value=100.0, key="fs")
        with r2b: avg_price = st.number_input("取得単価", min_value=0.0, value=0.0, key="fp")
        with r2c: annual_div = st.number_input("年間配当金(円/株)", min_value=0.0, value=0.0, step=1.0, key="fd")
        with r2d: broker = st.selectbox("口座", BROKER_OPTIONS, key="fb")
        with r2e: tax = st.selectbox("口座区分", TAX_OPTIONS, key="ft")
        r3a, r3b, _ = st.columns([1.5, 1.5, 2])
        # #6 配当月をmultiselectに変更（フリーテキストの入力ミスを防止）
        with r3a: div_month_sel = st.multiselect("配当月", options=list(range(1,13)),
                                                  format_func=lambda x: f"{x}月", key="fdm")
        with r3b: buy_fx = st.number_input("取得時為替 (米国株)", min_value=0.0, value=0.0, step=0.1, key="ffx")
        submitted = st.form_submit_button("＋ 追加", use_container_width=True)

    if submitted and code:
        # フォーム送信後にのみ銘柄名を取得（rerun抑制）
        auto_name = ""
        if not manual_name and market in ["日本株", "米国株"]:
            with st.spinner("銘柄名を取得中..."):
                auto_name = get_ticker_name(code, market)
        final_name = manual_name or auto_name or code
        div_months_str = ",".join(str(m) for m in sorted(div_month_sel))
        new = pd.DataFrame({"銘柄コード": [code], "銘柄名": [final_name], "市場": [market],
            "保有株数": [shares], "取得単価": [avg_price], "口座": [broker], "口座区分": [tax],
            "手動配当利回り(%)": [0.0], "配当月": [div_months_str], "年間配当金(円/株)": [annual_div],
            "取得時為替": [buy_fx], "最新更新日": [datetime.now().strftime("%Y/%m/%d %H:%M")]})
        save_data(pd.concat([df, new], ignore_index=True))
        st.cache_data.clear(); st.success(f"✓ {final_name} を追加"); st.rerun()

    # 口座別サマリー
    if not df.empty and not display_df.empty:
        st.markdown("---"); st.markdown("#### 🏦 口座別サマリー")
        if "口座" not in display_df.columns: display_df["口座"] = "SBI証券"
        if "口座区分" not in display_df.columns: display_df["口座区分"] = "特定口座"
        ag = display_df.groupby("口座").agg({"評価額(円)":"sum","税引後損益(円)":"sum","予想配当(円)":"sum","銘柄コード":"count"}).reset_index()
        cols = st.columns(min(len(ag), 3)) if len(ag) > 0 else []
        for i, (_, r) in enumerate(ag.iterrows()):
            with cols[i % len(cols)]:
                bc = ACCT_BADGE_MAP.get(r["口座"], "acct-other")
                pc = "#00E676" if r["税引後損益(円)"] >= 0 else "#FF5252"; ps = "+" if r["税引後損益(円)"] >= 0 else ""
                st.markdown(f"<div class='status-card' style='padding:0.8rem'><h4><span class='acct-badge {bc}'>{r['口座']}</span> {int(r['銘柄コード'])}銘柄</h4>"
                            f"<p class='mv' style='font-size:1.2rem'>{r['評価額(円)']:,.0f}<span>円</span></p>"
                            f"<p class='sv' style='color:{pc}'>{ps}{r['税引後損益(円)']:,.0f}円 · 配当 {r['予想配当(円)']:,.0f}円</p></div>", unsafe_allow_html=True)

        nisa = display_df[display_df["口座区分"].str.contains("NISA", na=False)]
        toku = display_df[~display_df["口座区分"].str.contains("NISA", na=False)]
        nc1, nc2 = st.columns(2)
        with nc1:
            nv = nisa["評価額(円)"].sum() if not nisa.empty else 0
            ng = nisa[nisa["口座区分"].str.contains("成長", na=False)]["評価額(円)"].sum()
            nt = nisa[nisa["口座区分"].str.contains("積立", na=False)]["評価額(円)"].sum()
            st.markdown(f"<div class='status-card' style='padding:0.7rem;border-left:3px solid #69F0AE'><h4>NISA合計（非課税）</h4>"
                        f"<p class='mv' style='font-size:1.1rem'>{nv:,.0f}<span>円</span></p>"
                        f"<p class='sv'>成長枠 {ng:,.0f}円 · 積立枠 {nt:,.0f}円 · {len(nisa)}銘柄</p></div>", unsafe_allow_html=True)
        with nc2:
            tv = toku["評価額(円)"].sum() if not toku.empty else 0
            st.markdown(f"<div class='status-card' style='padding:0.7rem;border-left:3px solid #FF8F00'><h4>特定口座合計（課税）</h4>"
                        f"<p class='mv' style='font-size:1.1rem'>{tv:,.0f}<span>円</span></p><p class='sv'>{len(toku)}銘柄</p></div>", unsafe_allow_html=True)

    # 保有一覧
    if not df.empty and not display_df.empty:
        st.markdown("---"); st.markdown("#### 📋 保有銘柄一覧")
        cpf = lambda v: f"color: {'#00E676' if v >= 0 else '#FF5252'}"
        cpc = lambda v: "" if pd.isna(v) else f"color: {'#00E676' if v > 0 else '#FF5252' if v < 0 else '#E0E0E0'}"
        fp = lambda v: "-" if pd.isna(v) else (f"+{v:.1f}%" if v > 0 else f"{v:.1f}%")
        show = ["銘柄コード","銘柄名","市場","口座","口座区分","保有株数","取得単価(円)","現在値(円)","前日比","評価額(円)","税引後損益(円)","予想配当(円)"]
        ac = [c for c in show if c in display_df.columns]
        fmt = {"保有株数": round_up_3, "取得単価(円)": round_up_3, "現在値(円)": round_up_3, "前日比": fp, "評価額(円)": "{:,.0f}", "税引後損益(円)": "{:,.0f}", "予想配当(円)": "{:,.0f}"}
        sdf = display_df[ac].style
        if "税引後損益(円)" in ac: sdf = sdf.map(cpf, subset=["税引後損益(円)"])
        if "前日比" in ac: sdf = sdf.map(cpc, subset=["前日比"])
        sdf = sdf.format({k: v for k, v in fmt.items() if k in ac})
        st.dataframe(sdf, width='stretch', hide_index=True)

        # CSV出力
        st.markdown("---"); st.markdown("#### 📥 データエクスポート")
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            csv_c = ["銘柄コード","銘柄名","市場","口座","口座区分","保有株数","取得単価(円)","現在値(円)","評価額(円)","含み損益(円)","税引後損益(円)","予想配当(円)","税引後配当(円)","セクター"]
            st.download_button("📋 保有銘柄一覧", display_df[[c for c in csv_c if c in display_df.columns]].to_csv(index=False).encode("utf-8-sig"),
                               f"portfolio_{datetime.now():%Y%m%d}.csv", "text/csv", use_container_width=True)
        with ec2:
            dr = [{"銘柄コード":r["銘柄コード"],"銘柄名":r["銘柄名"],"口座":r.get("口座",""),"口座区分":r.get("口座区分",""),
                   "予想配当(税引前)":round(r["予想配当(円)"]),"税引後配当":round(r.get("税引後配当(円)",0)),"配当月":r.get("配当月","")}
                  for _,r in display_df.iterrows() if r.get("予想配当(円)",0) > 0]
            if dr: st.download_button("💰 配当明細", pd.DataFrame(dr).to_csv(index=False).encode("utf-8-sig"), f"dividends_{datetime.now():%Y%m%d}.csv", "text/csv", use_container_width=True)
            else: st.button("💰 配当明細", disabled=True, use_container_width=True)
        with ec3:
            hdf = load_history()
            if not hdf.empty: st.download_button("📈 資産推移", hdf.to_csv(index=False).encode("utf-8-sig"), f"history_{datetime.now():%Y%m%d}.csv", "text/csv", use_container_width=True)
            else: st.button("📈 資産推移", disabled=True, use_container_width=True)

    # 修正・削除
    if not df.empty:
        with st.expander("✏️ 銘柄の修正・削除", expanded=False):
            edf = df.copy(); edf["削除"] = False
            edited = st.data_editor(edf, num_rows="dynamic", width='stretch', hide_index=True, column_config={
                "口座": st.column_config.SelectboxColumn("口座", options=BROKER_OPTIONS, required=True),
                "口座区分": st.column_config.SelectboxColumn("口座区分", options=TAX_OPTIONS, required=True),
                "市場": st.column_config.SelectboxColumn("市場", options=MARKET_OPTIONS, required=True),
                "保有株数": st.column_config.NumberColumn("保有株数", min_value=0, format="%.4f"),
                "取得単価": st.column_config.NumberColumn("取得単価", min_value=0, format="%.2f"),
                "手動配当利回り(%)": st.column_config.NumberColumn("手動利回り(%)", min_value=0, format="%.2f"),
                "年間配当金(円/株)": st.column_config.NumberColumn("年間配当(円/株)", min_value=0, format="%.2f"),
                "取得時為替": st.column_config.NumberColumn("取得時為替($/¥)", min_value=0, format="%.1f"),
                "削除": st.column_config.CheckboxColumn("削除", default=False)})
            if st.button("💾 変更を保存", key="sv"):
                save_data(edited[edited["削除"]==False].drop(columns=["削除"]))
                st.cache_data.clear(); st.success("更新しました！"); st.rerun()

    # 資産推移
    if TA > 0:
        st.markdown("---"); st.markdown("#### 📈 資産推移")
        hdf = load_history()
        if not hdf.empty:
            fig = px.line(hdf, x="日付", y="総資産額(円)", markers=True)
            fig.update_traces(line_color="#00E676", marker=dict(size=8, color="#FFFFFF"))
            fig.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                              margin=dict(t=10,b=10,l=10,r=10), height=300,
                              xaxis=dict(showgrid=True, gridcolor="#1E232F"), yaxis=dict(showgrid=True, gridcolor="#1E232F", tickformat=","))
            st.plotly_chart(fig, width='stretch')
        else:
            st.info("ヘッダーの「💾 本日の資産を記録」で記録を開始してください。")

# ── TAB 2: 分析 ──
with tab_an:
    if not df.empty and TA > 0 and not display_df.empty:
        display_df["円グラフ表示名"] = display_df["銘柄コード"].astype(str) + " " + display_df["銘柄名"].astype(str)
        st.markdown("#### 🍩 銘柄別割合")
        a1, a2 = st.columns([1.2, 1])
        with a1:
            f1 = px.pie(display_df, values="評価額(円)", names="円グラフ表示名", hole=0.4)
            f1.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0", showlegend=False, margin=dict(t=10,b=10))
            st.plotly_chart(f1, width='stretch')
        with a2:
            t1 = display_df[display_df["評価額(円)"]>0].groupby("円グラフ表示名",as_index=False)["評価額(円)"].sum().sort_values("評価額(円)",ascending=False)
            t1["割合"] = (t1["評価額(円)"]/TA*100).apply(lambda x: f"{x:.1f}%")
            t1["評価額(円)"] = t1["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            st.dataframe(t1.rename(columns={"円グラフ表示名":"銘柄"}), width='stretch', hide_index=True)

        st.markdown("---"); st.markdown("#### 🏢 セクター別割合")
        s1, s2 = st.columns([1.2, 1])
        with s1:
            f2 = px.pie(display_df, values="評価額(円)", names="セクター", hole=0.4)
            f2.update_traces(textposition="inside", textinfo="percent+label")
            f2.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0", showlegend=False, margin=dict(t=10,b=10))
            st.plotly_chart(f2, width='stretch')
        with s2:
            t2 = display_df[display_df["評価額(円)"]>0].groupby("セクター",as_index=False)["評価額(円)"].sum().sort_values("評価額(円)",ascending=False)
            t2["割合"] = (t2["評価額(円)"]/TA*100).apply(lambda x: f"{x:.1f}%")
            t2["評価額(円)"] = t2["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            st.dataframe(t2, width='stretch', hide_index=True)

        st.markdown("---"); st.markdown("#### 🗺️ ヒートマップ")
        st.caption("四角の大きさ＝評価額、色＝前日比。手動入力資産は除外。")
        tdf = display_df[(display_df["市場"].isin(["日本株","米国株"]))&(display_df["評価額(円)"]>0)].copy()
        if not tdf.empty:
            tdf["前日比(数値)"] = tdf["前日比"].apply(lambda x: x if pd.notna(x) else 0.0)
            tdf["Treemap Label"] = tdf["銘柄名"].astype(str)+"<br>"+tdf["前日比(数値)"].apply(lambda x: f"+{x:.2f}%" if x>0 else f"{x:.2f}%")
            ft = px.treemap(tdf, path=["市場","セクター","Treemap Label"], values="評価額(円)", color="前日比(数値)", color_continuous_scale="RdYlGn", color_continuous_midpoint=0)
            ft.update_layout(margin=dict(t=10,l=10,r=10,b=10), height=500, paper_bgcolor="#0A0E13")
            ft.data[0].textfont.color = "black"
            st.plotly_chart(ft, width='stretch')

        # リバランス
        st.markdown("---"); st.markdown("#### ⚖️ リバランス提案")
        sc = display_df[display_df["評価額(円)"]>0].groupby("セクター",as_index=False)["評価額(円)"].sum()
        sc["現在(%)"] = sc["評価額(円)"]/TA*100
        secs = sorted(sc["セクター"].tolist())
        if secs:
            with st.expander("🎯 目標配分を設定（%）", expanded=False):
                tp = {}; nc = min(len(secs), 4); tc = st.columns(nc)
                for i, sec in enumerate(secs):
                    cv = sc[sc["セクター"]==sec]["現在(%)"].values; cv = cv[0] if len(cv) else 0
                    with tc[i%nc]: tp[sec] = st.number_input(f"{sec}", 0.0, 100.0, round(cv,1), 1.0, key=f"t_{sec}")
                tt = sum(tp.values())
                if abs(tt-100)>0.5: st.warning(f"⚠ 目標合計: {tt:.1f}%")
                else: st.success(f"✓ 目標合計: {tt:.1f}%")
            rd = []
            for sec in secs:
                cv = sc[sc["セクター"]==sec]; cp = cv["現在(%)"].values[0] if len(cv) else 0; ca = cv["評価額(円)"].values[0] if len(cv) else 0
                tp_v = tp.get(sec,0); ta_v = TA*(tp_v/100)
                rd.append({"セクター":sec,"現在(%)":cp,"目標(%)":tp_v,"乖離(%)":cp-tp_v,"現在(円)":ca,"調整額(円)":ca-ta_v})
            rdf = pd.DataFrame(rd).sort_values("乖離(%)",key=abs,ascending=False)
            fr = go.Figure()
            for _,r in rdf.iterrows():
                cl = "#FF5252" if r["乖離(%)"]>1 else "#00E676" if r["乖離(%)"]<-1 else "#9E9E9E"
                fr.add_trace(go.Bar(x=[r["乖離(%)"]],y=[r["セクター"]],orientation="h",marker_color=cl,text=f"{r['乖離(%)']:+.1f}%",textposition="auto",showlegend=False))
            fr.update_layout(plot_bgcolor="#0A0E13",paper_bgcolor="#0A0E13",font_color="#E0E0E0",margin=dict(t=10,b=10,l=10,r=10),height=max(len(secs)*40,200),
                             xaxis=dict(title="乖離（%）",showgrid=True,gridcolor="#1E232F",zeroline=True,zerolinecolor="#4A5060"),yaxis=dict(showgrid=False))
            st.plotly_chart(fr, width='stretch')
            st.caption("🔴 比重オーバー / 🟢 比重不足 / 灰 適正範囲(±1%)")
            ha = rdf[abs(rdf["乖離(%)"])>1.0]
            if not ha.empty:
                st.markdown("##### 📋 調整アクション")
                for _,r in ha.iterrows():
                    a = r["調整額(円)"]
                    if a>0: st.markdown(f"<div class='alert-bar alert-down'>📉 <b>{r['セクター']}</b> 現在{r['現在(%)']:.1f}%→目標{r['目標(%)']:.1f}% <span style='color:#FF5252;font-weight:bold'>約¥{abs(a):,.0f}売却</span></div>",unsafe_allow_html=True)
                    else: st.markdown(f"<div class='alert-bar alert-up'>📈 <b>{r['セクター']}</b> 現在{r['現在(%)']:.1f}%→目標{r['目標(%)']:.1f}% <span style='color:#69F0AE;font-weight:bold'>約¥{abs(a):,.0f}買い増し</span></div>",unsafe_allow_html=True)
            else: st.success("✓ 全セクター±1%以内。リバランス不要。")
    else: st.info("銘柄を追加すると分析が表示されます。")

# ── TAB 3: 配当 ──
with tab_div:
    if not df.empty and TA > 0 and not display_df.empty:
        st.markdown("#### 💰 月別配当カレンダー")
        mdv = {m:0 for m in range(1,13)}; mda = {m:0 for m in range(1,13)}; mdt = {m:[] for m in range(1,13)}
        for _,row in display_df.iterrows():
            da, daa, dms = row.get("予想配当(円)",0), row.get("税引後配当(円)",0), str(row.get("配当月",""))
            if da > 0 and dms:
                try:
                    ml = [int(x.strip()) for x in dms.split(",") if x.strip().isdigit()]
                    p, pa = da/len(ml), daa/len(ml)
                    tl = "非課税" if "NISA" in str(row.get("口座区分","")) else "課税"
                    for m in ml:
                        if 1<=m<=12: mdv[m]+=p; mda[m]+=pa; mdt[m].append({"銘柄":f"{row['銘柄コード']} {row['銘柄名']}","税引前":p,"税引後":pa,"税区分":tl})
                except Exception: pass
        mn = [f"{m}月" for m in range(1,13)]
        for rs in range(0,12,4):
            cols = st.columns(4)
            for i in range(4):
                m = rs+i+1
                with cols[i]:
                    if mdv[m] > 0:
                        with st.popover(f"📅 {mn[m-1]}", use_container_width=True):
                            st.markdown(f"**{mn[m-1]}** 税引前:¥{mdv[m]:,.0f} → 手取り:¥{mda[m]:,.0f}")
                            for d in sorted(mdt[m],key=lambda x:x["税引前"],reverse=True):
                                tb = "🟢" if d["税区分"]=="非課税" else "🟡"
                                st.markdown(f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1E232F;font-size:0.85rem'>"
                                            f"<span style='color:#B0B8C0'>{tb} {d['銘柄']}</span><span style='color:#FFD54F;font-weight:bold'>¥{d['税引後']:,.0f}</span></div>",unsafe_allow_html=True)
                        st.markdown(f"<div style='text-align:center;margin-top:-8px;margin-bottom:8px'><span style='color:#FFD54F;font-weight:bold;font-size:0.9rem'>¥{mda[m]:,.0f}</span>"
                                    f"<span style='color:#7A8A9A;font-size:0.6rem;display:block'>手取り·{len(mdt[m])}銘柄</span></div>",unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div class='div-month div-month-empty'><span class='month-label'>{mn[m-1]}</span><span class='month-amount'>—</span></div>",unsafe_allow_html=True)
        st.markdown("---")
        tcd, tcda = sum(mdv.values()), sum(mda.values())
        if tcd > 0:
            dc1,dc2,dc3,dc4 = st.columns(4)
            with dc1: st.markdown(f"<div class='status-card' style='padding:0.7rem;border-left:3px solid #FFD54F'><h4>年間配当（税引前）</h4><p class='mv' style='font-size:1.1rem'>¥{tcd:,.0f}</p></div>",unsafe_allow_html=True)
            with dc2: st.markdown(f"<div class='status-card' style='padding:0.7rem;border-left:3px solid #69F0AE'><h4>年間手取り（税引後）</h4><p class='mv' style='font-size:1.1rem'>¥{tcda:,.0f}</p></div>",unsafe_allow_html=True)
            with dc3: st.markdown(f"<div class='status-card' style='padding:0.7rem;border-left:3px solid #00D2FF'><h4>月平均手取り</h4><p class='mv' style='font-size:1.1rem'>¥{tcda/12:,.0f}</p></div>",unsafe_allow_html=True)
            with dc4:
                am = sum(1 for v in mdv.values() if v>0)
                st.markdown(f"<div class='status-card' style='padding:0.7rem;border-left:3px solid #BD93F9'><h4>配当発生月</h4><p class='mv' style='font-size:1.1rem'>{am}<span>/12ヶ月</span></p></div>",unsafe_allow_html=True)
        st.markdown("---"); st.markdown("#### 🏆 配当金ランキング")
        drank = display_df[display_df["予想配当(円)"]>0][["銘柄コード","銘柄名","予想配当(円)","手動配当利回り(%)"]].sort_values("予想配当(円)",ascending=False).head(10)
        if not drank.empty:
            drank["予想配当(円)"] = drank["予想配当(円)"].apply(lambda x: f"¥{int(x):,}")
            drank["手動配当利回り(%)"] = drank["手動配当利回り(%)"].apply(lambda x: f"{x:.2f}%" if x>0 else "自動")
            st.dataframe(drank, width='stretch', hide_index=True)
    else: st.info("銘柄を追加すると配当カレンダーが表示されます。")

# ── TAB 4: シミュレーション ──
with tab_sim:
    if not df.empty and TA > 0:
        st.markdown(f"#### 🎯 {goal_oku}億円ゴール 年間必要積立額 (年利{interest_rate_pct}%)")
        st.caption("サイドバーで目標・年利・積立額を変更できます。")
        yl = [10,15,20,25,30]; pm = []
        for y in yl:
            sf = goal_amount - (TA*((1+interest_rate)**y))
            pm.append(sf/(((1+interest_rate)**y-1)/interest_rate) if sf>0 else 0)
        sdb = pd.DataFrame({"達成年数":[f"{y}年後" for y in yl],"年間積立額":pm})
        sdb["表示用金額"] = sdb["年間積立額"].apply(lambda x: f"{int(x):,}円" if x>0 else "達成確実！")
        fb = px.bar(sdb, x="年間積立額", y="達成年数", orientation="h", text="表示用金額")
        fb.update_traces(textposition="auto", marker_color="#00D2FF")
        fb.update_layout(plot_bgcolor="#0A0E13",paper_bgcolor="#0A0E13",font_color="#E0E0E0",margin=dict(t=10,b=10),xaxis=dict(tickformat=",",ticksuffix="円"))
        st.plotly_chart(fb, width='stretch')
        st.markdown("---"); st.markdown("#### 🚀 未来の資産推移")
        plf = st.select_slider("期間",["1年後","3年後","5年後","10年後","20年後","30年後"],value="10年後")
        ym = {"1年後":1,"3年後":3,"5年後":5,"10年後":10,"20年後":20,"30年後":30}
        sdl = get_future_simulation(TA, interest_rate, ym[plf], yearly_add)
        sdl["年"] = sdl["日時"].dt.year; yd = sdl.groupby("年").last().reset_index()
        by = yd["年"].iloc[0]; yd["経過年数"] = yd["年"].apply(lambda y: f"{y-by}年目" if y>by else "現在")
        ff = go.Figure()
        ff.add_trace(go.Bar(x=yd["経過年数"],y=yd["積立元本(円)"],name="積立元本",marker_color="#4A90D9"))
        ff.add_trace(go.Bar(x=yd["経過年数"],y=yd["運用益(円)"],name="運用益",marker_color="#00D2FF"))
        if goal_amount>0: ff.add_trace(go.Scatter(x=[yd["経過年数"].iloc[0],yd["経過年数"].iloc[-1]],y=[goal_amount]*2,mode="lines",line=dict(color="#FF1744",width=2,dash="dash"),name=f"目標({goal_oku}億円)"))
        fv,fpv,fg = yd["予測評価額(円)"].iloc[-1],yd["積立元本(円)"].iloc[-1],yd["運用益(円)"].iloc[-1]
        f1,f2,f3 = st.columns(3)
        with f1: st.markdown(f"<div class='status-card'><h4>予測評価額</h4><p class='mv' style='color:#00D2FF'>{fv:,.0f}<span>円</span></p></div>",unsafe_allow_html=True)
        with f2: st.markdown(f"<div class='status-card'><h4>積立元本</h4><p class='mv'>{fpv:,.0f}<span>円</span></p></div>",unsafe_allow_html=True)
        with f3: st.markdown(f"<div class='status-card'><h4>運用益</h4><p class='mv' style='color:#00E676'>{fg:,.0f}<span>円</span></p></div>",unsafe_allow_html=True)
        ff.update_layout(barmode="stack",plot_bgcolor="#0A0E13",paper_bgcolor="#0A0E13",font_color="#E0E0E0",margin=dict(l=0,r=0,t=20,b=10),height=400,
                         xaxis=dict(showgrid=False),yaxis=dict(showgrid=True,gridcolor="#1E232F",tickformat=","),
                         legend=dict(yanchor="top",y=0.99,xanchor="left",x=0.01,bgcolor="rgba(0,0,0,0)"))
        st.plotly_chart(ff, width='stretch')
    else: st.info("銘柄を追加するとシミュレーションが表示されます。")

# ── TAB 5: 世界指標 ──
with tab_mkt:
    m1,m2 = st.columns([3,1])
    with m1: pil = st.selectbox("チャート期間",["1週間","1ヶ月","3ヶ月","1年"],index=1,key="ip")
    with m2:
        st.markdown("<div style='height:8px'></div>",unsafe_allow_html=True)
        if st.button("🔄 指標を更新",use_container_width=True,key="rm"): get_cached_market_data.clear(); st.rerun()
    sp = {"1週間":"5d","1ヶ月":"1mo","3ヶ月":"3mo","1年":"1y"}[pil]
    with st.spinner("指標データを取得中..."):
        ic = get_cached_market_data(tuple(sorted(WORLD_INDICES.values())), period=sp)
        items = list(WORLD_INDICES.items())
        for i in range(0,len(items),2):
            rc = st.columns(2)
            for j in range(2):
                if i+j < len(items):
                    iname,tk = items[i+j]
                    with rc[j]:
                        st.markdown("<div class='indicator-card'>",unsafe_allow_html=True)
                        tc_,cc_ = st.columns([1,1.5])
                        if tk in ic.columns:
                            ser = ic[tk].dropna()
                            if len(ser)>=2:
                                lc=ser.iloc[-1];prc=ser.iloc[-2];pch=(lc/prc-1)*100;dif=lc-prc
                                col="#00E676" if pch>=0 else "#FF5252"; fc="rgba(0,230,118,0.15)" if pch>=0 else "rgba(255,82,82,0.15)"; sgn="+" if pch>=0 else ""
                                with tc_: st.markdown(f"<div style='display:flex;flex-direction:column;justify-content:center;height:150px'><p style='color:#B0B8C0;margin:0;font-size:14px;font-weight:bold'>{iname}</p><p style='color:#FFF;margin:5px 0 0;font-size:1.4rem;font-weight:bold'>{lc:,.2f}</p><p style='color:{col};margin:0 0 5px;font-size:13px;font-weight:bold'>{sgn}{dif:,.2f}<br>({sgn}{pch:.2f}%)</p></div>",unsafe_allow_html=True)
                                with cc_:
                                    fm=go.Figure(data=[go.Scatter(x=ser.index,y=ser.values,mode="lines",line=dict(color=col,width=2),fill="tozeroy",fillcolor=fc)])
                                    ymx,ymn=ser.max(),ser.min(); ymg=(ymx-ymn)*0.1 if ymx!=ymn else lc*0.1
                                    xtf="%Y/%m" if sp=="1y" else "%m/%d"
                                    fm.update_layout(plot_bgcolor="#12161E",paper_bgcolor="#12161E",margin=dict(l=45,r=10,t=10,b=30),height=180,
                                        xaxis=dict(showgrid=True,gridcolor="#2B3240",griddash="dot",tickformat=xtf,tickfont=dict(color="#9E9E9E",size=10)),
                                        yaxis=dict(showgrid=True,gridcolor="#2B3240",griddash="dot",tickformat=",",tickfont=dict(color="#9E9E9E",size=10),range=[ymn-ymg,ymx+ymg]),showlegend=False)
                                    st.plotly_chart(fm,use_container_width=True,config={"displayModeBar":False})
                            else:
                                with tc_: st.markdown(f"<p style='color:#B0B8C0;font-weight:bold'>{iname}</p><p style='color:#FF5252'>データ不足</p>",unsafe_allow_html=True)
                        else:
                            with tc_: st.markdown(f"<p style='color:#B0B8C0;font-weight:bold'>{iname}</p><p style='color:#FF5252'>取得失敗</p>",unsafe_allow_html=True)
                        st.markdown("</div>",unsafe_allow_html=True)

# ── TAB 6: AI総評 ──
with tab_ai:
    st.markdown("#### 🤖 Claudeによるポートフォリオ総評")
    if not df.empty and TA > 0 and not display_df.empty:
        api_key = st.secrets.get("anthropic_api_key","")
        if not api_key:
            st.warning("⚠ Streamlit Secretsに `anthropic_api_key` を設定してください。")
        else:
            ptxt = build_portfolio_summary_text(display_df, totals, jpy_usd_rate, history_df=load_history())
            for k,v in [("ai_review_dt",None),("ai_review_text",""),("ai_review_loaded",False),("ai_confirm_regen",False)]:
                if k not in st.session_state: st.session_state[k] = v
            if not st.session_state.ai_review_loaded:
                try: d,t = load_ai_review(); st.session_state.ai_review_dt=d; st.session_state.ai_review_text=t
                except Exception: pass
                st.session_state.ai_review_loaded = True
            sdt, stx = st.session_state.ai_review_dt, st.session_state.ai_review_text
            if stx and sdt:
                try:
                    sd = datetime.strptime(sdt,"%Y/%m/%d %H:%M"); ha = (datetime.now()-sd).total_seconds()/3600
                    tl = f"{ha:.1f}時間前" if ha<48 else f"{ha/24:.0f}日前"
                except Exception: tl = ""
                st.markdown(f"<div style='background:#12161E;border:1px solid #1E232F;border-radius:12px;padding:1.5rem;border-left:3px solid #00D2FF'>"
                            f"<div style='color:#00D2FF;font-weight:700;margin-bottom:0.8rem'>🤖 Claude分析レポート</div>"
                            f"<div style='color:#B0B8C0;font-size:0.75rem;margin-bottom:1rem'>{sdt}時点（{tl}）</div></div>",unsafe_allow_html=True)
                st.markdown(stx); st.caption("⚠ AIによる参考情報。投資助言ではありません。"); st.markdown("---")
            need_confirm = False
            if sdt:
                try:
                    sd = datetime.strptime(sdt,"%Y/%m/%d %H:%M")
                    if (datetime.now()-sd).total_seconds()<86400: need_confirm=True
                except Exception: pass
            if need_confirm and not st.session_state.ai_confirm_regen:
                ha = (datetime.now()-sd).total_seconds()/3600
                st.info(f"⏱ {ha:.1f}時間前に生成済み。再生成でAPIクレジット消費。")
                if st.button("🔄 それでも再生成する",use_container_width=True,key="aic"):
                    st.session_state.ai_confirm_regen=True; st.rerun()
            else:
                bl = "🔄 再生成" if stx else "📝 AI総評を生成"
                if st.button(bl,use_container_width=True,key="aig"):
                    st.session_state.ai_confirm_regen = False
                    with st.spinner("Claudeが分析中...（20〜30秒）"):
                        try:
                            import requests as req
                            prompt = f"""あなたは日本の個人投資家向けポートフォリオアドバイザーです。以下を分析し日本語でレポートを作成。
{ptxt}
5つの観点で分析: 1.全体評価(5段階) 2.強みと弱み 3.市場環境との整合性 4.配当戦略の評価 5.アクション提案(3〜5つ,優先度付き)
注意: 投資助言ではなく参考情報です。"""
                            resp = req.post("https://api.anthropic.com/v1/messages",
                                headers={"Content-Type":"application/json","x-api-key":api_key,"anthropic-version":"2023-06-01"},
                                json={"model":"claude-sonnet-4-20250514","max_tokens":2000,"messages":[{"role":"user","content":prompt}]},timeout=60)
                            if resp.status_code == 200:
                                ai_text = "".join(b["text"] for b in resp.json()["content"] if b["type"]=="text")
                                ns = datetime.now().strftime("%Y/%m/%d %H:%M")
                                st.session_state.ai_review_dt=ns; st.session_state.ai_review_text=ai_text
                                save_ai_review(ns,ai_text); st.rerun()
                            else: st.error(f"API エラー (HTTP {resp.status_code}): {resp.json().get('error',{}).get('message',resp.text)}")
                        except Exception as e: st.error(f"エラー: {e}")
            with st.expander("📄 送信データプレビュー",expanded=False): st.code(ptxt,language="text")
    else: st.info("銘柄を追加するとAI総評を利用できます。")
