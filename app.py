"""
FORCE CAPITAL — メインUI (司令塔)
  config.py  定数    | data.py   Google Sheets
  market.py  市場    | calc.py   計算エンジン
  style.py   CSS     | tabs/     タブUI
"""
import streamlit as st
import pandas as pd
import hmac
import html
import time
import bcrypt
from datetime import datetime

from config import WORLD_INDICES, logger
from data import load_data, load_fund_prices, load_gas_prices, load_history, save_history, get_gas_last_updated
from market import get_cached_market_data, get_cached_ticker_info
from calc import calculate_portfolio, get_portfolio_totals
from style import MAIN_CSS
from tabs import pnl_color, pnl_sign

st.set_page_config(page_title="FORCE CAPITAL", layout="wide", initial_sidebar_state="collapsed")
st.markdown(MAIN_CSS, unsafe_allow_html=True)

# ═══════════════════ 認証 ═══════════════════
SESSION_TTL_SEC = 2 * 3600  # 2時間でセッション失効

def _verify_credentials(username: str, password: str) -> bool:
    """ユーザー名＋bcryptハッシュでパスワード検証。
    st.secrets["users"][username] に bcrypt ハッシュを保存する形式。
    レガシー互換: st.secrets["app_password"] がある場合は単一ユーザーとして受付。
    """
    if not username or not password:
        # タイミング攻撃防止のためダミーハッシュで計算
        bcrypt.checkpw(b"dummy", b"$2b$12$KIXtvPMnVAH9ccY1YY4vROlGK8YZQhgfYFCjLcfXsY9oB8q9T/TAG")
        return False
    users = st.secrets.get("users", {})
    stored_hash = users.get(username, "") if users else ""
    if stored_hash:
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
        except (ValueError, TypeError) as e:
            logger.error("bcrypt検証エラー: %s", e)
            return False
    # レガシー互換: 単一パスワードの旧設定
    legacy = st.secrets.get("app_password", "")
    if legacy and username == "admin":
        return hmac.compare_digest(password, legacy)
    # 存在しないユーザーでもダミー計算してタイミング差を作らない
    bcrypt.checkpw(b"dummy", b"$2b$12$" + b"x" * 53)
    return False

def check_password():
    # セッション有効期限チェック
    if st.session_state.get("authenticated"):
        if time.time() - st.session_state.get("login_time", 0) < SESSION_TTL_SEC:
            return True
        st.session_state["authenticated"] = False
        st.warning("セッションの有効期限が切れました。再ログインしてください。")
    st.markdown("""
    <div style='display:flex;justify-content:center;align-items:center;min-height:60vh'>
      <div style='text-align:center'>
        <div style='margin-bottom:1rem'>
          <span style='color:rgba(255,255,255,0.35);font-family:Courier New,monospace;font-size:13px;letter-spacing:2px'>&lt;</span>
          <span style='color:#00D2FF;font-family:Courier New,monospace;font-size:24px;font-weight:700;letter-spacing:4px'>FORCE</span>
          <span style='color:rgba(255,255,255,0.35);font-family:Courier New,monospace;font-size:13px;letter-spacing:2px'>&gt;</span>
          <span style='color:rgba(255,255,255,0.18);font-family:monospace;font-size:10px;letter-spacing:2px;margin-left:4px'>CAPITAL</span>
        </div>
        <p style='color:rgba(255,255,255,0.4);font-size:0.85rem;margin-bottom:1.5rem'>アクセスにはパスワードが必要です</p>
      </div>
    </div>""", unsafe_allow_html=True)
    MAX_ATTEMPTS = 5
    attempts = st.session_state.get("login_attempts", 0)
    if attempts >= MAX_ATTEMPTS:
        st.error("試行回数が上限に達しました。ページを再読込してください。")
        return False
    with st.form("login_form", clear_on_submit=False):
        username = st.text_input("ユーザー名", key="user_input", autocomplete="username")
        password = st.text_input("パスワード", type="password", key="pw_input", autocomplete="current-password")
        submitted = st.form_submit_button("ログイン", width="stretch")
    # ユーザー名入力欄に自動フォーカス（ページ読込直後に即入力可能に）
    st.markdown("""
    <script>
      const tryFocus = () => {
        const inputs = window.parent.document.querySelectorAll('input[type="text"]');
        if (inputs.length > 0) { inputs[0].focus(); return true; }
        return false;
      };
      if (!tryFocus()) setTimeout(tryFocus, 100);
    </script>
    """, unsafe_allow_html=True)
    if submitted:
        if _verify_credentials(username, password):
            st.session_state["authenticated"] = True
            st.session_state["username"] = username
            st.session_state["login_time"] = time.time()
            st.session_state["login_attempts"] = 0
            logger.info("ログイン成功 user=%s", username)
            st.rerun()
        else:
            st.session_state["login_attempts"] = attempts + 1
            remaining = MAX_ATTEMPTS - st.session_state["login_attempts"]
            # ブルートフォース対策: 失敗ごとに指数バックオフ遅延
            delay = min(2 ** st.session_state["login_attempts"], 30)
            logger.warning("ログイン失敗 user=%s attempt=%d delay=%ds", username, st.session_state["login_attempts"], delay)
            time.sleep(delay)
            st.error(f"パスワードが正しくありません（残り{remaining}回）")
    return False

