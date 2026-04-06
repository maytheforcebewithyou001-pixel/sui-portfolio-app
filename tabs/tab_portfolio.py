"""TAB 1: ポートフォリオ"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime
from config import BROKER_OPTIONS, TAX_OPTIONS, MARKET_OPTIONS, ACCT_BADGE_MAP
from data import load_data, save_data, load_history, _clear_sheet_cache
from market import get_ticker_name
from calc import round_up_3
from tabs import card, colored_card, pnl_color, pnl_sign


def render(tab, df, display_df, totals):
    TA = totals["total_asset"]
    with tab:
        # ── 銘柄追加フォーム ──
        st.markdown("#### ➕ 銘柄を追加")
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
            with r3a: div_month_sel = st.multiselect("配当月", options=list(range(1, 13)),
                                                      format_func=lambda x: f"{x}月", key="fdm")
            with r3b: buy_fx = st.number_input("取得時為替 (米国株)", min_value=0.0, value=0.0, step=0.1, key="ffx")
            submitted = st.form_submit_button("＋ 追加", width="stretch")

        if submitted and code:
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
            _clear_sheet_cache(); st.success(f"✓ {final_name} を追加"); st.rerun()

        # ── 口座別サマリー ──
        if not df.empty and not display_df.empty:
            st.markdown("---"); st.markdown("#### 🏦 口座別サマリー")
            if "口座" not in display_df.columns: display_df["口座"] = "SBI証券"
            if "口座区分" not in display_df.columns: display_df["口座区分"] = "特定口座"
            ag = display_df.groupby("口座").agg({"評価額(円)": "sum", "税引後損益(円)": "sum", "予想配当(円)": "sum", "銘柄コード": "count"}).reset_index()
            cols = st.columns(min(len(ag), 3)) if len(ag) > 0 else []
            for i, (_, r) in enumerate(ag.iterrows()):
                with cols[i % len(cols)]:
                    bc = ACCT_BADGE_MAP.get(r["口座"], "acct-other")
                    pc = pnl_color(r["税引後損益(円)"]); ps = pnl_sign(r["税引後損益(円)"])
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
                colored_card("NISA合計（非課税）", f"{nv:,.0f}<span>円</span>",
                             sub=f"成長枠 {ng:,.0f}円 · 積立枠 {nt:,.0f}円 · {len(nisa)}銘柄", border_color="#69F0AE")
            with nc2:
                tv = toku["評価額(円)"].sum() if not toku.empty else 0
                colored_card("特定口座合計（課税）", f"{tv:,.0f}<span>円</span>",
                             sub=f"{len(toku)}銘柄", border_color="#FF8F00")

        # ── 保有一覧 ──
        if not df.empty and not display_df.empty:
            st.markdown("---"); st.markdown("#### 📋 保有銘柄一覧")
            cpf = lambda v: f"color: {'#00E676' if v >= 0 else '#FF5252'}"
            cpc = lambda v: "" if pd.isna(v) else f"color: {'#00E676' if v > 0 else '#FF5252' if v < 0 else '#E0E0E0'}"
            fp = lambda v: "-" if pd.isna(v) else (f"+{v:.1f}%" if v > 0 else f"{v:.1f}%")
            show = ["銘柄コード", "銘柄名", "市場", "口座", "口座区分", "保有株数", "取得単価(円)", "現在値(円)", "前日比", "評価額(円)", "税引後損益(円)", "予想配当(円)", "実質利回り(%)"]
            ac = [c for c in show if c in display_df.columns]
            fmt = {"保有株数": round_up_3, "取得単価(円)": round_up_3, "現在値(円)": round_up_3, "前日比": fp,
                   "評価額(円)": "{:,.0f}", "税引後損益(円)": "{:,.0f}", "予想配当(円)": "{:,.0f}", "実質利回り(%)": "{:.2f}%"}
            sdf = display_df[ac].style
            if "税引後損益(円)" in ac: sdf = sdf.map(cpf, subset=["税引後損益(円)"])
            if "前日比" in ac: sdf = sdf.map(cpc, subset=["前日比"])
            sdf = sdf.format({k: v for k, v in fmt.items() if k in ac})
            st.dataframe(sdf, width='stretch', hide_index=True)

            # CSV出力
            st.markdown("---"); st.markdown("#### 📥 データエクスポート")
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                csv_c = ["銘柄コード", "銘柄名", "市場", "口座", "口座区分", "保有株数", "取得単価(円)", "現在値(円)", "評価額(円)", "含み損益(円)", "税引後損益(円)", "予想配当(円)", "税引後配当(円)", "セクター"]
                st.download_button("📋 保有銘柄一覧", display_df[[c for c in csv_c if c in display_df.columns]].to_csv(index=False).encode("utf-8-sig"),
                                   f"portfolio_{datetime.now():%Y%m%d}.csv", "text/csv", width="stretch")
            with ec2:
                dr = [{"銘柄コード": r["銘柄コード"], "銘柄名": r["銘柄名"], "口座": r.get("口座", ""), "口座区分": r.get("口座区分", ""),
                       "予想配当(税引前)": round(r["予想配当(円)"]), "税引後配当": round(r.get("税引後配当(円)", 0)), "配当月": r.get("配当月", "")}
                      for _, r in display_df.iterrows() if r.get("予想配当(円)", 0) > 0]
                if dr: st.download_button("💰 配当明細", pd.DataFrame(dr).to_csv(index=False).encode("utf-8-sig"), f"dividends_{datetime.now():%Y%m%d}.csv", "text/csv", width="stretch")
                else: st.button("💰 配当明細", disabled=True, width="stretch")
            with ec3:
                hdf = load_history()
                if not hdf.empty: st.download_button("📈 資産推移", hdf.to_csv(index=False).encode("utf-8-sig"), f"history_{datetime.now():%Y%m%d}.csv", "text/csv", width="stretch")
                else: st.button("📈 資産推移", disabled=True, width="stretch")

        # ── 修正・削除 ──
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
                    save_data(edited[edited["削除"] == False].drop(columns=["削除"]))
                    _clear_sheet_cache(); st.success("更新しました！"); st.rerun()

        # ── 資産推移チャート ──
        if TA > 0:
            st.markdown("---"); st.markdown("#### 📈 資産推移")
            hdf = load_history()
            if not hdf.empty:
                hdf["総資産額(円)"] = pd.to_numeric(hdf["総資産額(円)"], errors="coerce")
                hdf = hdf.dropna(subset=["総資産額(円)"])
                hdf["日付_dt"] = pd.to_datetime(hdf["日付"], errors="coerce")
                hdf = hdf.dropna(subset=["日付_dt"]).sort_values("日付_dt")
                hf1, hf2, hf3 = st.columns([1, 1, 2])
                with hf1:
                    h_range = st.selectbox("期間", ["全期間", "直近1ヶ月", "直近3ヶ月", "直近6ヶ月", "直近1年"], key="hrange")
                cutoffs = {"直近1ヶ月": 30, "直近3ヶ月": 90, "直近6ヶ月": 180, "直近1年": 365}
                hdf_f = hdf[hdf["日付_dt"] >= pd.Timestamp.now() - pd.Timedelta(days=cutoffs[h_range])] if h_range in cutoffs else hdf
                with hf2: show_cost = st.checkbox("投資元本ラインを表示", value=True, key="hcost")
                if not hdf_f.empty:
                    fig_h = go.Figure()
                    fig_h.add_trace(go.Scatter(x=hdf_f["日付_dt"], y=hdf_f["総資産額(円)"], mode="lines+markers",
                                               name="評価額", line=dict(color="#00E676", width=2), marker=dict(size=6, color="#FFFFFF")))
                    if show_cost and not df.empty:
                        total_cost = (df["保有株数"] * df["取得単価"]).sum()
                        fig_h.add_trace(go.Scatter(x=[hdf_f["日付_dt"].iloc[0], hdf_f["日付_dt"].iloc[-1]],
                                                   y=[total_cost, total_cost], mode="lines",
                                                   name="投資元本(概算)", line=dict(color="#FFD54F", width=1, dash="dash")))
                    if len(hdf_f) >= 2:
                        first_v, last_v = hdf_f["総資産額(円)"].iloc[0], hdf_f["総資産額(円)"].iloc[-1]
                        chg = last_v - first_v; chg_pct = (chg / first_v * 100) if first_v > 0 else 0
                        with hf3:
                            c = pnl_color(chg); s = pnl_sign(chg)
                            st.markdown(f"<div style='padding:0.5rem 0;font-size:0.85rem;color:#B0B8C0'>期間変化: "
                                        f"<span style='color:{c};font-weight:bold'>{s}{chg:,.0f}円 ({s}{chg_pct:.1f}%)</span></div>", unsafe_allow_html=True)
                    fig_h.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                                        margin=dict(t=10, b=10, l=10, r=10), height=320,
                                        xaxis=dict(showgrid=True, gridcolor="#1E232F"),
                                        yaxis=dict(showgrid=True, gridcolor="#1E232F", tickformat=","),
                                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
                    st.plotly_chart(fig_h, width='stretch')
                else: st.info("選択期間内に記録がありません。")
            else: st.info("ヘッダーの「💾 記録」で記録を開始してください。")
