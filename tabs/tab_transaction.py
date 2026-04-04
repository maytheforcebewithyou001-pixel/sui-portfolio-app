"""TAB 6: 取引履歴"""
import streamlit as st
import pandas as pd
from datetime import datetime
from config import BROKER_OPTIONS, TAX_OPTIONS
from data import save_data, save_transaction, save_transactions_batch, load_transactions
from tabs import pnl_color, pnl_sign


def _parse_broker_csv(csv_file):
    """SBI証券/楽天証券の約定履歴CSVを自動判別しパース。統一カラムで返す"""
    import io
    raw = csv_file.read()
    csv_text = None
    for enc in ["shift_jis", "cp932", "utf-8-sig", "utf-8"]:
        try: csv_text = raw.decode(enc); break
        except Exception: continue
    if csv_text is None: return None, None, "ファイルのエンコーディングを判別できませんでした。"

    lines = csv_text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "約定日" in line and "銘柄" in line: header_idx = i; break
    if header_idx is None: return None, None, "ヘッダー行が見つかりませんでした。"

    body_text = "\n".join(lines[header_idx:])
    csv_df = pd.read_csv(io.StringIO(body_text), encoding_errors="ignore")
    csv_df = csv_df.dropna(subset=["約定日"], how="all")
    csv_df = csv_df[csv_df["約定日"].astype(str).str.match(r"^\d{4}/")]
    if csv_df.empty: return None, None, "有効な約定データが見つかりませんでした。"

    for col in csv_df.columns:
        if csv_df[col].dtype == object:
            csv_df[col] = csv_df[col].astype(str).str.strip()

    # ── 証券会社を自動判別 ──
    is_rakuten = "売買区分" in csv_df.columns
    broker = "楽天証券" if is_rakuten else "SBI証券"

    if is_rakuten:
        # 楽天証券フォーマット
        csv_df["_取引種別"] = csv_df["売買区分"].apply(lambda v: "売却" if "売" in str(v) else "買い増し")
        def _tax_rakuten(v):
            v = str(v)
            if "NISA" in v and "積立" in v: return "NISA(積立投資枠)"
            if "NISA" in v: return "NISA(成長投資枠)"
            return "特定口座"
        csv_df["_口座区分"] = csv_df["口座区分"].apply(_tax_rakuten)
        for nc in ["数量［株］", "単価［円］", "手数料［円］", "受渡金額［円］"]:
            if nc in csv_df.columns:
                csv_df[nc] = csv_df[nc].astype(str).str.replace(",", "").str.replace("-", "0")
                csv_df[nc] = pd.to_numeric(csv_df[nc], errors="coerce").fillna(0)
        # 統一カラム名にリネーム
        csv_df = csv_df.rename(columns={"銘柄コード": "_code", "銘柄名": "_name", "市場名称": "_market",
                                         "数量［株］": "_qty", "単価［円］": "_price", "手数料［円］": "_fee"})
    else:
        # SBI証券フォーマット
        csv_df["_取引種別"] = csv_df["取引"].apply(lambda v: "売却" if "売" in str(v) or "解約" in str(v) else "買い増し")
        def _tax_sbi(v):
            v = str(v)
            if "つ" in v or "つみたて" in v or "旧つみたて" in v: return "NISA(積立投資枠)"
            if "成" in v or "NISA" in v: return "NISA(成長投資枠)"
            return "特定口座"
        csv_df["_口座区分"] = csv_df["預り"].apply(_tax_sbi)
        for nc in ["約定数量", "約定単価", "受渡金額/決済損益", "手数料/諸経費等"]:
            if nc in csv_df.columns:
                csv_df[nc] = csv_df[nc].astype(str).str.replace(",", "").str.replace("--", "0")
                csv_df[nc] = pd.to_numeric(csv_df[nc], errors="coerce").fillna(0)
        csv_df = csv_df.rename(columns={"銘柄コード": "_code", "銘柄": "_name", "市場": "_market",
                                         "約定数量": "_qty", "約定単価": "_price", "手数料/諸経費等": "_fee"})

    # コード正規化
    csv_df["_code"] = csv_df["_code"].astype(str).str.strip()
    csv_df.loc[csv_df["_code"].isin(["nan", ""]), "_code"] = ""

    return csv_df, broker, None


