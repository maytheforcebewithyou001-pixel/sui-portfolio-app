"""TAB 5: 世界指標"""
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from config import WORLD_INDICES
from market import get_cached_market_data
import jquants


# 投資部門 (J-Quants v2 投資部門別売買のBalカラム表示名マップ)
_INVESTOR_LABELS = {
    "FrgnBal": "海外投資家",
    "IndBal": "個人",
    "TrstBnkBal": "信託銀行",
    "InvTrBal": "投資信託",
    "BusCoBal": "事業法人",
    "InsCoBal": "生損保",
    "BankBal": "都銀・地銀",
    "PropBal": "自己",
}
_INVESTOR_COLORS = {
    "FrgnBal": "#00D2FF",
    "IndBal": "#FFD54F",
    "TrstBnkBal": "#B388FF",
    "InvTrBal": "#69F0AE",
    "BusCoBal": "#FF7043",
    "InsCoBal": "#90A4AE",
    "BankBal": "#7986CB",
    "PropBal": "#A1887F",
}


def _render_investor_flow():
    """投資部門別売買フロー (TSEPrime)"""
    st.markdown("---")
    st.markdown("### 📡 投資部門別 売買フロー (TSEPrime)")
    st.caption("海外投資家・個人・信託銀行などの週次ネット買越額。需給転換シグナルの確認に使用。")

    pc1, pc2 = st.columns([1, 3])
    with pc1:
        period_label = st.selectbox("期間", ["12週", "26週", "52週"], index=0, key="investor_period")
    weeks = {"12週": 12, "26週": 26, "52週": 52}[period_label]

    df = jquants.get_investor_types(weeks=weeks)
    if df is None or df.empty:
        st.info("J-Quants 投資部門別売買データが取得できなかったわ。プラン契約範囲を確認して。")
        return

    available_cols = [c for c in _INVESTOR_LABELS.keys() if c in df.columns]
    if "EnDate" not in df.columns or not available_cols:
        st.info("投資部門データのカラム構造が想定と違う。スキップ。")
        return

    default_picks = [c for c in ["FrgnBal", "IndBal", "TrstBnkBal", "InvTrBal"] if c in available_cols]
    picked = st.multiselect(
        "表示する投資部門を選択",
        options=available_cols,
        format_func=lambda c: _INVESTOR_LABELS.get(c, c),
        default=default_picks,
        key="investor_types_pick",
    )
    if not picked:
        st.caption("部門を1つ以上選択してね")
        return

    show_cumulative = st.checkbox("累積買越額グラフを表示（マネー流入の中長期トレンド）", value=False, key="investor_cumulative")

    chart_df = df[["EnDate"] + picked].copy()

    fig = go.Figure()
    for col in picked:
        fig.add_trace(go.Bar(
            x=chart_df["EnDate"],
            y=chart_df[col] / 1e8,  # 億円単位
            name=_INVESTOR_LABELS.get(col, col),
            marker_color=_INVESTOR_COLORS.get(col, "#888"),
        ))
    fig.add_hline(y=0, line_color="#777", line_width=1)
    fig.update_layout(
        plot_bgcolor="#12161E", paper_bgcolor="#12161E",
        margin=dict(l=50, r=10, t=10, b=40), height=360,
        barmode="group",
        xaxis=dict(showgrid=True, gridcolor="#2B3240", griddash="dot",
                   tickformat="%Y/%m" if weeks > 26 else "%m/%d", tickfont=dict(color="#9E9E9E", size=10)),
        yaxis=dict(showgrid=True, gridcolor="#2B3240", griddash="dot",
                   tickformat=",.0f", tickfont=dict(color="#9E9E9E", size=10),
                   title=dict(text="ネット買越額 (億円)", font=dict(color="#9E9E9E", size=11))),
        legend=dict(orientation="h", x=0, y=-0.15, font=dict(color="#B0B8C0", size=11)),
    )
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})

    if show_cumulative:
        fig_c = go.Figure()
        for col in picked:
            cum = (chart_df[col].fillna(0) / 1e8).cumsum()
            fig_c.add_trace(go.Scatter(
                x=chart_df["EnDate"], y=cum, mode="lines",
                name=_INVESTOR_LABELS.get(col, col),
                line=dict(color=_INVESTOR_COLORS.get(col, "#888"), width=2),
            ))
        fig_c.add_hline(y=0, line_color="#777", line_width=1)
        fig_c.update_layout(
            plot_bgcolor="#12161E", paper_bgcolor="#12161E",
            margin=dict(l=50, r=10, t=10, b=40), height=320,
            xaxis=dict(showgrid=True, gridcolor="#2B3240", griddash="dot",
                       tickformat="%Y/%m", tickfont=dict(color="#9E9E9E", size=10)),
            yaxis=dict(showgrid=True, gridcolor="#2B3240", griddash="dot",
                       tickformat=",.0f", tickfont=dict(color="#9E9E9E", size=10),
                       title=dict(text="累積買越額 (億円)", font=dict(color="#9E9E9E", size=11))),
            legend=dict(orientation="h", x=0, y=-0.15, font=dict(color="#B0B8C0", size=11)),
        )
        st.plotly_chart(fig_c, width="stretch", config={"displayModeBar": False})

    # 直近4週の数値テーブル
    st.markdown("**直近4週 ネット買越額 (億円)**")
    latest4 = chart_df.tail(4).copy()
    latest4["EnDate"] = latest4["EnDate"].dt.strftime("%Y-%m-%d")
    for col in picked:
        latest4[col] = (latest4[col] / 1e8).round(0).astype("Int64")
    latest4 = latest4.rename(columns={"EnDate": "週末日", **{c: _INVESTOR_LABELS.get(c, c) for c in picked}})
    st.dataframe(latest4, hide_index=True, width="stretch")

    # 簡易シグナル検出
    signals = []
    if "FrgnBal" in df.columns:
        f = df["FrgnBal"].dropna()
        if len(f) >= 2:
            prev, curr = f.iloc[-2], f.iloc[-1]
            if prev < 0 and curr > 0:
                signals.append(f"🟢 海外投資家がネット買越転換 ({prev/1e8:+,.0f}億 → {curr/1e8:+,.0f}億) — 買い好機")
            elif prev > 0 and curr < 0:
                signals.append(f"🔴 海外投資家がネット売越転換 ({prev/1e8:+,.0f}億 → {curr/1e8:+,.0f}億) — 警戒")
    if "IndBal" in df.columns:
        ind = df["IndBal"].dropna()
        if len(ind) >= 8:
            mean_, std_ = ind.iloc[:-1].mean(), ind.iloc[:-1].std()
            latest = ind.iloc[-1]
            if std_ and std_ > 0:
                z = (latest - mean_) / std_
                if z > 1.5:
                    signals.append(f"⚠️ 個人ネット買越過熱 (Z={z:+.2f}) — 戻り売り圧力警戒")
                elif z < -1.5:
                    signals.append(f"⚠️ 個人ネット売越過熱 (Z={z:+.2f}) — 逆張り好機の可能性")
    if signals:
        st.markdown("**フロー検出シグナル**")
        for s in signals:
            st.markdown(f"- {s}")


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

        # 投資部門別フロー (J-Quants)
        _render_investor_flow()
