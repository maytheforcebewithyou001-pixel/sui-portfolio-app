"""TAB 2: 分析"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from config import (NISA_GROWTH_ANNUAL, NISA_GROWTH_LIFETIME,
                    NISA_TSUMITATE_ANNUAL, NISA_TSUMITATE_LIFETIME, NISA_TOTAL_LIFETIME)
from tabs import colored_card, alert_bar


def _nisa_bar(label, val, limit, color, annual_limit):
    pct = min(val / limit * 100, 100)
    rem = max(limit - val, 0)
    rem_y = max(annual_limit - val, 0)
    st.markdown(f"""<div class='status-card' style='padding:0.8rem;border-left:3px solid {color}'>
        <h4>{label}</h4>
        <p class='mv' style='font-size:1.1rem;color:{color}'>{val:,.0f}<span>円</span></p>
        <p class='sv'>生涯上限 {limit/1e4:,.0f}万 → 残 {rem:,.0f}円 ({100-pct:.1f}%)</p>
        <div style='background:#1E232F;border-radius:4px;height:6px;margin-top:6px'>
          <div style='height:100%;border-radius:4px;background:{color};width:{pct:.1f}%'></div></div>
        <p class='sv' style='margin-top:4px'>年間上限 {annual_limit/1e4:,.0f}万 → 今年の残枠概算 {rem_y:,.0f}円</p>
    </div>""", unsafe_allow_html=True)


def render(tab, df, display_df, totals):
    TA = totals["total_asset"]
    with tab:
        if df.empty or TA <= 0 or display_df.empty:
            st.info("銘柄を追加すると分析が表示されます。"); return

        display_df["円グラフ表示名"] = display_df["銘柄コード"].astype(str) + " " + display_df["銘柄名"].astype(str)

        # ── NISA 枠管理（投資元本ベース） ──
        st.markdown("#### 🌿 NISA 枠残高（投資元本ベース）")
        # NISA枠は投資元本（取得金額）で管理される
        if "取得単価" in display_df.columns and "保有株数" in display_df.columns:
            display_df["取得金額"] = display_df["取得単価"].astype(float) * display_df["保有株数"].astype(float)
            nisa_g = display_df[display_df["口座区分"].str.contains("成長", na=False)]["取得金額"].sum()
            nisa_t = display_df[display_df["口座区分"].str.contains("積立", na=False)]["取得金額"].sum()
        else:
            nisa_g = display_df[display_df["口座区分"].str.contains("成長", na=False)]["評価額(円)"].sum()
            nisa_t = display_df[display_df["口座区分"].str.contains("積立", na=False)]["評価額(円)"].sum()
        nc_a, nc_b, nc_c = st.columns(3)
        with nc_a: _nisa_bar("成長投資枠", nisa_g, NISA_GROWTH_LIFETIME, "#00E676", NISA_GROWTH_ANNUAL)
        with nc_b: _nisa_bar("積立投資枠", nisa_t, NISA_TSUMITATE_LIFETIME, "#69F0AE", NISA_TSUMITATE_ANNUAL)
        with nc_c:
            total = nisa_g + nisa_t; pct = min(total / NISA_TOTAL_LIFETIME * 100, 100)
            st.markdown(f"""<div class='status-card' style='padding:0.8rem;border-left:3px solid #00D2FF'>
                <h4>NISA 合計</h4>
                <p class='mv' style='font-size:1.1rem;color:#00D2FF'>{total:,.0f}<span>円</span></p>
                <p class='sv'>生涯上限 1,800万 → 残 {max(NISA_TOTAL_LIFETIME-total,0):,.0f}円 ({100-pct:.1f}%)</p>
                <div style='background:#1E232F;border-radius:4px;height:6px;margin-top:6px'>
                  <div style='height:100%;border-radius:4px;background:linear-gradient(90deg,#00D2FF,#00E676);width:{pct:.1f}%'></div></div>
                <p class='sv' style='margin-top:4px'>※投資元本（取得単価×保有数）ベースで算出。</p>
            </div>""", unsafe_allow_html=True)

        # ── 銘柄構成 ──
        st.markdown("---")
        a1, a2 = st.columns([1.2, 1])
        with a1:
            f1 = px.pie(display_df, values="評価額(円)", names="円グラフ表示名", hole=0.4)
            f1.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0", showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(f1, width='stretch')
        with a2:
            t1 = display_df[display_df["評価額(円)"] > 0].groupby("円グラフ表示名", as_index=False)["評価額(円)"].sum().sort_values("評価額(円)", ascending=False)
            t1["割合"] = (t1["評価額(円)"] / TA * 100).apply(lambda x: f"{x:.1f}%")
            t1["評価額(円)"] = t1["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            st.dataframe(t1.rename(columns={"円グラフ表示名": "銘柄"}), width='stretch', hide_index=True)

        # ── セクター別 ──
        st.markdown("---"); st.markdown("#### 🏢 セクター別割合")
        s1, s2 = st.columns([1.2, 1])
        with s1:
            f2 = px.pie(display_df, values="評価額(円)", names="セクター", hole=0.4)
            f2.update_traces(textposition="inside", textinfo="percent+label")
            f2.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0", showlegend=False, margin=dict(t=10, b=10))
            st.plotly_chart(f2, width='stretch')
        with s2:
            t2 = display_df[display_df["評価額(円)"] > 0].groupby("セクター", as_index=False)["評価額(円)"].sum().sort_values("評価額(円)", ascending=False)
            t2["割合"] = (t2["評価額(円)"] / TA * 100).apply(lambda x: f"{x:.1f}%")
            t2["評価額(円)"] = t2["評価額(円)"].apply(lambda x: f"{int(x):,}円")
            st.dataframe(t2, width='stretch', hide_index=True)

        # ── ヒートマップ ──
        st.markdown("---"); st.markdown("#### 🗺️ ヒートマップ")
        st.caption("四角の大きさ＝評価額、色＝前日比。手動入力資産は除外。")
        tdf = display_df[(display_df["市場"].isin(["日本株", "米国株"])) & (display_df["評価額(円)"] > 0)].copy()
        if not tdf.empty:
            tdf["前日比(数値)"] = tdf["前日比"].apply(lambda x: x if pd.notna(x) else 0.0)
            tdf["Treemap Label"] = tdf["銘柄名"].astype(str) + "<br>" + tdf["前日比(数値)"].apply(lambda x: f"+{x:.2f}%" if x > 0 else f"{x:.2f}%")
            ft = px.treemap(tdf, path=["市場", "セクター", "Treemap Label"], values="評価額(円)", color="前日比(数値)", color_continuous_scale="RdYlGn", color_continuous_midpoint=0)
            ft.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=500, paper_bgcolor="#0A0E13")
            ft.data[0].textfont.color = "black"
            st.plotly_chart(ft, width='stretch')

        # ── リバランス ──
        st.markdown("---"); st.markdown("#### ⚖️ リバランス提案")
        sc = display_df[display_df["評価額(円)"] > 0].groupby("セクター", as_index=False)["評価額(円)"].sum()
        sc["現在(%)"] = sc["評価額(円)"] / TA * 100
        secs = sorted(sc["セクター"].tolist())
        if not secs: return
        with st.expander("🎯 目標配分を設定（%）", expanded=False):
            tp = {}; nc = min(len(secs), 4); tc = st.columns(nc)
            for i, sec in enumerate(secs):
                cv = sc[sc["セクター"] == sec]["現在(%)"].values; cv = cv[0] if len(cv) else 0
                with tc[i % nc]: tp[sec] = st.number_input(f"{sec}", 0.0, 100.0, round(cv, 1), 1.0, key=f"t_{sec}")
            tt = sum(tp.values())
            if abs(tt - 100) > 0.5: st.warning(f"⚠ 目標合計: {tt:.1f}%")
            else: st.success(f"✓ 目標合計: {tt:.1f}%")

        rd = []
        for sec in secs:
            cv = sc[sc["セクター"] == sec]; cp = cv["現在(%)"].values[0] if len(cv) else 0; ca = cv["評価額(円)"].values[0] if len(cv) else 0
            tp_v = tp.get(sec, 0); ta_v = TA * (tp_v / 100)
            rd.append({"セクター": sec, "現在(%)": cp, "目標(%)": tp_v, "乖離(%)": cp - tp_v, "現在(円)": ca, "調整額(円)": ca - ta_v})
        rdf = pd.DataFrame(rd).sort_values("乖離(%)", key=abs, ascending=False)

        fr = go.Figure()
        for _, r in rdf.iterrows():
            cl = "#FF5252" if r["乖離(%)"] > 1 else "#00E676" if r["乖離(%)"] < -1 else "#9E9E9E"
            fr.add_trace(go.Bar(x=[r["乖離(%)"]], y=[r["セクター"]], orientation="h", marker_color=cl, text=f"{r['乖離(%)']:+.1f}%", textposition="auto", showlegend=False))
        fr.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0", margin=dict(t=10, b=10, l=10, r=10),
                         height=max(len(secs) * 40, 200), xaxis=dict(title="乖離（%）", showgrid=True, gridcolor="#1E232F", zeroline=True, zerolinecolor="#4A5060"), yaxis=dict(showgrid=False))
        st.plotly_chart(fr, width='stretch')
        st.caption("🔴 比重オーバー / 🟢 比重不足 / 灰 適正範囲(±1%)")

        ha = rdf[abs(rdf["乖離(%)"]) > 1.0]
        if not ha.empty:
            st.markdown("##### 📋 調整アクション")
            for _, r in ha.iterrows():
                a = r["調整額(円)"]
                if a > 0: alert_bar(f"📉 <b>{r['セクター']}</b> 現在{r['現在(%)']:.1f}%→目標{r['目標(%)']:.1f}% <span style='color:#FF5252;font-weight:bold'>約¥{abs(a):,.0f}売却</span>", up=False)
                else: alert_bar(f"📈 <b>{r['セクター']}</b> 現在{r['現在(%)']:.1f}%→目標{r['目標(%)']:.1f}% <span style='color:#69F0AE;font-weight:bold'>約¥{abs(a):,.0f}買い増し</span>", up=True)
        else: st.success("✓ 全セクター±1%以内。リバランス不要。")

        # ── ベンチマーク比較 ──
        st.markdown("---"); st.markdown("#### 📊 ベンチマーク比較")
        st.caption("資産推移記録とベンチマーク（日経225 / S&P500）のパフォーマンスを比較します。")
        from data import load_history
        from market import get_cached_market_data
        hdf = load_history()
        if not hdf.empty and len(hdf) >= 2:
            hdf["総資産額(円)"] = pd.to_numeric(hdf["総資産額(円)"], errors="coerce")
            hdf["日付_dt"] = pd.to_datetime(hdf["日付"], errors="coerce")
            hdf = hdf.dropna(subset=["総資産額(円)", "日付_dt"]).sort_values("日付_dt")
            if len(hdf) >= 2:
                start_date = hdf["日付_dt"].iloc[0]
                try:
                    bench_tickers = tuple(sorted(["^N225", "^GSPC"]))
                    bench_df = get_cached_market_data(bench_tickers, period="1y")
                    fig_bench = go.Figure()
                    # ポートフォリオ（正規化）
                    base_val = hdf["総資産額(円)"].iloc[0]
                    hdf["正規化"] = hdf["総資産額(円)"] / base_val * 100
                    fig_bench.add_trace(go.Scatter(x=hdf["日付_dt"], y=hdf["正規化"], mode="lines",
                                                   name="ポートフォリオ", line=dict(color="#00E676", width=2)))
                    for sym, name, color in [("^N225", "日経225", "#00D2FF"), ("^GSPC", "S&P500", "#FFD54F")]:
                        if sym in bench_df.columns:
                            bs = bench_df[sym].dropna()
                            bs = bs[bs.index >= start_date]
                            if not bs.empty:
                                bs_norm = bs / bs.iloc[0] * 100
                                fig_bench.add_trace(go.Scatter(x=bs_norm.index, y=bs_norm.values, mode="lines",
                                                               name=name, line=dict(color=color, width=1.5, dash="dot")))
                    fig_bench.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                                            margin=dict(t=10, b=10, l=10, r=10), height=350,
                                            yaxis=dict(title="パフォーマンス（起点=100）", showgrid=True, gridcolor="#1E232F"),
                                            xaxis=dict(showgrid=True, gridcolor="#1E232F"),
                                            legend=dict(orientation="h", yanchor="bottom", y=1.02, bgcolor="rgba(0,0,0,0)"))
                    st.plotly_chart(fig_bench, width='stretch')
                except Exception:
                    st.info("ベンチマークデータの取得に失敗しました。")
        else:
            st.info("資産推移の記録が2件以上あるとベンチマーク比較が表示されます。")

        # ── リスク指標 ──
        if not hdf.empty and len(hdf) >= 5:
            st.markdown("---"); st.markdown("#### 📐 リスク指標")
            vals = hdf["総資産額(円)"].values
            returns = np.diff(vals) / vals[:-1]
            if len(returns) >= 2:
                volatility = np.std(returns) * np.sqrt(252) * 100
                avg_return = np.mean(returns) * 252
                sharpe = avg_return / (np.std(returns) * np.sqrt(252)) if np.std(returns) > 0 else 0
                cummax = np.maximum.accumulate(vals)
                drawdowns = (vals - cummax) / cummax * 100
                max_dd = np.min(drawdowns)
                rc1, rc2, rc3 = st.columns(3)
                with rc1:
                    colored_card("ボラティリティ（年率）", f"{volatility:.1f}%",
                                 sub="記録ベースの概算値", border_color="#00D2FF")
                with rc2:
                    sc = "#00E676" if sharpe >= 0.5 else "#FFD54F" if sharpe >= 0 else "#FF5252"
                    colored_card("シャープレシオ", f"{sharpe:.2f}",
                                 sub="リスク調整後リターン", border_color=sc)
                with rc3:
                    colored_card("最大ドローダウン", f"{max_dd:.1f}%",
                                 sub="記録期間中の最大下落率", border_color="#FF5252")
