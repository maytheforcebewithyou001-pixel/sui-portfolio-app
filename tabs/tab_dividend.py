"""TAB 3: 配当"""
import streamlit as st
import pandas as pd
from tabs import colored_card


def render(tab, df, display_df, totals):
    TA = totals["total_asset"]
    with tab:
        if df.empty or TA <= 0 or display_df.empty:
            st.info("銘柄を追加すると配当カレンダーが表示されます。"); return

        st.markdown("#### 💰 月別配当カレンダー")
        mdv = {m: 0 for m in range(1, 13)}; mda = {m: 0 for m in range(1, 13)}; mdt = {m: [] for m in range(1, 13)}
        for _, row in display_df.iterrows():
            da, daa, dms = row.get("予想配当(円)", 0), row.get("税引後配当(円)", 0), str(row.get("配当月", ""))
            if da > 0 and dms:
                try:
                    ml = [int(x.strip()) for x in dms.split(",") if x.strip().isdigit()]
                    p, pa = da / len(ml), daa / len(ml)
                    tl = "非課税" if "NISA" in str(row.get("口座区分", "")) else "課税"
                    for m in ml:
                        if 1 <= m <= 12: mdv[m] += p; mda[m] += pa; mdt[m].append({"銘柄": f"{row['銘柄コード']} {row['銘柄名']}", "税引前": p, "税引後": pa, "税区分": tl})
                except Exception: pass

        mn = [f"{m}月" for m in range(1, 13)]
        for rs in range(0, 12, 4):
            cols = st.columns(4)
            for i in range(4):
                m = rs + i + 1
                with cols[i]:
                    if mdv[m] > 0:
                        with st.popover(f"📅 {mn[m-1]}", width="stretch"):
                            st.markdown(f"**{mn[m-1]}** 税引前:¥{mdv[m]:,.0f} → 手取り:¥{mda[m]:,.0f}")
                            for d in sorted(mdt[m], key=lambda x: x["税引前"], reverse=True):
                                tb = "🟢" if d["税区分"] == "非課税" else "🟡"
                                st.markdown(f"<div style='display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #1E232F;font-size:0.85rem'>"
                                            f"<span style='color:#B0B8C0'>{tb} {d['銘柄']}</span><span style='color:#FFD54F;font-weight:bold'>¥{d['税引後']:,.0f}</span></div>", unsafe_allow_html=True)
                        st.markdown(f"<div style='text-align:center;margin-top:-8px;margin-bottom:8px'><span style='color:#FFD54F;font-weight:bold;font-size:0.9rem'>¥{mda[m]:,.0f}</span>"
                                    f"<span style='color:#7A8A9A;font-size:0.6rem;display:block'>手取り·{len(mdt[m])}銘柄</span></div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"<div class='div-month div-month-empty'><span class='month-label'>{mn[m-1]}</span><span class='month-amount'>—</span></div>", unsafe_allow_html=True)

        st.markdown("---")
        tcd, tcda = sum(mdv.values()), sum(mda.values())
        if tcd > 0:
            dc1, dc2, dc3, dc4 = st.columns(4)
            with dc1: colored_card("年間配当（税引前）", f"¥{tcd:,.0f}", border_color="#FFD54F")
            with dc2: colored_card("年間手取り（税引後）", f"¥{tcda:,.0f}", border_color="#69F0AE")
            with dc3: colored_card("月平均手取り", f"¥{tcda/12:,.0f}", border_color="#00D2FF")
            with dc4: colored_card("配当発生月", f"{sum(1 for v in mdv.values() if v>0)}<span>/12ヶ月</span>", border_color="#BD93F9")

        st.markdown("---"); st.markdown("#### 🏆 配当金ランキング")
        drank = display_df[display_df["予想配当(円)"] > 0][["銘柄コード", "銘柄名", "予想配当(円)", "実質利回り(%)"]].sort_values("予想配当(円)", ascending=False).head(10)
        if not drank.empty:
            drank["予想配当(円)"] = drank["予想配当(円)"].apply(lambda x: f"¥{int(x):,}")
            drank["実質利回り(%)"] = drank["実質利回り(%)"].apply(lambda x: f"{x:.2f}%")
            st.dataframe(drank, width='stretch', hide_index=True)