"""P3-2 配当タブ突合: ローカルAPIのスナップショットに tab_dividend.py と同一ロジックを適用し、
期待値(月別カレンダー・年間サマリー・ランキング)を表示する。

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

    # 月別カレンダー(tab_dividend.py:15-26)
    mdv = {m: 0 for m in range(1, 13)}
    mda = {m: 0 for m in range(1, 13)}
    mdt = {m: [] for m in range(1, 13)}
    for _, row in display_df.iterrows():
        da = row.get("予想配当(円)", 0) or 0
        daa = row.get("税引後配当(円)", 0) or 0
        dms = str(row.get("配当月", "") or "")
        if da > 0 and dms:
            ml = [int(x.strip()) for x in dms.split(",") if x.strip().isdigit()]
            if not ml:
                continue
            p, pa = da / len(ml), daa / len(ml)
            tl = "非課税" if "NISA" in str(row.get("口座区分", "")) else "課税"
            for m in ml:
                if 1 <= m <= 12:
                    mdv[m] += p
                    mda[m] += pa
                    mdt[m].append({"銘柄": f"{row['銘柄コード']} {row['銘柄名']}", "税引前": p, "税引後": pa, "税区分": tl})

    print("=== 配当タブ期待値 ===\n--- 月別(税引前/手取り/銘柄数) ---")
    for m in range(1, 13):
        if mdv[m] > 0:
            print(f"{m}月: ¥{mdv[m]:,.0f} / ¥{mda[m]:,.0f} / {len(mdt[m])}銘柄")
        else:
            print(f"{m}月: —")

    tcd, tcda = sum(mdv.values()), sum(mda.values())
    print("\n--- サマリー ---")
    print(f"年間配当(税引前): ¥{tcd:,.0f}")
    print(f"年間手取り(税引後): ¥{tcda:,.0f}")
    print(f"月平均手取り: ¥{tcda/12:,.0f}")
    print(f"配当発生月: {sum(1 for v in mdv.values() if v > 0)}/12")

    print("\n--- ランキング(上位10) ---")
    drank = display_df[display_df["予想配当(円)"] > 0][["銘柄コード", "銘柄名", "予想配当(円)", "実質利回り(%)"]].sort_values("予想配当(円)", ascending=False).head(10)
    for _, r in drank.iterrows():
        print(f"{r['銘柄コード']} {r['銘柄名']}: ¥{int(r['予想配当(円)']):,} {r['実質利回り(%)']:.2f}%")

    # 内訳サンプル: 最大月の上位3
    top_m = max(mdv, key=mdv.get)
    print(f"\n--- {top_m}月内訳(税引前降順・上位3) ---")
    for x in sorted(mdt[top_m], key=lambda v: v["税引前"], reverse=True)[:3]:
        print(f"{'🟢' if x['税区分'] == '非課税' else '🟡'} {x['銘柄']}: ¥{x['税引後']:,.0f}")


if __name__ == "__main__":
    main()
