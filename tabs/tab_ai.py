"""TAB 7: AI総評（履歴蓄積＋過去分析を文脈に含める）"""
import streamlit as st
from datetime import datetime
from zoneinfo import ZoneInfo
from config import AI_MODEL
from data import load_ai_review, load_ai_review_history, save_ai_review, load_history
from calc import build_portfolio_summary_text

_JST = ZoneInfo("Asia/Tokyo")


def _build_history_context(history):
    """過去の分析履歴をプロンプト用テキストに変換"""
    if not history:
        return ""
    lines = ["\n■ 過去の分析レポート（直近、古い順）"]
    for dt, text in history:
        # 各レポートを要約的に含める（長すぎる場合は先頭800文字に制限）
        truncated = text[:800] + "..." if len(text) > 800 else text
        lines.append(f"\n--- {dt} の分析 ---\n{truncated}")
    lines.append("\n※上記の過去分析を踏まえ、前回からの変化点・改善点・悪化点を指摘してください。")
    return "\n".join(lines)


def render(tab, df, display_df, totals, jpy_usd_rate):
    TA = totals["total_asset"]
    with tab:
        st.markdown("#### 🤖 Claudeによるポートフォリオ総評")
        if df.empty or TA <= 0 or display_df.empty:
            st.info("銘柄を追加するとAI総評を利用できます。"); return

        api_key = st.secrets.get("anthropic_api_key", "")
        if not api_key:
            st.warning("⚠ Streamlit Secretsに `anthropic_api_key` を設定してください。"); return

        ptxt = build_portfolio_summary_text(display_df, totals, jpy_usd_rate, history_df=load_history())

        # セッション初期化
        for k, v in [("ai_review_dt", None), ("ai_review_text", ""), ("ai_review_loaded", False), ("ai_confirm_regen", False)]:
            if k not in st.session_state: st.session_state[k] = v
        if not st.session_state.ai_review_loaded:
            try: d, t = load_ai_review(); st.session_state.ai_review_dt = d; st.session_state.ai_review_text = t
            except Exception: pass
            st.session_state.ai_review_loaded = True

        sdt, stx = st.session_state.ai_review_dt, st.session_state.ai_review_text

        # ── 最新レポート表示 ──
        if stx and sdt:
            try:
                sd = datetime.strptime(sdt, "%Y/%m/%d %H:%M"); ha = (datetime.now(_JST) - sd.replace(tzinfo=_JST)).total_seconds() / 3600
                tl = f"{ha:.1f}時間前" if ha < 48 else f"{ha/24:.0f}日前"
            except Exception: tl = ""
            st.markdown(f"<div style='background:#12161E;border:1px solid #1E232F;border-radius:12px;padding:1.5rem;border-left:3px solid #00D2FF'>"
                        f"<div style='color:#00D2FF;font-weight:700;margin-bottom:0.8rem'>🤖 Claude分析レポート</div>"
                        f"<div style='color:#B0B8C0;font-size:0.75rem;margin-bottom:1rem'>{sdt}時点（{tl}）</div></div>", unsafe_allow_html=True)
            st.markdown(stx); st.caption("⚠ AIによる参考情報。投資助言ではありません。"); st.markdown("---")

        # ── 生成ボタン ──
        need_confirm = False
        if sdt:
            try:
                sd = datetime.strptime(sdt, "%Y/%m/%d %H:%M")
                if (datetime.now(_JST) - sd.replace(tzinfo=_JST)).total_seconds() < 86400: need_confirm = True
            except Exception: pass

        if need_confirm and not st.session_state.ai_confirm_regen:
            ha = (datetime.now(_JST) - sd.replace(tzinfo=_JST)).total_seconds() / 3600
            st.info(f"⏱ {ha:.1f}時間前に生成済み。再生成でAPIクレジット消費。")
            if st.button("🔄 それでも再生成する", use_container_width=True, key="aic"):
                st.session_state.ai_confirm_regen = True; st.rerun()
        else:
            bl = "🔄 再生成" if stx else "📝 AI総評を生成"
            if st.button(bl, use_container_width=True, key="aig"):
                st.session_state.ai_confirm_regen = False
                with st.spinner("Claudeが分析中...（20〜30秒）"):
                    try:
                        import requests as req, time as _time

                        # 過去の分析履歴を取得してプロンプトに含める
                        past_reviews = load_ai_review_history(10)
                        history_context = _build_history_context(past_reviews)

                        prompt = (
                            f"あなたは日本の個人投資家向けポートフォリオアドバイザーです。以下を分析し日本語でレポートを作成。\n"
                            f"{ptxt}\n"
                            f"{history_context}\n\n"
                            f"以下の観点で分析:\n"
                            f"1.全体評価(5段階) 2.強みと弱み 3.市場環境との整合性 4.配当戦略の評価 5.アクション提案(3〜5つ,優先度付き)\n"
                        )
                        if past_reviews:
                            prompt += "6.前回からの変化点（改善/悪化/新たなリスク）\n"
                        prompt += "注意: 投資助言ではなく参考情報です。"

                        MAX_RETRIES, resp = 3, None
                        for attempt in range(MAX_RETRIES):
                            resp = req.post("https://api.anthropic.com/v1/messages",
                                            headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
                                            json={"model": AI_MODEL, "max_tokens": 2000, "messages": [{"role": "user", "content": prompt}]}, timeout=60)
                            if resp.status_code == 200: break
                            if resp.status_code in (429, 529, 500, 502, 503) and attempt < MAX_RETRIES - 1:
                                _time.sleep(2 ** attempt * 2); continue
                            break
                        if resp.status_code == 200:
                            ai_text = "".join(b["text"] for b in resp.json()["content"] if b["type"] == "text")
                            ns = datetime.now(_JST).strftime("%Y/%m/%d %H:%M")
                            st.session_state.ai_review_dt = ns; st.session_state.ai_review_text = ai_text
                            save_ai_review(ns, ai_text); st.rerun()
                        else: st.error(f"API エラー (HTTP {resp.status_code}): {resp.json().get('error', {}).get('message', resp.text)}")
                    except Exception as e: st.error(f"エラー: {e}")

        # ── 送信データプレビュー ──
        with st.expander("📄 送信データプレビュー", expanded=False): st.code(ptxt, language="text")

        # ── 過去の分析履歴 ──
        past = load_ai_review_history(10)
        if len(past) > 1:
            st.markdown("---"); st.markdown("#### 📚 過去の分析履歴")
            for dt, text in reversed(past[:-1]):  # 最新は上に表示済みなので除外、新しい順
                with st.expander(f"📋 {dt}", expanded=False):
                    st.markdown(text)