"""P3-2 通貨配分タブ突合: ローカルAPIのスナップショットに tab_currency.py と同一のpandasロジックを適用し、
期待値(目標差分・通貨別サマリー・為替感応度)を表示する。

前提: scripts/run_api_local.py でAPIが 127.0.0.1:8000 に起動済み(ログインは admin/testpass)。
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
    cash_jpy = snap["totals"]["cash_jpy"]
    TA = snap["totals"]["total_asset"] + cash_jpy  # tab_currency.py:14
    rate = snap["jpy_usd_rate"]
    t_jpy = snap["targets"]["jpy_pct"]
    t_usd = snap["targets"]["usd_pct"]
    print(f"=== 通貨配分タブ期待値 TA(現金込)=¥{TA:,.0f} rate={rate:.2f} 目標 JPY{t_jpy:.0f}%/USD{t_usd:.0f}% ===")

    # 通貨正規化(tab_currency.py:21-23)
    cdf = display_df.copy()
    if "通貨" not in cdf.columns:
        cdf["通貨"] = "JPY"
    cdf["通貨"] = cdf["通貨"].fillna("JPY")
    cdf.loc[cdf["通貨"].isin(["", "-", "nan"]), "通貨"] = "JPY"

    ccy_agg = cdf.groupby("通貨").agg(
        評価額=("評価額(円)", "sum"),
        損益=("税引後損益(円)", "sum"),
        配当=("予想配当(円)", "sum"),
        銘柄数=("銘柄コード", "count"),
    ).reset_index().sort_values("評価額", ascending=False)

    # 目標差分(tab_currency.py:41-47)
    jpy_actual = ccy_agg.loc[ccy_agg["通貨"] == "JPY", "評価額"].sum() + cash_jpy
    usd_actual = ccy_agg.loc[ccy_agg["通貨"] == "USD", "評価額"].sum()
    jpy_diff = jpy_actual - TA * t_jpy / 100
    usd_diff = usd_actual - TA * t_usd / 100
    usd_diff_usd = usd_diff / rate if rate > 0 else 0
    print("\n--- 目標差分 ---")
    print(f"JPY: {jpy_diff:+,.0f}円 実{jpy_actual/TA*100:.1f}%")
    print(f"USD: {usd_diff:+,.0f}円 / {usd_diff_usd:+,.2f}$ 実{usd_actual/TA*100:.1f}%")

    # リバランスプラン(tab_currency.py:82-103)
    shift = jpy_diff
    thresh = TA * 0.01
    if abs(shift) <= thresh:
        print(f"プラン: 達成圏内(誤差 {abs(shift):,.0f}円・{abs(shift)/TA*100:.1f}%)")
    else:
        m_yen = 7.0 * 10000
        months = abs(shift) / m_yen
        print(f"プラン: {'JPY過剰→USDへ' if shift > 0 else 'JPY不足→JPYへ'} {abs(shift):,.0f}円 / 月7万なら約{months:.1f}ヶ月")

    # サマリー(現金行込み・評価額降順)
    disp = ccy_agg.copy()
    if cash_jpy > 0:
        disp = pd.concat([disp, pd.DataFrame([{"通貨": "現金(JPY)", "評価額": cash_jpy, "損益": 0.0, "配当": 0.0, "銘柄数": 0}])], ignore_index=True).sort_values("評価額", ascending=False)
    print("\n--- 通貨別サマリー ---")
    for _, r in disp.iterrows():
        print(f"{r['通貨']}: {r['評価額']:,.0f}円 {r['評価額']/TA*100:.1f}% 損益{r['損益']:+,.0f}円 配当{int(r['配当']):,}円 {int(r['銘柄数'])}銘柄")

    # 為替感応度(tab_currency.py:223-234)
    usd_total = cdf[cdf["通貨"] == "USD"]["評価額(円)"].sum()
    print(f"\n--- 為替感応度 (USD建て合計 {usd_total:,.0f}円) ---")
    for pct in [-10, -5, -3, -1, 0, 1, 3, 5, 10]:
        impact = usd_total * (pct / 100)
        print(f"{pct:+d}%: レート¥{rate*(1+pct/100):.1f} 変動{impact:+,.0f}円 評価額{TA+impact:,.0f}円 全体{impact/TA*100:+.2f}%")


if __name__ == "__main__":
    main()
