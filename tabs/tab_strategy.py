"""TAB: 戦略バックテスト vs ベンチマーク

stock_backtest プロジェクトで毎月生成される strategy_performance.json を読み込み、
戦略NAV / オルカン / S&P500 の比較を表示する。

データソース: /strategy_performance.json (毎月1日 19:00 更新)
"""
import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


JSON_PATH = Path(__file__).resolve().parent.parent / "strategy_performance.json"


def _load_perf():
    if not JSON_PATH.exists():
        return None
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _fmt_pct(x):
    if x is None:
        return "—"
    return f"{x*100:+.2f}%"


def _fmt_num(x, dec=2):
    if x is None:
        return "—"
    return f"{x:.{dec}f}"


def render(tab):
    with tab:
        st.subheader("📈 戦略バックテスト vs ベンチマーク")

        perf = _load_perf()
        if perf is None:
            st.warning("strategy_performance.json が見つかりません。"
                        "毎月1日 19:00 に自動更新されます。")
            return

        # ヘッダー
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("BT期間", f"{perf['period']['start']} 〜 {perf['period']['end']}")
        with col2:
            st.metric("初期投資額", f"¥{int(perf['initial']):,}")
        with col3:
            st.metric("最終更新", perf['updated_at'][:16].replace("T", " "))

        st.markdown("---")

        # メトリクス比較表
        st.markdown("#### メトリクス比較")
        metrics_data = {
            "指標": ["総リターン", "CAGR (年率)", "MaxDrawdown", "Sharpe比"],
            "戦略": [
                _fmt_pct(perf["strategy"]["total_return"]),
                _fmt_pct(perf["strategy"]["cagr"]),
                _fmt_pct(perf["strategy"]["max_dd"]),
                _fmt_num(perf["strategy"]["sharpe"]),
            ],
            "オルカン (2559.T)": [
                _fmt_pct(perf["orcam"]["total_return"]),
                _fmt_pct(perf["orcam"]["cagr"]),
                _fmt_pct(perf["orcam"]["max_dd"]),
                _fmt_num(perf["orcam"]["sharpe"]),
            ],
            "S&P500 (2558.T)": [
                _fmt_pct(perf["sp500"]["total_return"]),
                _fmt_pct(perf["sp500"]["cagr"]),
                _fmt_pct(perf["sp500"]["max_dd"]),
                _fmt_num(perf["sp500"]["sharpe"]),
            ],
        }
        df_metrics = pd.DataFrame(metrics_data)
        st.dataframe(df_metrics, hide_index=True, width="stretch")

        # NAV 月次推移チャート
        st.markdown("#### 月次NAV推移")
        df = pd.DataFrame(perf["monthly_nav"])
        df["month"] = pd.to_datetime(df["month"], format="%Y-%m")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["month"], y=df["strategy_nav"],
                                  mode="lines+markers", name="戦略",
                                  line=dict(color="#d62728", width=2)))
        fig.add_trace(go.Scatter(x=df["month"], y=df["orcam_nav"],
                                  mode="lines+markers", name="オルカン",
                                  line=dict(color="#1f77b4", width=2)))
        fig.add_trace(go.Scatter(x=df["month"], y=df["sp500_nav"],
                                  mode="lines+markers", name="S&P500",
                                  line=dict(color="#2ca02c", width=2)))
        fig.add_hline(y=perf["initial"], line_dash="dash",
                       line_color="gray", annotation_text=f"初期 ¥{int(perf['initial']):,}")
        fig.update_layout(
            xaxis_title="月", yaxis_title="NAV (円)",
            hovermode="x unified", height=500,
            legend=dict(orientation="h", yanchor="bottom", y=1.02,
                          xanchor="right", x=1),
            yaxis=dict(tickformat=","),
            template="plotly_dark",
        )
        st.plotly_chart(fig, width="stretch")

        # 補足情報
        with st.expander("📝 戦略について"):
            st.markdown("""
            **戦略構成 (6戦略)**:
            - **I2**: MACD×低PBR×高配当 (ATRリスク)
            - **M**: MACD+増配カタリスト (ATRリスク)
            - **D**: 増配開示×低PBR (固定額)
            - **A**: 出来高急騰×低PBR×高配当 (ATRリスク)
            - **Q**: 高ROE×営業利益率×安定収益 (ATRリスク)
            - **BB**: BB収縮ブレイクアウト (ATRリスク)

            **特性**: 市場無相関(β≈0.05)・正α(年率+5%)を狙うシステム。
            MaxDDは抑制されているがインデックスのβ(市場上昇)は捕捉しない設計。

            **運用方針 (2026-05-11以降)**: 資産形成主力はインデックス投信。
            戦略はペーパートレード継続・データ収集用途。
            """)

        st.caption(f"データは毎月1日 19:00 にバックグラウンド更新 | 最終更新: {perf['updated_at']}")