def render(tab, df):
    with tab:
        st.markdown("#### 📒 取引履歴")

        # ── 手動記録フォーム ──
        if not df.empty:
            with st.expander("➕ 取引を記録", expanded=True):
                with st.form("tx_form", clear_on_submit=True):
                    tx_r1a, tx_r1b, tx_r1c = st.columns([1, 2, 1])
                    with tx_r1a: tx_type = st.selectbox("取引種別", ["買い増し", "売却", "新規購入"], key="txtype")
                    with tx_r1b:
                        tx_options = [f"{row['銘柄コード']} {row['銘柄名']}" for _, row in df.iterrows()]
                        tx_sel = st.selectbox("銘柄", tx_options, key="txsel") if tx_options else None
                    with tx_r1c: tx_date = st.date_input("取引日", value=datetime.now().date(), key="txdate")
                    tx_r2a, tx_r2b, tx_r2c, tx_r2d = st.columns(4)
                    with tx_r2a: tx_qty = st.number_input("数量", min_value=0.0001, value=1.0, step=1.0, key="txqty")
                    with tx_r2b: tx_price = st.number_input("単価(円)", min_value=0.0, value=0.0, key="txprice")
                    with tx_r2c: tx_fee = st.number_input("手数料(円)", min_value=0.0, value=0.0, key="txfee")
                    with tx_r2d:
                        tx_broker = st.selectbox("口座", BROKER_OPTIONS, key="txbroker")
                        tx_tax = st.selectbox("口座区分", TAX_OPTIONS, key="txtax")
                    tx_submitted = st.form_submit_button("記録する", use_container_width=True)

                if tx_submitted and tx_sel:
                    tx_code = tx_sel.split(" ")[0]; tx_name = " ".join(tx_sel.split(" ")[1:])
                    idx = df[df["銘柄コード"].astype(str) == str(tx_code)].index
                    if len(idx) > 0:
                        cur_shares = float(df.at[idx[0], "保有株数"]); cur_price = float(df.at[idx[0], "取得単価"])
                        pnl_realized = 0.0
                        if tx_type == "売却":
                            df.at[idx[0], "保有株数"] = max(cur_shares - tx_qty, 0)
                            pnl_realized = (tx_price - cur_price) * tx_qty
                        else:
                            new_total = cur_shares + tx_qty
                            df.at[idx[0], "取得単価"] = (cur_shares * cur_price + tx_qty * tx_price) / new_total if new_total > 0 else tx_price
                            df.at[idx[0], "保有株数"] = new_total
                        save_data(df)
                        save_transaction({"日付": tx_date.strftime("%Y/%m/%d"), "銘柄コード": tx_code, "銘柄名": tx_name,
                                          "市場": df.at[idx[0], "市場"] if "市場" in df.columns else "-",
                                          "取引種別": tx_type, "数量": tx_qty, "単価(円)": tx_price,
                                          "手数料": tx_fee, "損益確定(円)": round(pnl_realized, 0),
                                          "口座": tx_broker, "口座区分": tx_tax})
                        st.cache_data.clear(); st.success(f"✓ {tx_type} 記録完了。保有数を更新しました。")
                        if tx_type == "売却" and pnl_realized != 0:
                            c_ = pnl_color(pnl_realized); s_ = pnl_sign(pnl_realized)
                            cls = "alert-up" if pnl_realized >= 0 else "alert-down"
                            st.markdown(f"<div class='alert-bar {cls}'>確定損益: <b style='color:{c_}'>{s_}{pnl_realized:,.0f}円</b></div>", unsafe_allow_html=True)
                        st.rerun()

        # ── CSVインポート ──
        st.markdown("---"); st.markdown("#### 📂 証券会社 約定履歴CSVから取込")
        st.caption("SBI証券・楽天証券の約定履歴CSVを自動判別して取り込みます。")
        csv_file = st.file_uploader("CSVファイルを選択", type=["csv"], key="csvup")
        if csv_file:
            csv_df, broker, err = _parse_broker_csv(csv_file)
            if err: st.error(err); return
            st.success(f"🏦 **{broker}** のCSVを検出 — {len(csv_df)}件の約定データ")
            preview_cols = ["約定日", "_name", "_code", "_取引種別", "_口座区分", "_qty", "_price"]
            preview_rename = {"_name": "銘柄名", "_code": "銘柄コード", "_qty": "数量", "_price": "単価"}
            show_df = csv_df[[c for c in preview_cols if c in csv_df.columns]].rename(columns=preview_rename)
            st.dataframe(show_df, use_container_width=True, height=min(len(csv_df) * 35 + 38, 600))

            imp_mode = st.radio("取込モード", ["取引履歴に登録", "保有銘柄の数量を更新", "両方（取引履歴＋保有銘柄更新）"], index=2, key="csv_imp_mode", horizontal=True)
            if st.button("✅ インポート実行", use_container_width=True, key="csvimport"):
                tx_count, upd_count, skip_count = 0, 0, 0
                if imp_mode in ("取引履歴に登録", "両方（取引履歴＋保有銘柄更新）"):
                    tx_batch = []
                    for _, crow in csv_df.iterrows():
                        code = crow["_code"]
                        market = str(crow.get("_market", "")).replace("nan", "-") or "-"
                        tx_batch.append({"日付": str(crow["約定日"]), "銘柄コード": code,
                                          "銘柄名": str(crow.get("_name", "")).strip(),
                                          "市場": market, "取引種別": crow["_取引種別"],
                                          "数量": crow["_qty"], "単価(円)": crow["_price"],
                                          "手数料": crow.get("_fee", 0), "損益確定(円)": 0,
                                          "口座": broker, "口座区分": crow["_口座区分"]})
                    save_transactions_batch(tx_batch)
                    tx_count = len(tx_batch)
                if imp_mode in ("保有銘柄の数量を更新", "両方（取引履歴＋保有銘柄更新）"):
                    for _, crow in csv_df.iterrows():
                        code = crow["_code"]
                        if not code: skip_count += 1; continue
                        qty, price = float(crow["_qty"]), float(crow["_price"])
                        idx = df[df["銘柄コード"].astype(str) == code].index
                        if len(idx) == 0: skip_count += 1; continue
                        cur_s, cur_p = float(df.at[idx[0], "保有株数"]), float(df.at[idx[0], "取得単価"])
                        if crow["_取引種別"] == "売却":
                            df.at[idx[0], "保有株数"] = max(cur_s - qty, 0)
                        else:
                            new_t = cur_s + qty
                            df.at[idx[0], "取得単価"] = (cur_s * cur_p + qty * price) / new_t if new_t > 0 else price
                            df.at[idx[0], "保有株数"] = new_t
                        upd_count += 1
                    save_data(df)
                st.cache_data.clear()
                msgs = []
                if tx_count > 0: msgs.append(f"取引履歴: {tx_count}件登録")
                if upd_count > 0: msgs.append(f"保有銘柄: {upd_count}件更新")
                if skip_count > 0: msgs.append(f"{skip_count}件スキップ（未登録銘柄/投信）")
                st.success(f"✓ {' / '.join(msgs)}"); st.rerun()

        # ── 取引履歴一覧 ──
        st.markdown("---"); st.markdown("#### 📋 取引履歴一覧")
        tx_df = load_transactions()
        if not tx_df.empty:
            tx_buy = tx_df[tx_df["取引種別"].isin(["買い増し", "新規購入"])]
            tx_sell = tx_df[tx_df["取引種別"] == "売却"]
            total_pnl = tx_df["損益確定(円)"].sum()
            ts1, ts2, ts3 = st.columns(3)
            with ts1: st.markdown(f"<div class='status-card' style='padding:0.7rem'><h4>買い付け回数</h4><p class='mv' style='font-size:1.2rem'>{len(tx_buy)}<span>回</span></p></div>", unsafe_allow_html=True)
            with ts2: st.markdown(f"<div class='status-card' style='padding:0.7rem'><h4>売却回数</h4><p class='mv' style='font-size:1.2rem'>{len(tx_sell)}<span>回</span></p></div>", unsafe_allow_html=True)
            with ts3:
                tc = pnl_color(total_pnl); ts = pnl_sign(total_pnl)
                st.markdown(f"<div class='status-card' style='padding:0.7rem'><h4>確定損益合計</h4><p class='mv' style='font-size:1.2rem;color:{tc}'>{ts}{total_pnl:,.0f}<span>円</span></p></div>", unsafe_allow_html=True)
            tx_show = tx_df.sort_values("日付", ascending=False).copy()
            tx_show["損益確定(円)"] = tx_show["損益確定(円)"].apply(lambda x: f"{x:+,.0f}円" if x != 0 else "-")
            tx_show["単価(円)"] = tx_show["単価(円)"].apply(lambda x: f"{x:,.0f}" if x > 0 else "-")
            tx_show["数量"] = tx_show["数量"].apply(lambda x: f"{x:,.4g}")
            st.dataframe(tx_show, width='stretch', hide_index=True)
            st.download_button("📥 取引履歴をCSVでダウンロード", tx_df.to_csv(index=False).encode("utf-8-sig"),
                               f"transactions_{datetime.now():%Y%m%d}.csv", "text/csv", use_container_width=True)
        else: st.info("取引を記録すると履歴が表示されます。")