if not check_password(): st.stop()

# ═══════════════════ サイドバー ═══════════════════
with st.sidebar:
    _current_user = st.session_state.get("username", "(未ログイン)")
    st.markdown(f"### 👤 {html.escape(_current_user)}")
    if st.button("🚪 ログアウト", width="stretch"):
        st.cache_data.clear()
        for k in ["authenticated", "username", "login_time", "login_attempts"]:
            st.session_state.pop(k, None)
        st.rerun()
    st.markdown("---")
    st.markdown("### ⚙️ 設定")
    goal_oku = st.slider("🎯 目標金額 (億円)", 0.5, 10.0, 1.2, 0.1)
    goal_amount = goal_oku * 1e8
    interest_rate_pct = st.slider("📈 想定年利 (%)", 1.0, 20.0, 6.0, 0.5)
    interest_rate = interest_rate_pct / 100.0
    yearly_add_man = st.number_input("💰 年間積立額 (万円)", min_value=0, value=120, step=10)
    yearly_add = yearly_add_man * 10000
    st.markdown("---")
    if st.button("🔄 全データ最新化", width="stretch"):
        st.cache_data.clear(); st.rerun()
    st.caption("左上の × で閉じる")

# ═══════════════════ データ取得 ═══════════════════
df = load_data()
fund_prices = load_fund_prices()
gas_prices = load_gas_prices()

gas_last_updated = get_gas_last_updated()

if not df.empty:
    with st.spinner("市場データを取得中..."):
        tickers = ["JPY=X"]
        for _, row in df.iterrows():
            c, m = str(row["銘柄コード"]), row["市場"]
            if m == "日本株": tickers.append(f"{c}.T")
            elif m == "米国株": tickers.append(c)
        unique_tickers = tuple(sorted(set(tickers)))
        closes_df = get_cached_market_data(unique_tickers, period="1y")
        info_dict = get_cached_ticker_info(unique_tickers)
        s = closes_df["JPY=X"].dropna() if "JPY=X" in closes_df.columns else pd.Series()
        jpy_usd_rate = s.iloc[-1] if not s.empty else 150.0
        display_df = calculate_portfolio(df, closes_df, info_dict, fund_prices, jpy_usd_rate, gas_prices)
        totals = get_portfolio_totals(display_df)
else:
    totals = dict(total_asset=0, total_net_profit=0, total_gross_profit=0, total_dividend=0, total_dividend_after_tax=0,
                  total_fx_gain=0, total_stock_gain=0, avg_dividend_yield=0.0, stock_count=0)
    jpy_usd_rate = 150.0; display_df = pd.DataFrame()

TA, SC = totals["total_asset"], totals["stock_count"]

# ═══════════════════ ヘッダー ═══════════════════
prev_asset = prev_diff = prev_diff_pct = 0; prev_date_str = ""
try:
    _hdf = load_history()
    if not _hdf.empty:
        _hdf["総資産額(円)"] = pd.to_numeric(_hdf["総資産額(円)"], errors="coerce")
        prev_asset = _hdf["総資産額(円)"].iloc[-1]; prev_date_str = str(_hdf["日付"].iloc[-1])
        if prev_asset > 0 and TA > 0:
            prev_diff = TA - prev_asset; prev_diff_pct = (prev_diff / prev_asset) * 100
except Exception: pass

