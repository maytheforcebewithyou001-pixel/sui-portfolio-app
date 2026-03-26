"""CSS スタイル定義（1箇所で管理）"""

MAIN_CSS = """
<style>
html, body, .stApp { overflow-y: auto !important; }
.stApp { background-color: #0A0E13; color: #E0E0E0; font-family: sans-serif; }

/* Bloomberg terminal header */
.term-header { background: #0A0E13; border: 1px solid rgba(255,255,255,0.08); border-radius: 4px; overflow: hidden; margin-bottom: 0.7rem; }
.term-top { display: flex; align-items: stretch; border-bottom: 1px solid rgba(255,255,255,0.06); }
.term-logo { padding: 12px 20px; border-right: 1px solid rgba(255,255,255,0.06); display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.term-logo .dot { width: 10px; height: 10px; background: #00E676; border-radius: 50%; }
.term-logo .bracket { color: rgba(255,255,255,0.35); font-size: 15px; letter-spacing: 2px; }
.term-logo .name { color: #00D2FF; font-size: 22px; font-weight: 700; letter-spacing: 4px; }
.term-logo .sub { color: rgba(255,255,255,0.18); font-size: 11px; letter-spacing: 2px; margin-left: 2px; }
.term-ticker-bar { flex: 1; display: flex; align-items: center; gap: 16px; padding: 0 16px; overflow-x: auto; }
.term-ticker { display: flex; align-items: center; gap: 6px; white-space: nowrap; }
.term-ticker .sym { color: rgba(255,255,255,0.35); font-size: 13px; }
.term-ticker .val { color: #FFFFFF; font-size: 14px; font-weight: 600; }
.term-ticker .chg-up { color: #00E676; font-size: 13px; }
.term-ticker .chg-dn { color: #FF5252; font-size: 13px; }
.term-sep { width: 1px; height: 16px; background: rgba(255,255,255,0.08); flex-shrink: 0; }
.term-time { padding: 10px 16px; border-left: 1px solid rgba(255,255,255,0.06); text-align: right; white-space: nowrap; }
.term-time .live { color: rgba(255,255,255,0.35); font-size: 10px; letter-spacing: 1px; }
.term-time .dt { color: rgba(255,255,255,0.5); font-size: 11px; }
.term-bottom { display: flex; align-items: center; gap: 20px; padding: 14px 20px; background: rgba(255,255,255,0.015); flex-wrap: wrap; }
.term-metric { display: flex; align-items: baseline; gap: 8px; }
.term-metric .label { color: rgba(255,255,255,0.35); font-size: 13px; letter-spacing: 1px; font-weight: 600; }
.term-metric .val-lg { font-size: 30px; font-weight: 700; letter-spacing: -0.5px; }
.term-metric .val-md { font-size: 20px; font-weight: 600; }
.term-metric .val-sm { font-size: 14px; }
.term-vsep { width: 1px; height: 24px; background: rgba(255,255,255,0.06); flex-shrink: 0; }
.term-goal-bar { width: 80px; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden; }
.term-goal-fill { height: 100%; background: linear-gradient(90deg, #00D2FF, #00E676); border-radius: 2px; }
@media (max-width: 768px) {
    .term-top { flex-direction: column; }
    .term-logo { border-right: none; border-bottom: 1px solid rgba(255,255,255,0.06); }
    .term-ticker-bar { padding: 8px 14px; flex-wrap: wrap; gap: 8px; }
    .term-time { border-left: none; border-top: 1px solid rgba(255,255,255,0.06); }
    .term-bottom { gap: 12px; }
    .term-metric .val-lg { font-size: 22px; }
    .term-metric .val-md { font-size: 16px; }
}
@keyframes fadeSlideIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
.status-card {
    background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px;
    padding: 1.1rem 1.2rem; margin-bottom: 0.7rem; position: relative;
    animation: fadeSlideIn 0.5s ease-out both; transition: transform 0.2s, box-shadow 0.2s;
}
.status-card:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(0,0,0,0.4); }
.c1{animation-delay:0s}.c2{animation-delay:.08s}.c3{animation-delay:.16s}.c4{animation-delay:.24s}
.status-card h4 { color: #B0B8C0; font-size: 0.78rem; margin: 0 0 0.3rem 0; letter-spacing: 0.04em; font-weight: 600; }
.status-card p.mv { color: #FFFFFF; font-size: 1.55rem; font-weight: bold; margin: 0; line-height: 1.2; }
.status-card p.mv span { color: #00D2FF; font-size: 0.95rem; margin-left: 0.15rem; }
.status-card p.sv { color: #A0A8B0; font-size: 0.78rem; margin: 0.15rem 0 0 0; }
.status-card::before { content: ''; position: absolute; top: 0; left: 0; right: 0; height: 3px; border-radius: 10px 10px 0 0; }
.card-total::before { background: linear-gradient(90deg, #00D2FF, #3A7BD5); }
.card-profit::before { background: linear-gradient(90deg, #00E676, #69F0AE); }
.card-dividend::before { background: linear-gradient(90deg, #FFD54F, #FF8F00); }
.card-goal::before { background: linear-gradient(90deg, #9C27B0, #E040FB); }
.goal-bar-wrap { background: #12161E; border: 1px solid #1E232F; border-radius: 8px; padding: 0.6rem 1rem; margin-bottom: 0.8rem; }
.goal-bar-bg { background: #1E232F; border-radius: 4px; height: 8px; width: 100%; overflow: hidden; }
.goal-bar-fill { height: 100%; border-radius: 4px; background: linear-gradient(90deg, #00D2FF, #00E676); transition: width 1.2s cubic-bezier(0.25,0.46,0.45,0.94); }
.goal-bar-labels { display: flex; justify-content: space-between; font-size: 0.7rem; color: #A0A8B0; margin-top: 4px; }
.alert-bar { display: flex; align-items: center; gap: 8px; font-size: 0.8rem; padding: 8px 14px; border-radius: 8px; margin-bottom: 8px; }
.alert-up { background: rgba(0,230,118,0.08); color: #69F0AE; border: 1px solid rgba(0,230,118,0.2); }
.alert-down { background: rgba(255,23,68,0.08); color: #FF5252; border: 1px solid rgba(255,23,68,0.2); }
.acct-badge { display: inline-block; font-size: 0.7rem; padding: 2px 8px; border-radius: 4px; margin-right: 4px; font-weight: 600; }
.acct-sbi { background: rgba(0,210,255,0.12); color: #00D2FF; }
.acct-rakuten { background: rgba(245,200,66,0.12); color: #FFD54F; }
.acct-nomura { background: rgba(189,147,249,0.12); color: #BD93F9; }
.div-month { text-align: center; padding: 8px 4px; border-radius: 8px; font-size: 0.75rem; }
.div-month-empty { background: #12161E; border: 1px solid #1E232F; color: #4A5060; }
.div-month .month-label { display: block; color: #B0B8C0; margin-bottom: 2px; font-weight: 600; }
.div-month .month-amount { display: block; color: #FFD54F; font-weight: bold; font-size: 0.85rem; }
.stButton > button { background-color: #12161E; color: #C0C8D0; border: 1px solid #1E232F; border-radius: 20px; padding: 0.5rem 1.2rem; font-size: 0.85rem; transition: all 0.2s; }
.stButton > button:hover { background-color: #1E232F; color: #FFFFFF; border-color: #00D2FF; box-shadow: 0 0 12px rgba(0,210,255,0.15); }
.stTabs [data-baseweb="tab-list"] { gap: 4px; background-color: #12161E; border-radius: 10px; padding: 4px; border: 1px solid #1E232F; }
.stTabs [data-baseweb="tab"] { background: transparent; color: #A0A8B0; border-radius: 8px; padding: 8px 16px; font-weight: 600; transition: all 0.15s; }
.stTabs [data-baseweb="tab"]:hover { color: #FFFFFF; background: #1E232F; }
.stTabs [aria-selected="true"] { background: #1E232F !important; color: #00D2FF !important; }
.stTabs [data-baseweb="tab-border"], .stTabs [data-baseweb="tab-highlight"] { display: none; }
.indicator-card { background-color: #12161E; border: 1px solid #1E232F; border-radius: 10px; padding: 1rem; margin-bottom: 1rem; transition: border-color 0.2s; }
.indicator-card:hover { border-color: #2A3040; }
.streamlit-expanderHeader { background-color: #12161E; border-radius: 10px; color: #FFFFFF; font-weight: bold; font-size: 1.1rem; border: 1px solid #1E232F; }
th { background-color: #1E232F !important; color: #FFFFFF !important; }
@media (max-width: 768px) {
    .status-card p.mv { font-size: 1.1rem; }
    .status-card { padding: 0.7rem; }
    .logo-text { font-size: 1.5rem; }
}
</style>
"""

ACCT_BADGE_MAP = {"SBI証券": "acct-sbi", "楽天証券": "acct-rakuten", "持ち株会(野村證券)": "acct-nomura"}