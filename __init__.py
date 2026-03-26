"""タブ共通ヘルパー"""
import streamlit as st

def card(title, value, sub="", border_color="", cls=""):
    bc = f"border-left:3px solid {border_color};" if border_color else ""
    st.markdown(
        f"<div class='status-card {cls}' style='padding:0.7rem;{bc}'>"
        f"<h4>{title}</h4>"
        f"<p class='mv' style='font-size:1.1rem'>{value}</p>"
        f"{'<p class=\"sv\">' + sub + '</p>' if sub else ''}"
        f"</div>", unsafe_allow_html=True)

def colored_card(title, value, color="#FFFFFF", sub="", border_color=""):
    bc = f"border-left:3px solid {border_color};" if border_color else ""
    st.markdown(
        f"<div class='status-card' style='padding:0.7rem;{bc}'>"
        f"<h4>{title}</h4>"
        f"<p class='mv' style='font-size:1.1rem;color:{color}'>{value}</p>"
        f"{'<p class=\"sv\">' + sub + '</p>' if sub else ''}"
        f"</div>", unsafe_allow_html=True)

def pnl_color(v):
    return "#00E676" if v >= 0 else "#FF5252"

def pnl_sign(v):
    return "+" if v >= 0 else ""

def alert_bar(text, up=True):
    cls = "alert-up" if up else "alert-down"
    st.markdown(f"<div class='alert-bar {cls}'>{text}</div>", unsafe_allow_html=True)
