"""P3-2 分析タブ突合: ローカルAPIのスナップショットに tab_analysis.py と同一のpandasロジックを適用し、
期待値(NISA枠・銘柄構成・セクター割合・リバランス乖離)を表示する。

前提: scripts/run_api_local.py でAPIが 127.0.0.1:8000 に起動済み(ログインは admin/testpass)。
比較方法: Next.js版 /analysis の表示数値と突合する。同一スナップショットを見るため価格ズレは発生しない。
"""
import os
import sys

import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://127.0.0.1:8000"


def main():
    token = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "testpass"}, timeout=30).json()["token"]
    snap = requests.get(f"{BASE}/api/portfolio", headers={"Authorization": f"Bearer {token}"}, timeout=300).json()

    display_df = pd.DataFrame(snap["rows"])
    TA = snap["totals"]["total_asset"]
    print(f"=== 分析タブ期待値 (tab_analysis.py と同一ロジック) TA=¥{TA:,.0f} ===")

    # ── NISA枠 (tab_analysis.py:35-36) ──
    nisa_g = display_df[display_df["口座区分"].str.contains("成長", na=False)]["評価額(円)"].sum()
    nisa_t = display_df[display_df["口座区分"].str.contains("積立", na=False)]["評価額(円)"].sum()
    lim = snap["nisa_limits"]
    print("\n--- NISA枠 ---")
    print(f"成長投資枠: {nisa_g:,.0f}円 / 残 {max(lim['growth_lifetime']-nisa_g,0):,.0f}円 / 年間残 {max(lim['growth_annual']-nisa_g,0):,.0f}円")
    print(f"積立投資枠: {nisa_t:,.0f}円 / 残 {max(lim['tsumitate_lifetime']-nisa_t,0):,.0f}円 / 年間残 {max(lim['tsumitate_annual']-nisa_t,0):,.0f}円")
    print(f"NISA合計  : {nisa_g+nisa_t:,.0f}円 / 残 {max(lim['total_lifetime']-(nisa_g+nisa_t),0):,.0f}円")

    # ── 銘柄構成 (tab_analysis.py:59-61) ──
    display_df["円グラフ表示名"] = display_df["銘柄コード"].astype(str) + " " + display_df["銘柄名"].astype(str)
    t1 = display_df[display_df["評価額(円)"] > 0].groupby("円グラフ表示名", as_index=False)["評価額(円)"].sum().sort_values("評価額(円)", ascending=False)
    t1["割合"] = (t1["評価額(円)"] / TA * 100).apply(lambda x: f"{x:.1f}%")
    print("\n--- 銘柄構成 (上位10) ---")
    for _, r in t1.head(10).iterrows():
        print(f"{r['円グラフ表示名']}: {int(r['評価額(円)']):,}円 {r['割合']}")

    # ── セクター別 (tab_analysis.py:73-75) ──
    t2 = display_df[display_df["評価額(円)"] > 0].groupby("セクター", as_index=False)["評価額(円)"].sum().sort_values("評価額(円)", ascending=False)
    t2["割合"] = (t2["評価額(円)"] / TA * 100).apply(lambda x: f"{x:.1f}%")
    print("\n--- セクター別 ---")
    for _, r in t2.iterrows():
        print(f"{r['セクター']}: {int(r['評価額(円)']):,}円 {r['割合']}")

    # ── ヒートマップ対象件数 (tab_analysis.py:81) ──
    tdf = display_df[(display_df["市場"].isin(["日本株", "米国株"])) & (display_df["評価額(円)"] > 0)]
    print(f"\n--- ヒートマップ対象: {len(tdf)}行 ---")

    # ── リバランス既定値 (tab_analysis.py:92-110, 目標=現在値0.1丸め) ──
    sc = display_df[display_df["評価額(円)"] > 0].groupby("セクター", as_index=False)["評価額(円)"].sum()
    sc["現在(%)"] = sc["評価額(円)"] / TA * 100
    print("\n--- リバランス(目標=既定値) ---")
    total_target = 0.0
    for sec in sorted(sc["セクター"].tolist()):
        cv = sc[sc["セクター"] == sec]["現在(%)"].values[0]
        tp = round(cv, 1)
        total_target += tp
        print(f"{sec}: 現在{cv:.1f}% 目標{tp:.1f}% 乖離{cv-tp:+.1f}%")
    print(f"目標合計: {total_target:.1f}%")


if __name__ == "__main__":
    main()
