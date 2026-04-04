"""TAB 4: シミュレーション"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from calc import get_future_simulation
from tabs import card


def render(tab, df, totals, goal_amount, goal_oku, interest_rate, interest_rate_pct, yearly_add):
    TA = totals["total_asset"]
    with tab:
        if df.empty or TA <= 0:
            st.info("銘柄を追加するとシミュレーションが表示されます。"); return

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

        st.markdown("---"); st.markdown("#### 🚀 未来の資産推移")
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