tnp, tda = totals["total_net_profit"], totals["total_dividend_after_tax"]
tgp = totals["total_gross_profit"]
prog = min(TA / goal_amount * 100, 100.0) if goal_amount > 0 else 100.0
pc, ps = pnl_color(tgp), pnl_sign(tgp)
pnl_pct = (tgp / (TA - tgp) * 100) if (TA - tgp) > 0 else 0
from zoneinfo import ZoneInfo
_JST = ZoneInfo("Asia/Tokyo")
_EST = ZoneInfo("America/New_York")
_now_jst = datetime.now(_JST)
now_str = _now_jst.strftime("%Y/%m/%d %H:%M")

# 市場開場判定
def _is_market_open(now_local, open_h, open_m, close_h, close_m):
    wd = now_local.weekday()
    if wd >= 5: return False  # 土日
    t = now_local.hour * 60 + now_local.minute
    return open_h * 60 + open_m <= t < close_h * 60 + close_m

_jp_open = _is_market_open(_now_jst, 9, 0, 15, 30)  # 東証 9:00-15:30
_now_est = datetime.now(_EST)
_us_open = _is_market_open(_now_est, 9, 30, 16, 0)   # NYSE/NASDAQ 9:30-16:00

_jp_status = "<span class='mkt-open'>● 東証 開場中</span>" if _jp_open else "<span class='mkt-closed'>○ 東証 閉場</span>"
_us_status = "<span class='mkt-open'>● 米国 開場中</span>" if _us_open else "<span class='mkt-closed'>○ 米国 閉場</span>"

# ティッカーバー
ticker_bar_html = ""
try:
    idx_closes = get_cached_market_data(tuple(sorted(["^N225", "^GSPC", "JPY=X", "^VIX"])), period="5d")
    for sym, tk in [("N225", "^N225"), ("SPX", "^GSPC"), ("USD/JPY", "JPY=X"), ("VIX", "^VIX")]:
        if tk in idx_closes.columns:
            _s = idx_closes[tk].dropna()
            if len(_s) >= 2:
                _lc, _pr = _s.iloc[-1], _s.iloc[-2]; _ch = ((_lc / _pr) - 1) * 100
                _chcls = "chg-up" if _ch >= 0 else "chg-dn"; _chs = "+" if _ch >= 0 else ""
                ticker_bar_html += f"<div class='term-ticker'><span class='sym'>{sym}</span><span class='val'>{_lc:,.1f}</span><span class='{_chcls}'>{_chs}{_ch:.1f}%</span></div><div class='term-sep'></div>"
    if ticker_bar_html.endswith("<div class='term-sep'></div>"):
        ticker_bar_html = ticker_bar_html[:-len("<div class='term-sep'></div>")]
except Exception:
    ticker_bar_html = "<span style='color:rgba(255,255,255,0.3);font-size:11px'>指標読込中...</span>"

prev_html = ""
if prev_asset > 0:
    _pc, _ps = pnl_color(prev_diff), pnl_sign(prev_diff)
    prev_html = f"<span class='val-sm' style='color:{_pc};margin-left:8px'>{_ps}{prev_diff:,.0f} ({_ps}{prev_diff_pct:.1f}%) vs {prev_date_str}</span>"

st.markdown(f"""
<div class='term-header'>
  <div class='term-top'>
    <div class='term-logo'><div class='dot'></div><span class='bracket'>&lt;</span><span class='name'>FORCE</span><span class='bracket'>&gt;</span><span class='sub'>CAPITAL</span></div>
    <div class='term-ticker-bar'>{ticker_bar_html}</div>
    <div class='term-time'><div class='mkt-row'>{_jp_status} {_us_status}</div><div class='dt'>{now_str} JST</div></div>
  </div>
  <div class='term-bottom'>
    <div class='term-metric'><span class='label'>評価額</span><span class='val-lg' style='color:#00D2FF'>¥{TA:,.0f}</span>{prev_html}</div>
    <div class='term-vsep'></div>
    <div class='term-metric'><span class='label'>損益</span><span class='val-md' style='color:{pc}'>{ps}¥{abs(tgp):,.0f}</span><span class='val-sm' style='color:{pnl_color(tnp)}'>({pnl_sign(tnp)}¥{abs(tnp):,.0f})</span><span class='val-sm' style='color:{pc}'> {ps}{pnl_pct:.1f}%</span></div>
    <div class='term-vsep'></div>
    <div class='term-metric'><span class='label'>年間配当</span><span class='val-md' style='color:#FFD54F'>¥{tda:,.0f}</span><span class='val-sm' style='color:rgba(255,255,255,0.35)'>{totals["avg_dividend_yield"]:.2f}%</span></div>
    <div class='term-vsep'></div>
    <div class='term-metric'><span class='label'>銘柄</span><span class='val-md' style='color:rgba(255,255,255,0.7)'>{SC}</span></div>
    <div style='flex:1'></div>
    <div class='term-metric'><span class='label'>目標</span><div class='term-goal-bar'><div class='term-goal-fill' style='width:{prog:.1f}%'></div></div><span class='val-sm' style='color:rgba(255,255,255,0.5)'>{prog:.1f}%</span></div>
  </div>
</div>""", unsafe_allow_html=True)

