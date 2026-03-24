"""CSS スタイル定義（1箇所で管理）"""

MAIN_CSS = """
<style>
html, body, .stApp { overflow-y: auto !important; }
.stApp { background-color: #0A0E13; color: #E0E0E0; font-family: sans-serif; }
.logo-text { color: #00D2FF; font-weight: bold; font-size: 2.2rem; letter-spacing: 0.05rem; line-height: 1; }
.logo-text span { color: #F0F0F0; }
.logo-sub { color: #B0B0B0; font-size: 0.78rem; margin-top: 4px; }
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
