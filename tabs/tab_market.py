"""TAB 5: 世界指標"""
import streamlit as st
import plotly.graph_objects as go
from config import WORLD_INDICES
from market import get_cached_market_data


def render(tab):
    with tab:
        m1, m2 = st.columns([3, 1])
        with m1: pil = st.selectbox("チャート期間", ["1週間", "1ヶ月", "3ヶ月", "1年"], index=1, key="ip")
        with m2:
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            if st.button("🔄 指標を更新", width="stretch", key="rm"):
                get_cached_market_data.clear(); st.rerun()

        sp = {"1週間": "5d", "1ヶ月": "1mo", "3ヶ月": "3mo", "1年": "1y"}[pil]
        with st.spinner("指標データを取得中..."):
            ic = get_cached_market_data(tuple(sorted(WORLD_INDICES.values())), period=sp)
            items = list(WORLD_INDICES.items())
            for i in range(0, len(items), 2):
                rc = st.columns(2)
                for j in range(2):
                    if i + j >= len(items): continue
                    iname, tk = items[i + j]
                    with rc[j]:
                        st.markdown("<div class='indicator-card'>", unsafe_allow_html=True)
                        tc_, cc_ = st.columns([1, 1.5])
                        if tk in ic.columns:
                            ser = ic[tk].dropna()
                            if len(ser) >= 2:
                                lc = ser.iloc[-1]; prc = ser.iloc[-2]; pch = ((lc / prc) - 1) * 100; dif = lc - prc
                                col = "#00E676" if pch >= 0 else "#FF5252"; fc = "rgba(0,230,118,0.15)" if pch >= 0 else "rgba(255,82,82,0.15)"; sgn = "+" if pch >= 0 else ""
                                with tc_:
                                    st.markdown(f"<div style='display:flex;flex-direction:column;justify-content:center;height:150px'>"
                                                f"<p style='color:#B0B8C0;margin:0;font-size:14px;font-weight:bold'>{iname}</p>"
                                                f"<p style='color:#FFF;margin:5px 0 0;font-size:1.4rem;font-weight:bold'>{lc:,.2f}</p>"
                                                f"<p style='color:{col};margin:0 0 5px;font-size:13px;font-weight:bold'>{sgn}{dif:,.2f}<br>({sgn}{pch:.2f}%)</p></div>", unsafe_allow_html=True)
                                with cc_:
                                    fm = go.Figure(data=[go.Scatter(x=ser.index, y=ser.values, mode="lines", line=dict(color=col, width=2), fill="tozeroy", fillcolor=fc)])
                                    ymx, ymn = ser.max(), ser.min(); ymg = (ymx - ymn) * 0.1 if ymx != ymn else lc * 0.1
                                    xtf = "%Y/%m" if sp == "1y" else "%m/%d"
                                    fm.update_layout(plot_bgcolor="#12161E", paper_bgcolor="#12161E", margin=dict(l=45, r=10, t=10, b=30), height=180,
                                                     xaxis=dict(showgrid=True, gridcolor="#2B3240", griddash="dot", tickformat=xtf, tickfont=dict(color="#9E9E9E", size=10)),
                                                     yaxis=dict(showgrid=True, gridcolor="#2B3240", griddash="dot", tickformat=",", tickfont=dict(color="#9E9E9E", size=10), range=[ymn - ymg, ymx + ymg]),
                                                     showlegend=False)
                                    st.plotly_chart(fm, width="stretch", config={"displayModeBar": False})
                            else:
                                with tc_: st.markdown(f"<p style='color:#B0B8C0;font-weight:bold'>{iname}</p><p style='color:#FF5252'>データ不足</p>", unsafe_allow_html=True)
                        else:
                            with tc_: st.markdown(f"<p style='color:#B0B8C0;font-weight:bold'>{iname}</p><p style='color:#FF5252'>取得失敗</p>", unsafe_allow_html=True)
                        st.markdown("</div>", unsafe_allow_html=True)
