"""P3-2 シミュレーションタブ突合: tab_simulation.py と同一ロジックの期待値を表示する。

ゴール逆算=タブ内式をそのまま、資産推移/積立/取り崩し=calc.py実物+タブの年次グルーピング。
前提: scripts/run_api_local.py でAPIが 127.0.0.1:8000 に起動済み(TA取得のため)。
"""
import os
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from calc import get_future_simulation, simulate_withdrawal  # noqa: E402

BASE = "http://127.0.0.1:8000"


def yearly(sim):
    sim = sim.copy()
    sim["年"] = sim["日時"].dt.year
    yd = sim.groupby("年").last().reset_index()
    by = yd["年"].iloc[0]
    yd["経過年数"] = yd["年"].apply(lambda y: f"{y - by}年目" if y > by else "現在")
    return yd


def main():
    token = requests.post(f"{BASE}/api/auth/login", json={"username": "admin", "password": "testpass"}, timeout=30).json()["token"]
    snap = requests.get(f"{BASE}/api/portfolio", headers={"Authorization": f"Bearer {token}"}, timeout=300).json()
    TA = snap["totals"].get("total_asset_all", snap["totals"]["total_asset"])
    print(f"=== シミュレーションタブ期待値 TA(現金込)=¥{TA:,.0f} ===")

    # ゴール逆算(tab_simulation.py:13-18、既定=1.2億・年利6%)
    goal, r = 1.2e8, 0.06
    print("\n--- ゴール逆算(1.2億・年利6%) ---")
    for y in [10, 15, 20, 25, 30]:
        sf = goal - (TA * ((1 + r) ** y))
        pm = sf / (((1 + r) ** y - 1) / r) if sf > 0 else 0
        print(f"{y}年後: {f'{int(pm):,}円' if pm > 0 else '達成確実！'}")

    # 資産推移(既定=年利6%・積立120万・10年)
    yd = yearly(get_future_simulation(TA, 0.06, 10, 1200000))
    last = yd.iloc[-1]
    print("\n--- 資産推移(10年・年利6%・積立120万) ---")
    print(f"予測評価額: ¥{last['予測評価額(円)']:,.0f} / 元本: ¥{last['積立元本(円)']:,.0f} / 運用益: ¥{last['運用益(円)']:,.0f}")
    print(f"年次ラベル: {list(yd['経過年数'])[:3]}...{list(yd['経過年数'])[-1]}")

    # 積立シム(既定=初期TA・月5万・年利5%・10年)
    ia = int(TA)
    yd2 = yearly(get_future_simulation(float(ia), 0.05, 10, 50000.0 * 12))
    last2 = yd2.iloc[-1]
    roi = last2["運用益(円)"] / last2["積立元本(円)"] * 100
    print("\n--- 積立シム(初期TA・月5万・年利5%・10年) ---")
    print(f"評価額: ¥{last2['予測評価額(円)']:,.0f} / 元本: ¥{last2['積立元本(円)']:,.0f} / 運用益: ¥{last2['運用益(円)']:,.0f} / +{roi:.1f}%")

    # 取り崩しシム(既定=固定額・初期int(TA)・年利4%・取崩int(ia*0.04)・40年)
    wa = int(ia * 0.04)
    sim = simulate_withdrawal(float(ia), 0.04, "fixed", annual_withdrawal=float(wa), max_years=40)
    depleted = sim[sim["残高(円)"] <= 0]
    print("\n--- 取り崩しシム(固定・年利4%・年間取崩4%) ---")
    print(f"年間取崩既定値: ¥{wa:,}")
    print(f"資産寿命: {'枯渇 ' + str(int(depleted['年'].iloc[0])) + '年' if not depleted.empty else str(int(sim['年'].iloc[-1])) + '年超'}")
    print(f"最終残高: ¥{sim['残高(円)'].iloc[-1]:,.0f} / 累計取崩: ¥{sim['累計取崩(円)'].iloc[-1]:,.0f}")


if __name__ == "__main__":
    main()
