"""TAB 1: ポートフォリオ"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import html
import unicodedata
from datetime import datetime
from config import BROKER_OPTIONS, TAX_OPTIONS, MARKET_OPTIONS, CURRENCY_OPTIONS, ACCT_BADGE_MAP, NISA_GROWTH_ANNUAL, NISA_TSUMITATE_ANNUAL
from data import load_data, save_data, load_history, _clear_sheet_cache, load_transactions
from market import get_ticker_name, get_cached_market_data, get_stock_detail, get_benchmark_history
from calc import round_up_3, safe_csv_df, calc_risk_metrics
from tabs import card, colored_card, pnl_color, pnl_sign
import jquants


def render(tab, df, display_df, totals):
    TA = totals["total_asset"]
    with tab:
        # ── 銘柄追加フォーム ──
        st.markdown("#### ➕ 銘柄を追加")
        with st.form("add_stock_form", clear_on_submit=True):
            r1a, r1b, r1c, r1d = st.columns([1, 0.6, 1, 2])
            with r1a: market = st.selectbox("市場", MARKET_OPTIONS, key="fm")
            with r1b: currency = st.selectbox("通貨", CURRENCY_OPTIONS, key="fcy")
            with r1c: code = st.text_input("証券コード", placeholder="例: 7203", key="fc")
            with r1d: manual_name = st.text_input("銘柄名", key="fn", placeholder="自動取得 or 手動入力")
            r2a, r2b, r2c, r2d, r2e = st.columns(5)
            with r2a: shares = st.number_input("保有数", min_value=0.0001, max_value=100_000_000.0, value=100.0, key="fs")
            with r2b: avg_price = st.number_input("取得単価", min_value=0.0, max_value=100_000_000.0, value=0.0, key="fp")
            with r2c: annual_div = st.number_input("年間配当金(円/株)", min_value=0.0, max_value=1_000_000.0, value=0.0, step=1.0, key="fd")
            with r2d: broker = st.selectbox("口座", BROKER_OPTIONS, key="fb")
            with r2e: tax = st.selectbox("口座区分", TAX_OPTIONS, key="ft")
            r3a, r3b, r3c = st.columns([1.5, 1.5, 1.5])
            with r3a: div_month_sel = st.multiselect("配当月", options=list(range(1, 13)),
                                                      format_func=lambda x: f"{x}月", key="fdm")
            with r3b: buy_fx = st.number_input("取得時為替 (米国株)", min_value=0.0, max_value=1000.0, value=0.0, step=0.1, key="ffx")
            with r3c: buy_date = st.date_input("取得日", value=None, key="fbd")
            submitted = st.form_submit_button("＋ 追加", width="stretch")

        if submitted and code:
            auto_name = ""
            if not manual_name and market in ["日本株", "米国株"]:
                with st.spinner("銘柄名を取得中..."):
                    auto_name = get_ticker_name(code, market)
            final_name = manual_name or auto_name or code
            div_months_str = ",".join(str(m) for m in sorted(div_month_sel))
            buy_date_str = buy_date.strftime("%Y/%m/%d") if buy_date else ""
            # 同一銘柄 + 同一口座 + 同一口座区分 → 合算（平均取得単価を再計算）
            match_idx = df[
                (df["銘柄コード"].astype(str) == str(code))
                & (df["口座"] == broker)
                & (df["口座区分"] == tax)
            ].index
            if len(match_idx) > 0:
                i = match_idx[0]
                cur_shares = float(df.at[i, "保有株数"])
                cur_price = float(df.at[i, "取得単価"])
                new_total = cur_shares + shares
                df.at[i, "取得単価"] = (cur_shares * cur_price + shares * avg_price) / new_total if new_total > 0 else avg_price
                df.at[i, "保有株数"] = new_total
                if annual_div > 0:
                    df.at[i, "年間配当金(円/株)"] = annual_div
                if div_months_str:
                    df.at[i, "配当月"] = div_months_str
                if buy_fx > 0:
                    df.at[i, "取得時為替"] = buy_fx
                df.at[i, "最新更新日"] = datetime.now().strftime("%Y/%m/%d %H:%M")
                save_data(df)
                _clear_sheet_cache()
                st.success(f"✓ {final_name} を既存保有に合算（{cur_shares:,.4g} + {shares:,.4g} = {new_total:,.4g}株）")
                st.rerun()
            else:
                # 別口座/口座区分 or 新規銘柄 → 別立てで追加
                new = pd.DataFrame({"銘柄コード": [code], "銘柄名": [final_name], "市場": [market], "通貨": [currency],
                    "保有株数": [shares], "取得単価": [avg_price], "口座": [broker], "口座区分": [tax],
                    "手動配当利回り(%)": [0.0], "配当月": [div_months_str], "年間配当金(円/株)": [annual_div],
                    "取得時為替": [buy_fx], "取得日": [buy_date_str], "最新更新日": [datetime.now().strftime("%Y/%m/%d %H:%M")]})
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
                    st.markdown(f"<div class='status-card' style='padding:0.8rem'><h4><span class='acct-badge {bc}'>{html.escape(str(r['口座']))}</span> {int(r['銘柄コード'])}銘柄</h4>"
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

            # ── NISA枠消化状況（今年・取引履歴の取得対価ベース） ──
            try:
                _tx = load_transactions()
            except Exception:
                _tx = pd.DataFrame()
            if not _tx.empty and "口座区分" in _tx.columns:
                _tx = _tx.copy()
                _tx["_d"] = pd.to_datetime(_tx["日付"], errors="coerce")
                _yr = datetime.now().year
                _kbn = _tx["口座区分"].astype(str)
                _buy = _tx[_tx["取引種別"].isin(["買い増し", "新規購入"]) &
                           _kbn.str.contains("NISA", na=False) &
                           (_tx["_d"].dt.year == _yr)].copy()
                if not _buy.empty:
                    _buy["_amt"] = _buy["数量"] * _buy["単価(円)"]  # 取得対価（枠は手数料を含めない）
                    # 投信は数量=口数・単価=基準価額(1万口あたり)のため1万で割って円換算。
                    # 取引履歴の投信行は市場列が「-」・銘柄コード空のことがあるため多重条件で判定:
                    #  ①市場=投資信託 ②つみたて枠(制度上投信のみ)
                    #  ③銘柄コードが数字でない行で銘柄名にファンド/インデックス(NFKC正規化後)
                    _code = _buy["銘柄コード"].astype(str).str.strip()
                    _norm = _buy["銘柄名"].astype(str).map(lambda s: unicodedata.normalize("NFKC", s))
                    _fund = (
                        (_buy["市場"].astype(str) == "投資信託")
                        | _buy["口座区分"].astype(str).str.contains("積立", na=False)
                        | (~_code.str.match(r"^\d") & _norm.str.contains("ファンド|インデックス", na=False))
                    )
                    _buy.loc[_fund, "_amt"] = _buy.loc[_fund, "_amt"] / 10000
                    _bk = _buy["口座区分"].astype(str)
                    g_used = _buy[_bk.str.contains("成長", na=False)]["_amt"].sum()
                    t_used = _buy[_bk.str.contains("積立", na=False)]["_amt"].sum()
                    st.markdown(f"##### 🎫 NISA枠消化状況（{_yr}年）")
                    q1, q2 = st.columns(2)
                    for _col, _label, _used, _limit, _color in [
                        (q1, "成長投資枠", g_used, NISA_GROWTH_ANNUAL, "#69F0AE"),
                        (q2, "つみたて投資枠", t_used, NISA_TSUMITATE_ANNUAL, "#00D2FF"),
                    ]:
                        with _col:
                            _pct = min(_used / _limit * 100, 100) if _limit > 0 else 0
                            _remain = max(_limit - _used, 0)
                            st.markdown(
                                f"<div class='status-card' style='padding:0.8rem;border-left:3px solid {_color}'>"
                                f"<h4>{_label}（年{int(_limit/10000):,}万円）</h4>"
                                f"<p class='mv' style='font-size:1.2rem;color:{_color}'>{_used:,.0f}<span>円 消化</span></p>"
                                f"<div style='background:#1E232F;border-radius:6px;height:8px;margin:0.4rem 0'>"
                                f"<div style='background:{_color};width:{_pct:.0f}%;height:8px;border-radius:6px'></div></div>"
                                f"<p class='sv'>{_pct:.0f}% 消化 · 残枠 {_remain:,.0f}円</p>"
                                f"</div>", unsafe_allow_html=True)
                    st.caption("※ 取引履歴の買い増し/新規購入・NISA口座の取得対価ベース。手数料・分配金再投資は枠計算に含めていないわ。〔計算版: 2026-07-02c 投信判定を多重条件化〕")

        # ── 保有一覧 ──
        if not df.empty and not display_df.empty:
            st.markdown("---"); st.markdown("#### 📋 保有銘柄一覧")
            cpf = lambda v: f"color: {'#00E676' if v >= 0 else '#FF5252'}"
            cpc = lambda v: "" if pd.isna(v) else f"color: {'#00E676' if v > 0 else '#FF5252' if v < 0 else '#E0E0E0'}"
            fp = lambda v: "-" if pd.isna(v) else (f"+{v:.1f}%" if v > 0 else f"{v:.1f}%")
            show = ["銘柄コード", "銘柄名", "市場", "口座", "口座区分", "保有株数", "取得日", "取得単価(円)", "現在値(円)", "前日比", "評価額(円)", "税引後損益(円)", "予想配当(円)", "実質利回り(%)"]
            ac = [c for c in show if c in display_df.columns]
            fmt = {"保有株数": round_up_3, "取得単価(円)": round_up_3, "現在値(円)": round_up_3, "前日比": fp,
                   "評価額(円)": "{:,.0f}", "税引後損益(円)": "{:,.0f}", "予想配当(円)": "{:,.0f}", "実質利回り(%)": "{:.2f}%"}
            show_df = display_df[ac].copy()
            show_df.index = range(len(show_df))
            event = st.dataframe(
                show_df.style
                    .map(cpf, subset=["税引後損益(円)"] if "税引後損益(円)" in ac else [])
                    .map(cpc, subset=["前日比"] if "前日比" in ac else [])
                    .format({k: v for k, v in fmt.items() if k in ac}),
                width='stretch', hide_index=True,
                on_select="rerun", selection_mode="single-row", key="stock_table")

            # ── 銘柄詳細 ──
            st.markdown("---"); st.markdown("#### 🔎 銘柄詳細")
            sel_rows = event.selection.rows if event.selection.rows else []
            sel = sel_rows[0] if sel_rows else None
            st.caption("↑ テーブルの行をクリックして銘柄を選択")
            if sel is not None:
                row = display_df.iloc[sel]
                code_raw = str(row["銘柄コード"])
                market_type = row["市場"]
                shares_val = float(row["保有株数"])
                buy_price = float(row.get("取得単価(円)", row.get("取得単価", 0)))
                buy_date_str = str(row.get("取得日", "")) if "取得日" in row.index else ""

                # 銘柄サマリーカード
                pc = pnl_color(row.get("税引後損益(円)", 0)); ps = pnl_sign(row.get("税引後損益(円)", 0))
                dod = row.get("前日比", None)
                dod_s = f"前日比 {dod:+.2f}%" if pd.notna(dod) else ""
                st.markdown(
                    f"<div class='status-card' style='padding:1rem;border-left:3px solid #00D2FF'>"
                    f"<h4>{html.escape(code_raw)} {html.escape(str(row['銘柄名']))} [{html.escape(str(market_type))}]</h4>"
                    f"<p class='mv'>現在値 {row.get('現在値(円)', 0):,.1f}<span>円</span>　"
                    f"<span style='font-size:0.9rem;color:{pc}'>{ps}{row.get('税引後損益(円)', 0):,.0f}円</span></p>"
                    f"<p class='sv'>取得単価 {buy_price:,.1f}円 · {shares_val:,.4g}株 · {dod_s}"
                    f"{' · 取得日 ' + buy_date_str if buy_date_str else ''}</p>"
                    f"</div>", unsafe_allow_html=True)

                # 指標カード
                if market_type in ("日本株", "米国株"):
                    try:
                        detail = get_stock_detail(code_raw, market_type)
                    except Exception:
                        detail = {}
                    def _fv(v, fmt="{:,.2f}"):
                        return fmt.format(v) if v is not None else "-"
                    ccy = "$" if market_type == "米国株" else "¥"
                    _tip = {
                        "前日終値": "前営業日の市場終了時の株価",
                        "配当利回り": "年間配当金 ÷ 株価 x 100。高いほど配当収入が多い",
                        "1株配当": "1株あたりの年間配当金額",
                        "PER": "株価収益率(Price Earnings Ratio)。株価 ÷ EPS。低いほど割安の目安",
                        "PBR": "株価純資産倍率(Price Book-value Ratio)。株価 ÷ BPS。1倍未満は解散価値以下",
                        "EPS": "1株当たり純利益(Earnings Per Share)。当期純利益 ÷ 発行済株式数",
                        "BPS": "1株当たり純資産(Book-value Per Share)。純資産 ÷ 発行済株式数",
                        "ROE": "自己資本利益率(Return On Equity)。当期純利益 ÷ 自己資本 x 100。経営効率の指標",
                    }
                    def _h4(label, mt=False):
                        tip = _tip.get(label, "")
                        ms = "margin-top:0.4rem;" if mt else ""
                        return "<h4 title='" + tip + "' style='" + ms + "cursor:help'>" + label + "</h4>"
                    # detail が空でも display_df から取れる値で埋める
                    _prev = _fv(detail.get("前日終値") if detail else None)
                    _dy_val = detail.get("配当利回り(%)") if detail else row.get("実質利回り(%)", None)
                    _dy = _fv(_dy_val)
                    _div_val = detail.get("1株配当") if detail else None
                    _div = _fv(_div_val)
                    _per = _fv(detail.get("PER") if detail else None)
                    _pbr = _fv(detail.get("PBR") if detail else None)
                    _eps = _fv(detail.get("EPS") if detail else None)
                    _bps = _fv(detail.get("BPS") if detail else None)
                    _roe = _fv(detail.get("ROE(%)") if detail else None)
                    _next_e = (detail.get("次回決算発表") if detail else None) or "-"
                    _q_end = (detail.get("直近四半期末") if detail else None) or "-"
                    dk = st.columns(4)
                    with dk[0]:
                        st.markdown(
                            "<div class='status-card' style='padding:0.6rem'>"
                            + _h4("前日終値") + "<p class='mv' style='font-size:1rem'>" + ccy + _prev + "</p>"
                            + _h4("配当利回り", mt=True) + "<p class='mv' style='font-size:1rem'>" + _dy + "%</p>"
                            + "</div>", unsafe_allow_html=True)
                    with dk[1]:
                        st.markdown(
                            "<div class='status-card' style='padding:0.6rem'>"
                            + _h4("1株配当") + "<p class='mv' style='font-size:1rem'>" + ccy + _div + "</p>"
                            + _h4("PER", mt=True) + "<p class='mv' style='font-size:1rem'>" + _per + "倍</p>"
                            + "</div>", unsafe_allow_html=True)
                    with dk[2]:
                        st.markdown(
                            "<div class='status-card' style='padding:0.6rem'>"
                            + _h4("PBR") + "<p class='mv' style='font-size:1rem'>" + _pbr + "倍</p>"
                            + _h4("EPS", mt=True) + "<p class='mv' style='font-size:1rem'>" + ccy + _eps + "</p>"
                            + "</div>", unsafe_allow_html=True)
                    with dk[3]:
                        st.markdown(
                            "<div class='status-card' style='padding:0.6rem'>"
                            + _h4("BPS") + "<p class='mv' style='font-size:1rem'>" + ccy + _bps + "</p>"
                            + _h4("ROE", mt=True) + "<p class='mv' style='font-size:1rem'>" + _roe + "%</p>"
                            + "<h4 style='margin-top:0.4rem'>次回決算発表</h4><p class='mv' style='font-size:0.9rem'>" + _next_e + "</p>"
                            + "<p class='sv'>四半期末 " + _q_end + "</p>"
                            + "</div>", unsafe_allow_html=True)

                # リスク指標ダッシュボード（日本株のみ、TOPIX対比）
                if market_type == "日本株":
                    try:
                        ticker_jp = f"{code_raw}.T"
                        risk_closes = get_cached_market_data(tuple(sorted([ticker_jp])), period="1y")
                        topix_df = jquants.get_topix_ohlc(period_days=400)
                        asset_series = risk_closes[ticker_jp].dropna() if ticker_jp in risk_closes.columns else pd.Series(dtype=float)
                        topix_series = topix_df.set_index("Date")["Close"] if (not topix_df.empty and "Close" in topix_df.columns) else None
                        rm = calc_risk_metrics(asset_series, topix_series)
                        if any(v is not None for v in rm.values()):
                            st.markdown("##### 📐 リスク指標（1年）")
                            def _rv(v, suffix="", fmt="{:+.2f}"):
                                return f"{fmt.format(v)}{suffix}" if v is not None else "-"
                            _tip_risk = {
                                "HV20": "20日ヒストリカルボラティリティ。日次リターン標準偏差の年率換算(%)",
                                "HV60": "60日ヒストリカルボラティリティ。長めの値動きの大きさ",
                                "β (vs TOPIX)": "TOPIX変動1%に対する銘柄変動率。1.0=同等、>1.3=高ベータ",
                                "MDD": "最大ドローダウン。期間中の高値からの最大下落幅(%)",
                                "シャープ": "シャープレシオ(年率)。リターン÷リスク、1.0超で優秀",
                                "TOPIX相対": "期間始点から見たTOPIX対比の超過リターン(ppt)",
                            }
                            _vals = [
                                ("HV20", _rv(rm.get("HV20"), "%", "{:.1f}")),
                                ("HV60", _rv(rm.get("HV60"), "%", "{:.1f}")),
                                ("β (vs TOPIX)", _rv(rm.get("beta"), "", "{:.2f}")),
                                ("MDD", _rv(rm.get("MDD"), "%", "{:.1f}")),
                                ("シャープ", _rv(rm.get("Sharpe"), "", "{:.2f}")),
                                ("TOPIX相対", _rv(rm.get("relative_perf"), "ppt", "{:+.1f}")),
                            ]
                            rcols = st.columns(6)
                            for ci, (lbl, val) in enumerate(_vals):
                                with rcols[ci]:
                                    tip = _tip_risk.get(lbl, "")
                                    st.markdown(
                                        f"<div class='status-card' style='padding:0.6rem'>"
                                        f"<h4 title='{tip}' style='cursor:help'>{lbl}</h4>"
                                        f"<p class='mv' style='font-size:1rem'>{val}</p>"
                                        f"</div>", unsafe_allow_html=True)
                    except Exception as e:
                        st.caption(f"リスク指標の計算でエラー: {e}")

                # 株価チャート（取得日〜現在）
                if market_type in ("日本株", "米国株"):
                    ticker = f"{code_raw}.T" if market_type == "日本株" else code_raw
                    # 取得日からの期間を計算
                    chart_period = "1y"
                    if buy_date_str:
                        try:
                            bd = pd.to_datetime(buy_date_str)
                            days_held = (pd.Timestamp.now() - bd).days
                            if days_held > 1800: chart_period = "max"
                            elif days_held > 365: chart_period = f"{min(days_held + 30, 3650)}d"
                        except Exception:
                            pass
                    # 株価データ取得
                    try:
                        chart_closes = get_cached_market_data(tuple(sorted([ticker, "JPY=X"])), period=chart_period)
                        if ticker in chart_closes.columns:
                            cs = chart_closes[ticker].dropna()
                            # 取得日でフィルタ
                            if buy_date_str:
                                try:
                                    bd = pd.to_datetime(buy_date_str)
                                    cs = cs[cs.index >= bd]
                                except Exception:
                                    pass
                            if len(cs) >= 2:
                                cost_total = buy_price * shares_val
                                eval_series = cs * shares_val
                                if market_type == "米国株" and "JPY=X" in chart_closes.columns:
                                    fx = chart_closes["JPY=X"].reindex(cs.index, method="ffill").fillna(150)
                                    eval_series = cs * shares_val * fx
                                    cost_total = buy_price * shares_val  # 取得単価(円)は既に円建て

                                fig_d = go.Figure()
                                fig_d.add_trace(go.Scatter(
                                    x=cs.index, y=eval_series, mode="lines",
                                    name="評価額", line=dict(color="#00D2FF", width=2),
                                    fill="tonexty" if False else None))
                                fig_d.add_trace(go.Scatter(
                                    x=[cs.index[0], cs.index[-1]], y=[cost_total, cost_total],
                                    mode="lines", name="元本",
                                    line=dict(color="#FFD54F", width=1.5, dash="dash")))
                                # 元本との差を塗りつぶし
                                fig_d.add_trace(go.Scatter(
                                    x=cs.index, y=[cost_total] * len(cs), mode="lines",
                                    line=dict(width=0), showlegend=False))
                                fig_d.add_trace(go.Scatter(
                                    x=cs.index, y=eval_series, mode="lines",
                                    line=dict(width=0), showlegend=False,
                                    fill="tonexty",
                                    fillcolor="rgba(0,210,255,0.08)"))

                                latest_eval = eval_series.iloc[-1]
                                pnl_val = latest_eval - cost_total
                                pnl_pct = (pnl_val / cost_total * 100) if cost_total > 0 else 0
                                pc2 = pnl_color(pnl_val); ps2 = pnl_sign(pnl_val)

                                fig_d.update_layout(
                                    plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                                    margin=dict(t=30, b=10, l=10, r=10), height=350,
                                    title=dict(text=f"損益 {ps2}{pnl_val:,.0f}円 ({ps2}{pnl_pct:.1f}%)",
                                               font=dict(color=pc2, size=14)),
                                    xaxis=dict(showgrid=True, gridcolor="#1E232F"),
                                    yaxis=dict(showgrid=True, gridcolor="#1E232F", tickformat=","),
                                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
                                st.plotly_chart(fig_d, use_container_width=True)
                            else:
                                st.info("株価データが不足しています。")
                        else:
                            st.info("この銘柄の株価データを取得できませんでした。")
                    except Exception as e:
                        st.warning(f"チャート生成エラー: {e}")
                else:
                    st.caption("投資信託・その他資産は株価チャート非対応です。")

                # 業績推移（日本株のみ、J-Quants財務サマリ時系列）
                if market_type == "日本株":
                    try:
                        fin_hist = jquants.get_fin_statements_history(code_raw, limit=8)
                        if fin_hist is not None and not fin_hist.empty:
                            st.markdown("##### 📈 業績推移（過去8期分）")
                            date_col = "DiscDate" if "DiscDate" in fin_hist.columns else "DisclosedDate"
                            period_col = "TypeOfCurrentPeriod" if "TypeOfCurrentPeriod" in fin_hist.columns else None
                            metric_map = {
                                "NetSales": "売上",
                                "OperatingProfit": "営業利益",
                                "Profit": "純利益",
                                "EarningsPerShare": "EPS",
                            }
                            available_metrics = [(k, v) for k, v in metric_map.items() if k in fin_hist.columns]
                            if available_metrics:
                                for k, _ in available_metrics:
                                    fin_hist[k] = pd.to_numeric(fin_hist[k], errors="coerce")
                                xlabel = fin_hist[date_col].dt.strftime("%Y/%m")
                                if period_col:
                                    xlabel = xlabel + " (" + fin_hist[period_col].astype(str) + ")"
                                fig_e = go.Figure()
                                colors_e = ["#00D2FF", "#69F0AE", "#FFD54F", "#FF8F00"]
                                for ci, (k, label) in enumerate(available_metrics):
                                    yvals = fin_hist[k]
                                    if k == "EarningsPerShare":
                                        fig_e.add_trace(go.Scatter(
                                            x=xlabel, y=yvals, mode="lines+markers",
                                            name=label, yaxis="y2",
                                            line=dict(color=colors_e[ci], width=2, dash="dot"),
                                            marker=dict(size=7)))
                                    else:
                                        fig_e.add_trace(go.Bar(
                                            x=xlabel, y=yvals / 1e8,
                                            name=label, marker_color=colors_e[ci]))
                                fig_e.update_layout(
                                    plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                                    margin=dict(t=10, b=10, l=10, r=10), height=320, barmode="group",
                                    xaxis=dict(showgrid=False, tickfont=dict(size=10)),
                                    yaxis=dict(title=dict(text="売上/利益 (億円)", font=dict(size=11)),
                                               showgrid=True, gridcolor="#1E232F"),
                                    yaxis2=dict(title=dict(text="EPS (円)", font=dict(size=11)),
                                                overlaying="y", side="right", showgrid=False),
                                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
                                st.plotly_chart(fig_e, width="stretch", config={"displayModeBar": False})

                                # 業績修正検出：予想 vs 実績、もしくは予想の更新
                                rev_msgs = []
                                if "ForecastNetSales" in fin_hist.columns and "NetSales" in fin_hist.columns:
                                    last = fin_hist.iloc[-1]
                                    fc, ac = pd.to_numeric(last.get("ForecastNetSales"), errors="coerce"), pd.to_numeric(last.get("NetSales"), errors="coerce")
                                    if pd.notna(fc) and pd.notna(ac) and fc > 0:
                                        diff = (ac / fc - 1) * 100
                                        if abs(diff) >= 3:
                                            rev_msgs.append(f"{'🟢 上振れ' if diff > 0 else '🔴 下振れ'}：直近期の売上が予想比 {diff:+.1f}%")
                                if "ForecastProfit" in fin_hist.columns and len(fin_hist) >= 2:
                                    prev_fc = pd.to_numeric(fin_hist.iloc[-2].get("ForecastProfit"), errors="coerce")
                                    curr_fc = pd.to_numeric(fin_hist.iloc[-1].get("ForecastProfit"), errors="coerce")
                                    if pd.notna(prev_fc) and pd.notna(curr_fc) and prev_fc != 0:
                                        rev = (curr_fc / abs(prev_fc) - (1 if prev_fc > 0 else -1)) * 100
                                        if abs(rev) >= 5:
                                            rev_msgs.append(f"{'🟢 通期純利益予想を上方修正' if rev > 0 else '🔴 通期純利益予想を下方修正'}：前回比 {rev:+.1f}%")
                                if rev_msgs:
                                    st.markdown("**業績修正検出**")
                                    for m in rev_msgs:
                                        st.markdown(f"- {m}")
                    except Exception as e:
                        st.caption(f"業績推移の取得でエラー: {e}")

            # CSV出力
            st.markdown("---"); st.markdown("#### 📥 データエクスポート")
            ec1, ec2, ec3 = st.columns(3)
            with ec1:
                csv_c = ["銘柄コード", "銘柄名", "市場", "口座", "口座区分", "保有株数", "取得単価(円)", "現在値(円)", "評価額(円)", "含み損益(円)", "税引後損益(円)", "予想配当(円)", "税引後配当(円)", "セクター"]
                st.download_button("📋 保有銘柄一覧", safe_csv_df(display_df[[c for c in csv_c if c in display_df.columns]]).to_csv(index=False).encode("utf-8-sig"),
                                   f"portfolio_{datetime.now():%Y%m%d}.csv", "text/csv", width="stretch")
            with ec2:
                dr = [{"銘柄コード": r["銘柄コード"], "銘柄名": r["銘柄名"], "口座": r.get("口座", ""), "口座区分": r.get("口座区分", ""),
                       "予想配当(税引前)": round(r["予想配当(円)"]), "税引後配当": round(r.get("税引後配当(円)", 0)), "配当月": r.get("配当月", "")}
                      for _, r in display_df.iterrows() if r.get("予想配当(円)", 0) > 0]
                if dr: st.download_button("💰 配当明細", safe_csv_df(pd.DataFrame(dr)).to_csv(index=False).encode("utf-8-sig"), f"dividends_{datetime.now():%Y%m%d}.csv", "text/csv", width="stretch")
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
                    "通貨": st.column_config.SelectboxColumn("通貨", options=CURRENCY_OPTIONS, required=True),
                    "保有株数": st.column_config.NumberColumn("保有株数", min_value=0, format="%.4f"),
                    "取得単価": st.column_config.NumberColumn("取得単価", min_value=0, format="%.2f"),
                    "手動配当利回り(%)": st.column_config.NumberColumn("手動利回り(%)", min_value=0, format="%.2f"),
                    "年間配当金(円/株)": st.column_config.NumberColumn("年間配当(円/株)", min_value=0, format="%.2f"),
                    "取得時為替": st.column_config.NumberColumn("取得時為替($/¥)", min_value=0, format="%.1f"),
                    "取得日": st.column_config.TextColumn("取得日"),
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

                    # ── ベンチマーク比較（指数化・円換算でαを可視化） ──
                    if len(hdf_f) >= 2:
                        _tmap = {"オルカン(ACWI)": "ACWI", "S&P 500": "^GSPC"}
                        bsel = st.multiselect("📊 ベンチマーク比較（期間開始=100に指数化）",
                                              list(_tmap.keys()), default=["オルカン(ACWI)"], key="hbench")
                        if bsel:
                            need = tuple([_tmap[b] for b in bsel] + ["JPY=X"])
                            bdf = get_benchmark_history(need, "2y")
                            if not bdf.empty and "JPY=X" in bdf.columns:
                                bdf = bdf.copy(); bdf.index = pd.to_datetime(bdf.index)
                                start_d, end_d = hdf_f["日付_dt"].iloc[0], hdf_f["日付_dt"].iloc[-1]
                                win = bdf[(bdf.index >= start_d) & (bdf.index <= end_d)]
                                pf0 = hdf_f["総資産額(円)"].iloc[0]
                                figc = go.Figure()
                                figc.add_trace(go.Scatter(x=hdf_f["日付_dt"], y=hdf_f["総資産額(円)"] / pf0 * 100,
                                                          mode="lines+markers", name="あなたの評価額",
                                                          line=dict(color="#00E676", width=2)))
                                alphas = []
                                _bcolors = {"オルカン(ACWI)": "#FFD54F", "S&P 500": "#00D2FF"}
                                for b in bsel:
                                    tk = _tmap[b]
                                    if tk not in win.columns:
                                        continue
                                    jpy = (win[tk] * win["JPY=X"]).dropna()
                                    if len(jpy) < 2:
                                        continue
                                    norm = jpy / jpy.iloc[0] * 100
                                    figc.add_trace(go.Scatter(x=norm.index, y=norm.values, mode="lines",
                                                              name=f"{b}(円換算)", line=dict(color=_bcolors.get(b, "#B0B8C0"), width=1.5)))
                                    alphas.append((b, float(norm.iloc[-1] - 100)))
                                figc.update_layout(plot_bgcolor="#0A0E13", paper_bgcolor="#0A0E13", font_color="#E0E0E0",
                                                   margin=dict(t=10, b=10, l=10, r=10), height=300,
                                                   xaxis=dict(showgrid=True, gridcolor="#1E232F"),
                                                   yaxis=dict(title="指数(開始=100)", showgrid=True, gridcolor="#1E232F"),
                                                   legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, bgcolor="rgba(0,0,0,0)"))
                                st.plotly_chart(figc, width='stretch')
                                pf_ret = (hdf_f["総資産額(円)"].iloc[-1] / pf0 - 1) * 100 if pf0 > 0 else 0
                                for b, bret in alphas:
                                    alpha = pf_ret - bret
                                    ac = pnl_color(alpha); asign = pnl_sign(alpha)
                                    st.markdown(f"<span style='font-size:0.85rem'>{b}対比 α: "
                                                f"<b style='color:{ac}'>{asign}{alpha:.2f}pt</b> "
                                                f"（あなた {pf_ret:+.2f}% vs {b} {bret:+.2f}%）</span>", unsafe_allow_html=True)
                                st.caption("※ ベンチマークはETF(ACWI/S&P500)を円換算し期間開始=100に指数化した簡易比較。投信オルカンの基準価額とは厳密には一致しないわ。")
                            else:
                                st.caption("ベンチマーク価格を取得できませんでした。")
                else: st.info("選択期間内に記録がありません。")
            else: st.info("ヘッダーの「💾 記録」で記録を開始してください。")
