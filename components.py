"""
components.py — 再利用可能なUIコンポーネント
CSS は style.py に一本化。ここではHTML生成関数のみ定義。
"""
import streamlit as st
import pandas as pd


def status_card(title, value_html, sub_html="", card_class="", delay_class=""):
    sub_part = f"<p class='sv'>{sub_html}</p>" if sub_html else ""
    st.markdown(
        f"<div class='status-card {card_class} {delay_class}'><h4>{title}</h4>"
        f"<p class='mv'>{value_html}</p>{sub_part}</div>",
        unsafe_allow_html=True,
    )


def goal_progress_bar(current, goal, goal_label):
    pv = min(current / goal * 100, 100.0) if goal > 0 else 0
    st.markdown(
        f"<div class='goal-bar-wrap'>"
        f"<div class='goal-bar-bg'><div class='goal-bar-fill' style='width:{pv}%'></div></div>"
        f"<div class='goal-bar-labels'><span>¥0</span>"
        f"<span style='color:#00D2FF'>{pv:.1f}% 達成</span>"
        f"<span>{goal_label}</span></div></div>",
        unsafe_allow_html=True,
    )


def big_mover_alert(name, code, pct):
    import html as _html
    cls = "alert-up" if pct > 0 else "alert-down"
    arrow = "▲" if pct > 0 else "▼"
    name_s = _html.escape(str(name))
    code_s = _html.escape(str(code))
    st.markdown(
        f"<div class='alert-bar {cls}'>{arrow} <b>{name_s}</b>（{code_s}）が前日比 {pct:+.2f}% の大幅変動</div>",
        unsafe_allow_html=True,
    )


def fmt_pnl_color(v):
    return f"color: {'#00E676' if v >= 0 else '#FF5252'}"


def fmt_dod_color(v):
    if pd.isna(v):
        return ""
    return f"color: {'#00E676' if v > 0 else '#FF5252' if v < 0 else '#E0E0E0'}"


def fmt_dod_pct(v):
    if pd.isna(v):
        return "-"
    return f"+{v:.1f}%" if v > 0 else f"{v:.1f}%"
