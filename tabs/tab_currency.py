"""TAB: 通貨配分ダッシュボード"""
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from tabs import colored_card, pnl_color, pnl_sign

CCY_COLORS = {"JPY": "#00D2FF", "USD": "#FFD54F", "その他": "#B0B8C0"}


def render(tab, df, display_df, totals, jpy_usd_rate):
    TA = totals["total_asset"]
    with tab:
        if df.empty or TA <= 0 or display_df.empty:
            st.info("銘柄を追加すると通貨配分が表示されます。")
            return

        cdf = display_df.copy()
        if "通貨" not in cdf.columns:
            cdf["通貨"] = "JPY"
        cdf.loc[cdf["通貨"].isin(["", "-", "nan"]), "通貨"] = "JPY"

        ccy_agg = cdf.groupby("通貨").agg(
            評価額=("評価額(円)", "sum"),
            損益=("税引後損益(円)", "sum"),
            配当=("予想配当(円)", "sum"),
            銘柄数=("銘柄コード", "count"),
        ).reset_index().sort_values("評価額", ascending=False)

        # ── 通貨別サマリー ──
        st.markdown("#### 💱 通貨配分サマリー")
        cols = st.columns(max(len(ccy_agg), 1))
        for idx, (_, r) in enumerate(ccy_agg.iterrows()):
            ccy = r["通貨"]
            pct = r["評価額"] / TA * 100
            color = CCY_COLORS.get(ccy, "#B0B8C0")
            pc = pnl_color(r["損益"]); ps = pnl_sign(r["損益"])
            with cols[idx % len(cols)]:
                st.markdown(
                    f"<div class='status-card' style='padding:0.8rem;border-left:3px solid {color}'>"
                    f"<h4>{ccy} 建て資産</h4>"
                    f"<p class='mv' style='font-size:1.3rem;color:{color}'>"
                    f"{r['評価額']:,.0f}<span>円</span></p>"
                    f"<p class='sv' style='font-size:1rem'>{pct:.1f}% · {int(r['銘柄数'])}銘柄</p>"
                    f"<p class='sv' style='color:{pc}'>"
                    f"損益 {ps}{r['損益']:,.0f}円 · 配当 {r['配当']:,.0f}円</p>"
                    f"</div>", unsafe_allow_html=True)

        # ── ドーナツチャート + 内訳テーブル ──
        st.markdown("---")
        c1, c2 = st.columns([1.2, 1])
        with c1:
            st.markdown("#### 🥧 通貨配分チャート")
            fig = px.pie(ccy_agg, values="評価額", names="通貨", hole=0.5,
                         color="通貨", color_discrete_map=CCY_COLORS)
            fig.update_traces(textposition="inside", textinfo="percent+label",
                              textfont_size=14)
            fig.update_layout(
                plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13",
                font_color="#E0E0E0", showlegend=False,
                margin=dict(t=10, b=10, l=10, r=10), height=350,
                annotations=[dict(text=f"¥{TA:,.0f}", x=0.5, y=0.5,
                                  font_size=16, font_color="#E0E0E0",
                                  showarrow=False)],
            )
            st.plotly_chart(fig, use_container_width=True)
        with c2:
            st.markdown("#### 📋 通貨別内訳")
            tbl = ccy_agg.copy()
            tbl["割合"] = (tbl["評価額"] / TA * 100).apply(lambda x: f"{x:.1f}%")
            tbl["評価額"] = tbl["評価額"].apply(lambda x: f"{int(x):,}円")
            tbl["損益"] = tbl["損益"].apply(lambda x: f"{x:+,.0f}円")
            tbl["配当"] = tbl["配当"].apply(lambda x: f"{int(x):,}円")
            st.dataframe(
                tbl[["通貨", "評価額", "割合", "損益", "配当", "銘柄数"]],
                width="stretch", hide_index=True)
            st.markdown(
                f"<div class='status-card' style='padding:0.6rem'>"
                f"<h4>現在の為替レート</h4>"
                f"<p class='mv' style='font-size:1.2rem'>$1 = ¥{jpy_usd_rate:.2f}</p>"
                f"</div>", unsafe_allow_html=True)

        # ── 通貨別保有銘柄 ──
        st.markdown("---"); st.markdown("#### 📋 通貨別 保有銘柄")
        for ccy in ccy_agg["通貨"].tolist():
            subset = cdf[cdf["通貨"] == ccy]
            ccy_val = subset["評価額(円)"].sum()
            with st.expander(
                f"💰 {ccy} — {ccy_val:,.0f}円 "
                f"({ccy_val / TA * 100:.1f}%) · {len(subset)}銘柄"
            ):
                show_cols = [
                    "銘柄コード", "銘柄名", "市場", "口座",
                    "保有株数", "評価額(円)", "税引後損益(円)", "実質利回り(%)",
                ]
                ac = [c for c in show_cols if c in subset.columns]
                show = subset[ac].sort_values("評価額(円)", ascending=False)
                fmt = {
                    "保有株数": "{:,.4g}", "評価額(円)": "{:,.0f}",
                    "税引後損益(円)": "{:+,.0f}", "実質利回り(%)": "{:.2f}%",
                }
                st.dataframe(
                    show.style.format({k: v for k, v in fmt.items() if k in ac}),
                    width="stretch", hide_index=True)

        # ── 為替感応度分析 ──
        usd_total = cdf[cdf["通貨"] == "USD"]["評価額(円)"].sum()
        if usd_total <= 0:
            return
        st.markdown("---"); st.markdown("#### 📊 為替感応度分析")
        st.caption(
            "USD/JPY が変動した場合のポートフォリオ評価額への影響"
            "（USD建て資産のみ対象）"
        )
        scenarios = [-10, -5, -3, -1, 0, 1, 3, 5, 10]
        rows = []
        for pct in scenarios:
            new_rate = jpy_usd_rate * (1 + pct / 100)
            impact = usd_total * (pct / 100)
            rows.append({
                "変動幅": f"{pct:+d}%",
                "想定レート": f"¥{new_rate:.1f}",
                "USD資産変動": impact,
                "評価額": TA + impact,
                "全体変動率": (impact / TA) * 100,
            })

        colors = [
            "#FF5252" if r["USD資産変動"] < 0
            else "#00E676" if r["USD資産変動"] > 0
            else "#9E9E9E"
            for r in rows
        ]
        fig_fx = go.Figure()
        fig_fx.add_trace(go.Bar(
            x=[r["変動幅"] for r in rows],
            y=[r["USD資産変動"] for r in rows],
            marker_color=colors,
            text=[f"{r['USD資産変動']:+,.0f}円" for r in rows],
            textposition="outside",
        ))
        fig_fx.update_layout(
            plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13",
            font_color="#E0E0E0", showlegend=False,
            margin=dict(t=30, b=10, l=10, r=10), height=320,
            xaxis=dict(title="USD/JPY 変動幅", showgrid=False),
            yaxis=dict(title="評価額への影響(円)", showgrid=True,
                       gridcolor="#1E232F", tickformat=","),
        )
        st.plotly_chart(fig_fx, use_container_width=True)

        fx_df = pd.DataFrame(rows)
        fx_df["USD資産変動"] = fx_df["USD資産変動"].apply(lambda x: f"{x:+,.0f}円")
        fx_df["評価額"] = fx_df["評価額"].apply(lambda x: f"{x:,.0f}円")
        fx_df["全体変動率"] = fx_df["全体変動率"].apply(lambda x: f"{x:+.2f}%")
        st.dataframe(fx_df, width="stretch", hide_index=True)