# 記録ボタン
_rec1, _rec2 = st.columns([5, 1])
with _rec2:
    if st.button("💾 記録", width="stretch") and TA > 0:
        save_history(datetime.now().strftime("%Y/%m/%d"), TA); st.toast("✓ 記録しました"); st.rerun()

# GASバナー
if gas_prices and gas_last_updated:
    try:
        gas_dt = datetime.strptime(gas_last_updated[:16], "%Y/%m/%d %H:%M")
        gap_min = (datetime.now() - gas_dt).total_seconds() / 60
        if gap_min > 60:
            st.markdown(f"<div class='alert-bar alert-down'>⚠ GAS株価データが古い可能性あり（最終更新: {gas_last_updated}、約{gap_min/60:.0f}時間前）</div>", unsafe_allow_html=True)
        else: st.caption(f"📡 GAS株価データ 最終更新: {gas_last_updated}")
    except Exception: pass

# 為替損益サマリー
tfx, tsg = totals["total_fx_gain"], totals["total_stock_gain"]
if tfx != 0 or tsg != 0:
    fx1, fx2 = st.columns(2)
    with fx1:
        c, s = pnl_color(tsg), pnl_sign(tsg)
        st.markdown(f"<div class='status-card' style='padding:0.6rem;border-left:3px solid #00D2FF'><h4>米国株 株価損益</h4><p class='mv' style='font-size:1rem;color:{c}'>{s}{tsg:,.0f}<span>円</span></p><p class='sv'>株価の値動きによる損益</p></div>", unsafe_allow_html=True)
    with fx2:
        c, s = pnl_color(tfx), pnl_sign(tfx)
        st.markdown(f"<div class='status-card' style='padding:0.6rem;border-left:3px solid #FFD54F'><h4>米国株 為替損益</h4><p class='mv' style='font-size:1rem;color:{c}'>{s}{tfx:,.0f}<span>円</span></p><p class='sv'>為替変動（$1=¥{jpy_usd_rate:.1f}）による損益</p></div>", unsafe_allow_html=True)

# 大幅変動アラート
if not display_df.empty and "前日比" in display_df.columns:
    for _, mv in display_df[display_df["前日比"].apply(lambda x: abs(x) >= 3.0 if pd.notna(x) else False)].iterrows():
        d = mv["前日比"]; cls = "alert-up" if d > 0 else "alert-down"; arrow = "▲" if d > 0 else "▼"
        _name = html.escape(str(mv['銘柄名'])); _code = html.escape(str(mv['銘柄コード']))
        st.markdown(f"<div class='alert-bar {cls}'>{arrow} <b>{_name}</b>（{_code}）が前日比 {d:+.2f}% の大幅変動</div>", unsafe_allow_html=True)

# ═══════════════════ タブ ═══════════════════
from tabs import tab_portfolio, tab_analysis, tab_dividend, tab_simulation, tab_market, tab_transaction, tab_ai

tab_pf, tab_an, tab_div, tab_sim, tab_mkt, tab_tx, tab_ai_tab = st.tabs(
    ["📊 ポートフォリオ", "🔍 分析", "💰 配当", "🚀 シミュレーション", "🌍 世界指標", "📒 取引履歴", "🤖 AI総評"])

tab_portfolio.render(tab_pf, df, display_df, totals)
tab_analysis.render(tab_an, df, display_df, totals)
tab_dividend.render(tab_div, df, display_df, totals)
tab_simulation.render(tab_sim, df, totals, goal_amount, goal_oku, interest_rate, interest_rate_pct, yearly_add)
tab_market.render(tab_mkt)
tab_transaction.render(tab_tx, df)
tab_ai.render(tab_ai_tab, df, display_df, totals, jpy_usd_rate)
