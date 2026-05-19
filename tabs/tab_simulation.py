"""TAB 4: シミュレーション"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from calc import get_future_simulation, simulate_withdrawal
from tabs import card


def _render_goal(TA, goal_amount, goal_oku, interest_rate, interest_rate_pct):
    st.markdown(f"#### 🎯 {goal_oku}億円ゴール 年間必要積立額 (年利{interest_rate_pct}%)")
    st.caption("サイドバーで目標・年利・積立額を変更できます。")
    yl = [10, 15, 20, 25, 30]; pm = []
    for y in yl:
        sf = goal_amount - (TA * ((1 + interest_rate) ** y))
        pm.append(sf / (((1 + interest_rate) ** y - 1) / interest_rate) if sf > 0 else 0)
    sdb = pd.DataFrame({"達成年数": [f"{y}年後" for y in yl], "年間積立額": pm})
    sdb["表示用金額"] = sdb["年間積立額"].apply(lambda x: f"{int(x):,}円" if x > 0 else "達成確実！")
    fb = px.bar(sdb, x="年間積立額", y="達成年数", orientation="h", text="表示用金額")
    fb.update_traces(textposition="auto", marker_color="#00D2FF")
    fb.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0", margin=dict(t=10, b=10), xaxis=dict(tickformat=",", ticksuffix="円"))
    st.plotly_chart(fb, width='stretch')


def _render_future(TA, interest_rate, yearly_add, goal_amount, goal_oku):
    st.markdown("#### 🚀 未来の資産推移 (サイドバー値ベース)")
    st.caption("サイドバーの現在資産・年利・積立額を使ったシミュレーション。")
    plf = st.select_slider("期間", ["1年後", "3年後", "5年後", "10年後", "20年後", "30年後"], value="10年後")
    ym = {"1年後": 1, "3年後": 3, "5年後": 5, "10年後": 10, "20年後": 20, "30年後": 30}
    sdl = get_future_simulation(TA, interest_rate, ym[plf], yearly_add)
    sdl["年"] = sdl["日時"].dt.year; yd = sdl.groupby("年").last().reset_index()
    by = yd["年"].iloc[0]; yd["経過年数"] = yd["年"].apply(lambda y: f"{y-by}年目" if y > by else "現在")

    ff = go.Figure()
    ff.add_trace(go.Bar(x=yd["経過年数"], y=yd["積立元本(円)"], name="積立元本", marker_color="#4A90D9"))
    ff.add_trace(go.Bar(x=yd["経過年数"], y=yd["運用益(円)"], name="運用益", marker_color="#00D2FF"))
    if goal_amount > 0:
        ff.add_trace(go.Scatter(x=[yd["経過年数"].iloc[0], yd["経過年数"].iloc[-1]], y=[goal_amount] * 2,
                                mode="lines", line=dict(color="#FF1744", width=2, dash="dash"), name=f"目標({goal_oku}億円)"))

    fv, fpv, fg = yd["予測評価額(円)"].iloc[-1], yd["積立元本(円)"].iloc[-1], yd["運用益(円)"].iloc[-1]
    f1, f2, f3 = st.columns(3)
    with f1: card("予測評価額", f"<span style='color:#00D2FF'>{fv:,.0f}<span>円</span></span>")
    with f2: card("積立元本", f"{fpv:,.0f}<span>円</span>")
    with f3: card("運用益", f"<span style='color:#00E676'>{fg:,.0f}<span>円</span></span>")

    ff.update_layout(barmode="stack", plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                     margin=dict(l=0, r=0, t=20, b=10), height=400,
                     xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#1E232F", tickformat=","),
                     legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
    st.plotly_chart(ff, width='stretch')


def _render_accumulation(TA):
    st.markdown("#### 💰 積立シミュレーター")
    st.caption("初期資産・月額積立・年利・期間を自由に設定。初期資産0なら純粋な積立シム。")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        ia = st.number_input("初期資産(円)", min_value=0, value=int(TA), step=100000, format="%d", key="acc_initial")
    with c2:
        ma = st.number_input("月額積立(円)", min_value=0, value=50000, step=10000, format="%d", key="acc_monthly")
    with c3:
        ar = st.number_input("年利(%)", min_value=-20.0, max_value=50.0, value=5.0, step=0.1, key="acc_rate")
    with c4:
        yrs = st.number_input("期間(年)", min_value=1, max_value=60, value=10, step=1, key="acc_years")

    sim = get_future_simulation(float(ia), ar / 100, int(yrs), float(ma) * 12)
    sim["年"] = sim["日時"].dt.year
    yd = sim.groupby("年").last().reset_index()
    by = yd["年"].iloc[0]
    yd["経過年数"] = yd["年"].apply(lambda y: f"{y-by}年目" if y > by else "現在")

    fv = yd["予測評価額(円)"].iloc[-1]
    fpv = yd["積立元本(円)"].iloc[-1]
    fg = yd["運用益(円)"].iloc[-1]
    contributed = float(ma) * 12 * int(yrs)

    k1, k2, k3, k4 = st.columns(4)
    with k1: card(f"{int(yrs)}年後の評価額", f"<span style='color:#00D2FF'>{fv:,.0f}<span>円</span></span>")
    with k2: card("元本合計", f"{fpv:,.0f}<span>円</span>", sub=f"初期 {int(ia):,} + 積立 {contributed:,.0f}")
    with k3: card("運用益", f"<span style='color:#00E676'>{fg:,.0f}<span>円</span></span>")
    with k4:
        roi = (fg / fpv * 100) if fpv > 0 else 0.0
        card("元本比リターン", f"<span style='color:#00E676'>+{roi:.1f}%</span>")

    fig = go.Figure()
    fig.add_trace(go.Bar(x=yd["経過年数"], y=yd["積立元本(円)"], name="元本", marker_color="#4A90D9"))
    fig.add_trace(go.Bar(x=yd["経過年数"], y=yd["運用益(円)"], name="運用益", marker_color="#00D2FF"))
    fig.update_layout(barmode="stack", plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                      margin=dict(l=0, r=0, t=20, b=10), height=380,
                      xaxis=dict(showgrid=False), yaxis=dict(showgrid=True, gridcolor="#1E232F", tickformat=",", ticksuffix="円"),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
    st.plotly_chart(fig, width='stretch')


def _render_withdrawal(TA):
    st.markdown("#### 🏔️ 取り崩しシミュレーター (4%ルール対応)")
    st.caption("リタイア後の資産寿命を試算。3モード切替: 固定額 / 残高比率 / インフレ調整。")

    mode_label = st.radio("取り崩しモード",
                         ["固定額 (インフレ調整なし)", "残高比率 (毎年残高の◯%)", "インフレ調整 (初年度額を毎年増額)"],
                         horizontal=True, key="wd_mode")
    mode = {"固定額 (インフレ調整なし)": "fixed",
            "残高比率 (毎年残高の◯%)": "rate",
            "インフレ調整 (初年度額を毎年増額)": "inflation"}[mode_label]

    c1, c2, c3 = st.columns(3)
    with c1:
        ia = st.number_input("初期資産(円)", min_value=0, value=int(TA) if TA > 0 else 30000000, step=1000000, format="%d", key="wd_initial")
    with c2:
        ar = st.number_input("年利(%)", min_value=-20.0, max_value=50.0, value=4.0, step=0.1, key="wd_rate")
    with c3:
        my = st.number_input("試算年数(上限)", min_value=5, max_value=60, value=40, step=5, key="wd_maxyears")

    w_amount = 0.0; w_rate = 0.0; inf_rate = 0.0
    if mode == "fixed":
        c4, _ = st.columns([1, 2])
        with c4:
            w_amount = st.number_input("年間取り崩し額(円)", min_value=0, value=int(ia * 0.04) if ia > 0 else 1200000, step=100000, format="%d", key="wd_amount_fixed")
    elif mode == "rate":
        c4, _ = st.columns([1, 2])
        with c4:
            w_rate = st.number_input("取り崩し率(%)", min_value=0.1, max_value=20.0, value=4.0, step=0.1, key="wd_rate_pct") / 100
    else:
        c4, c5 = st.columns(2)
        with c4:
            w_amount = st.number_input("初年度取り崩し額(円)", min_value=0, value=int(ia * 0.04) if ia > 0 else 1200000, step=100000, format="%d", key="wd_amount_inf")
        with c5:
            inf_rate = st.number_input("インフレ率(%)", min_value=0.0, max_value=20.0, value=2.0, step=0.1, key="wd_inflation") / 100

    sim = simulate_withdrawal(float(ia), ar / 100, mode,
                              annual_withdrawal=float(w_amount),
                              withdrawal_rate=float(w_rate),
                              inflation_rate=float(inf_rate),
                              max_years=int(my))

    depleted_rows = sim[sim["残高(円)"] <= 0]
    depleted_year = int(depleted_rows["年"].iloc[0]) if not depleted_rows.empty else None
    final_balance = float(sim["残高(円)"].iloc[-1])
    final_year = int(sim["年"].iloc[-1])
    total_withdrawn = float(sim["累計取崩(円)"].iloc[-1])

    k1, k2, k3 = st.columns(3)
    with k1:
        if depleted_year is not None:
            card("資産寿命", f"<span style='color:#FF5252'>{depleted_year}年</span>", sub="この年で枯渇")
        else:
            card("資産寿命", f"<span style='color:#00E676'>{final_year}年超</span>", sub=f"上限{int(my)}年内では枯渇せず")
    with k2:
        color = "#FF5252" if final_balance < ia * 0.5 else "#00E676"
        card(f"{final_year}年後残高", f"<span style='color:{color}'>{final_balance:,.0f}<span>円</span></span>")
    with k3:
        card("累計取り崩し", f"{total_withdrawn:,.0f}<span>円</span>")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sim["年"], y=sim["残高(円)"], mode="lines", name="残高", line=dict(color="#00D2FF", width=2.5), fill="tozeroy", fillcolor="rgba(0,210,255,0.15)"))
    fig.add_trace(go.Bar(x=sim["年"], y=sim["取り崩し額(円)"], name="年間取崩", marker_color="#FFA726", yaxis="y2", opacity=0.7))
    if depleted_year is not None:
        fig.add_vline(x=depleted_year, line=dict(color="#FF5252", width=2, dash="dash"), annotation_text=f"枯渇 ({depleted_year}年目)", annotation_position="top")
    fig.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                      margin=dict(l=0, r=0, t=20, b=10), height=400,
                      xaxis=dict(title="経過年数", showgrid=False),
                      yaxis=dict(title="残高(円)", showgrid=True, gridcolor="#1E232F", tickformat=","),
                      yaxis2=dict(title="取崩額(円)", overlaying="y", side="right", showgrid=False, tickformat=","),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
    st.plotly_chart(fig, width='stretch')

    with st.expander("年次データ"):
        disp = sim.copy()
        disp["残高(円)"] = disp["残高(円)"].apply(lambda v: f"{v:,.0f}")
        disp["取り崩し額(円)"] = disp["取り崩し額(円)"].apply(lambda v: f"{v:,.0f}")
        disp["累計取崩(円)"] = disp["累計取崩(円)"].apply(lambda v: f"{v:,.0f}")
        st.dataframe(disp, width='stretch', hide_index=True)


def render(tab, df, totals, goal_amount, goal_oku, interest_rate, interest_rate_pct, yearly_add):
    TA = totals["total_asset"]
    with tab:
        if df.empty or TA <= 0:
            st.info("銘柄を追加するとシミュレーションが表示されます。"); return

        sub_goal, sub_future, sub_acc, sub_wd = st.tabs([
            "🎯 ゴール逆算", "🚀 資産推移", "💰 積立シム", "🏔️ 取り崩しシム"
        ])
        with sub_goal:
            _render_goal(TA, goal_amount, goal_oku, interest_rate, interest_rate_pct)
        with sub_future:
            _render_future(TA, interest_rate, yearly_add, goal_amount, goal_oku)
        with sub_acc:
            _render_accumulation(TA)
        with sub_wd:
            _render_withdrawal(TA)
