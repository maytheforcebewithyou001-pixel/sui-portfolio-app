"""TAB: ランク達成"""
import streamlit as st
from config import RANK_TIERS, get_rank


def render(tab, totals):
    TA = totals["total_asset"]
    rank = get_rank(TA)
    current_level = rank[2] if rank else 0

    with tab:
        # ── 現在ランク ──
        if rank:
            name, color, level, max_level = rank
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
            fill = round(level / max_level * 10)
            bars_on = "\u25B0" * fill
            bars_off = "\u25B1" * (10 - fill)

            # 次ランク情報
            if level < max_level:
                next_threshold, next_name, _ = RANK_TIERS[level]
                remaining = next_threshold - TA
                next_info = f"次のランク <b>{next_name}</b> まで <b>&#165;{remaining:,.0f}</b>"
            else:
                next_info = "全ランク制覇"

            st.markdown(f"""
            <div style='text-align:center;padding:2rem 1rem 1.5rem'>
              <div style='color:rgba(255,255,255,0.35);font-size:12px;letter-spacing:3px;margin-bottom:8px'>CURRENT RANK</div>
              <div style='font-family:Courier New,monospace;font-size:42px;font-weight:700;color:{color};
                          letter-spacing:6px;text-shadow:0 0 20px rgba({r},{g},{b},0.4)'>{name}</div>
              <div style='margin:12px 0 8px'>
                <span style='font-family:Courier New,monospace;font-size:16px;color:{color};letter-spacing:2px'>{bars_on}</span>
                <span style='font-family:Courier New,monospace;font-size:16px;color:rgba(255,255,255,0.12);letter-spacing:2px'>{bars_off}</span>
              </div>
              <div style='color:rgba(255,255,255,0.4);font-size:13px;letter-spacing:1px'>LV. {level} / {max_level}</div>
              <div style='color:rgba(255,255,255,0.5);font-size:13px;margin-top:12px'>{next_info}</div>
            </div>""", unsafe_allow_html=True)
        else:
            st.markdown("""
            <div style='text-align:center;padding:2rem 1rem'>
              <div style='color:rgba(255,255,255,0.35);font-size:12px;letter-spacing:3px;margin-bottom:8px'>CURRENT RANK</div>
              <div style='font-family:Courier New,monospace;font-size:28px;color:rgba(255,255,255,0.25);letter-spacing:4px'>UNRANKED</div>
              <div style='color:rgba(255,255,255,0.4);font-size:13px;margin-top:12px'>
                最初のランク <b>CADET</b> まで <b>&#165;{:,.0f}</b></div>
            </div>""".format(1_000_000 - TA), unsafe_allow_html=True)

        st.markdown("---")

        # ── 全ランク一覧 ──
        st.markdown("<div style='color:rgba(255,255,255,0.35);font-size:12px;letter-spacing:3px;"
                    "text-align:center;margin-bottom:16px'>ALL RANKS</div>", unsafe_allow_html=True)

        for i, (threshold, name, color) in enumerate(RANK_TIERS):
            tier_level = i + 1
            achieved = tier_level <= current_level
            is_current = tier_level == current_level
            r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)

            if is_current:
                border = f"border:1px solid rgba({r},{g},{b},0.5)"
                bg = f"background:rgba({r},{g},{b},0.1)"
                shadow = f"box-shadow:0 0 15px rgba({r},{g},{b},0.15)"
                name_style = f"color:{color};font-weight:700"
                amount_style = f"color:{color}"
                indicator = f"<span style='color:{color};font-size:10px;letter-spacing:1px;margin-left:8px'>&#9664; NOW</span>"
            elif achieved:
                border = f"border:1px solid rgba({r},{g},{b},0.25)"
                bg = f"background:rgba({r},{g},{b},0.05)"
                shadow = ""
                name_style = f"color:{color}"
                amount_style = f"color:rgba(255,255,255,0.5)"
                indicator = f"<span style='color:rgba({r},{g},{b},0.5);font-size:10px;margin-left:8px'>&#10003;</span>"
            else:
                border = "border:1px solid rgba(255,255,255,0.06)"
                bg = "background:rgba(255,255,255,0.02)"
                shadow = ""
                name_style = "color:rgba(255,255,255,0.25)"
                amount_style = "color:rgba(255,255,255,0.2)"
                indicator = ""

            st.markdown(f"""
            <div style='{border};{bg};{shadow};border-radius:6px;padding:10px 16px;margin-bottom:6px;
                        display:flex;align-items:center;justify-content:space-between;transition:all 0.2s'>
              <div style='display:flex;align-items:center;gap:12px'>
                <span style='font-family:Courier New,monospace;font-size:11px;color:rgba(255,255,255,0.25);
                             min-width:28px'>LV.{tier_level}</span>
                <span style='font-family:Courier New,monospace;font-size:14px;letter-spacing:2px;{name_style}'>{name}</span>
                {indicator}
              </div>
              <span style='font-family:Courier New,monospace;font-size:13px;{amount_style}'>&#165;{threshold:,.0f}</span>
            </div>""", unsafe_allow_html=True)
