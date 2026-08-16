# -*- coding: utf-8 -*-
"""ライフプランMCモデルの独立検算スクリプト (2026-07-17)

レポート『ライフプラン_モンテカルロ検証_20260717.md』§1の仕様文書だけを根拠に、
simulate() とは独立のロジックで決定論（複利4%固定）の年次資産推移を再実装し、
本体 simulate(deterministic=True, track=True) の軌跡と突合する。

合格基準: 全56年の総資産が相対誤差1e-9未満で一致し、95歳終端が§6の29,615万と一致。
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
import numpy as np

from lifeplan_montecarlo_20260717 import simulate

R = 0.04          # 複利リターン（実質）
SAVE = 200.0      # 年間新規貯蓄（就労中）
SPEND = 360.0     # 老後生活費（年金差引前）
RETIRE = 60


def pension_at(age):
    """仕様: 夫=60歳134→61歳以降146、妻=基礎80を夫69歳から"""
    p = 0.0
    if age >= RETIRE:
        p += 134.0 if age == RETIRE else 146.0
    if age >= 69:
        p += 80.0
    return p


def edu_cost_at(age):
    """仕様: 私立トラック 中40(12-14)/高150(15-17)/大250(18-21)。子①=夫-37, 子②=夫-40"""
    total = 0.0
    for off in (37, 40):
        c = age - off
        if 12 <= c <= 14:
            total += 40
        elif 15 <= c <= 17:
            total += 150
        elif 18 <= c <= 21:
            total += 250
    return total


def edu_inflow_at(age):
    """仕様: 別建て口座へ21万/子/年、各子18歳まで"""
    return (21 if age - 37 < 18 else 0) + (21 if age - 40 < 18 else 0)


def independent_trace(rates=None, death=None):
    """決定論の年次資産推移。rates=Noneで複利4%固定（従来）、
    配列指定でその年次リターン系列（returns_seq検算用）。
    death=(死亡年齢, 保険金, 遺族収入/年, 以後支出/年) で夫死亡シナリオ検算。"""
    risk, edu, cash = 3066.0, 0.0, 300.0
    rows = []
    for k, age in enumerate(range(40, 96)):
        r_y = R if rates is None else float(rates[k])
        # 1) 運用成長（現金は実質0）
        risk *= 1 + r_y
        edu *= 1 + r_y
        # 1b) 死亡年に保険金、以後は遺族家計
        dead = death is not None and age >= death[0]
        if death is not None and age == death[0]:
            risk += death[1]
        # 2) 教育口座への流入
        edu += edu_inflow_at(age)
        # 3) 教育費: 当年貯蓄→別建て口座→本体→現金
        need = edu_cost_at(age)
        working = age < RETIRE and not dead
        sav = SAVE if working else 0.0
        use = min(sav, need); need -= use; sav -= use
        risk += sav                       # 余った貯蓄は本体へ
        use = min(edu, need); edu -= use; need -= use
        use = min(risk, need); risk -= use; need -= use
        use = min(cash, need); cash -= use; need -= use
        assert need < 1e-9, f"{age}歳で教育費枯渇"
        # 4) 老後（or遺族期）: 生活費 − 年金（収入超過分は本体へ）
        if not working:
            if dead:
                pens = death[2] + (80.0 if age >= 69 else 0.0)
                net = death[3] - pens
            else:
                net = SPEND - pension_at(age)
            if net < 0:
                risk += -net; net = 0.0
            use = min(risk, net); risk -= use; net -= use
            use = min(cash, net); cash -= use; net -= use
            assert net < 1e-9, f"{age}歳で生活費枯渇"
        rows.append((age, risk, edu, cash, risk + edu + cash))
    return rows


if __name__ == "__main__":
    rows = independent_trace()

    r = simulate(deterministic=True, track=True)
    t = r["trajectory"]
    # 決定論では全パス同一なので p50 がそのまま唯一の軌跡
    max_rel = 0.0
    for (age, _, _, _, total), p50 in zip(rows, t["p50"]):
        rel = abs(total - p50) / max(p50, 1.0)
        max_rel = max(max_rel, rel)
    print(f"全56年 突合: 最大相対誤差 = {max_rel:.2e}")
    assert max_rel < 1e-9, "本体実装と独立実装が不一致"

    terminal = rows[-1][4]
    print(f"95歳終端(独立計算) = {terminal:,.0f}万 / レポート§6 = 29,615万")
    assert abs(terminal - 29615) < 1.0, "レポート値と不一致"

    # 節目の年をトレース表示（教育ピーク・退職遷移）
    print("\n年齢 |  本体リスク |  教育口座 |  現金 |  総資産 | 教育費 | 年金")
    for age, risk, edu, cash, total in rows:
        if age in (40, 49, 52, 55, 58, 59, 60, 61, 65, 69, 70, 80, 95):
            print(f"{age:>3} | {risk:>10,.0f} | {edu:>8,.0f} | {cash:>5,.0f} | "
                  f"{total:>9,.0f} | {edu_cost_at(age):>5,.0f} | {pension_at(age):>4,.0f}")

    # ---------- 追加検算（2026-07-26: 実史形状ブートストラップ／シーケンス・リプレイ）
    from lifeplan_montecarlo_20260717 import historical_sequences
    from lifeplan_returns_hist import (block_bootstrap_z, load_returns,
                                       sequence_indices, standardized_log_dev)

    # (a) 回帰: 既定経路の結果が7/17確定値のまま（乱数消費が変わっていない証明）
    base = simulate()["score"]
    print(f"\n回帰: simulate()既定スコア = {base:.3f}（要求 88.225）")
    assert abs(base - 88.225) < 1e-9, "既定経路の回帰NG（乱数消費が変わった疑い）"

    # (b) returns_seq注入: 任意の年次系列を独立トレースと突合（56年・1e-9）
    rates = [0.10 if k % 3 == 0 else (-0.05 if k % 3 == 1 else 0.04)
             for k in range(56)]
    rows_seq = independent_trace(rates)
    t_seq = simulate(returns_seq=np.array(rates), n_paths=1, track=True)["trajectory"]
    max_rel = max(abs(total - p50) / max(p50, 1.0)
                  for (_, _, _, _, total), p50 in zip(rows_seq, t_seq["p50"]))
    print(f"returns_seq注入 突合(+10%/-5%/+4%繰返し系列): 最大相対誤差 = {max_rel:.2e}")
    assert max_rel < 1e-9, "returns_seq注入が独立実装と不一致"

    # (c) 標準化: 組込系列のzは平均0・標本SD1、幾何平均はμに厳密一致
    _, hr = load_returns()
    z = standardized_log_dev(hr)
    assert abs(z.mean()) < 1e-12 and abs(z.std(ddof=1) - 1.0) < 1e-12, "z標準化NG"
    mu = 0.04
    gen = np.exp(np.log(1 + mu) + 0.18 * z) - 1
    geo_err = abs(np.log1p(gen).mean() - np.log(1 + mu))
    print(f"実史z標準化: mean={z.mean():.1e} sd-1={z.std(ddof=1)-1:.1e} / "
          f"再構成系列の幾何平均誤差 = {geo_err:.2e}")
    assert geo_err < 1e-12, "幾何平均μの貼り直しが不正確"

    # (d) ブロック抽出: 各行が「連続インデックスの塊」だけで構成されること
    z10 = np.arange(10, dtype=float)          # 値=インデックスの照合用系列
    zb = block_bootstrap_z(z10, n_paths=200, n_years=56, block_len=5,
                           rng=np.random.default_rng(1))
    for p in range(200):
        for k in range(0, 55, 5):
            blk = zb[p, k:k + 5]
            assert all((blk[t + 1] - blk[t]) % 10 == 1 for t in range(len(blk) - 1)), \
                f"ブロック非連続: path={p} pos={k} {blk}"
    print("ブロックBS: 200パス×56年 全ブロックの連続性 OK")

    # (e) 循環インデックスとシーケンス集計の自己整合
    idx = sequence_indices(95, 56, 97)
    assert idx[0] == 95 and idx[2] == 0 and len(idx) == 56, "循環インデックスNG"
    hs = historical_sequences()
    ok_n = sum(1 for x in hs["results"] if x["ok"])
    assert hs["n_starts"] == len(hr) and ok_n == hs["n_ok"], "シーケンス集計NG"
    assert abs(hs["success_rate"] - ok_n / hs["n_starts"] * 100) < 1e-12
    print(f"開始年総当たり: {hs['n_starts']}開始年・成功率 {hs['success_rate']:.1f}% 集計整合 OK")

    # ---------- 追加検算（2026-07-26第2弾: 収入リスク・死亡シナリオ・μ不確実性）
    # (f) ゼロ効果パラメータは基準と厳密一致（別ストリーム設計・opt-in性の証明）
    for name, kw in [("mu_sd=0", dict(mu_sd=0.0)),
                     ("bonus_risk p=0", dict(bonus_risk=(0.0, 116, 2))),
                     ("disable_risk p=0", dict(disable_risk=(0.0, 0.0))),
                     ("save_cut範囲外", dict(save_cut=(200, 3, 84))),
                     ("crash_at範囲外", dict(crash_at=(39, -0.4)))]:
        s = simulate(**kw)["score"]
        assert abs(s - base) < 1e-12, f"ゼロ効果NG {name}: {s}"
    print("ゼロ効果パラメータ5種: 基準88.225と厳密一致 OK")

    # (g) 確率1の収入イベント = save直接指定と厳密一致（市場乱数の分離も同時に証明）
    s84 = simulate(save=84)["score"]
    for name, kw in [("bonus p=1", dict(bonus_risk=(1.0, 116, 1))),
                     ("disable p=1", dict(disable_risk=(1.0, 84.0))),
                     ("save_cut全期間", dict(save_cut=(40, 200, 84)))]:
        s = simulate(**kw)["score"]
        assert abs(s - s84) < 1e-12, f"等価性NG {name}: {s} != {s84}"
    a = simulate(crash_year1=-0.40)["score"]
    b = simulate(crash_at=(40, -0.40))["score"]
    assert abs(a - b) < 1e-12, "crash_at(40)がcrash_year1と不一致"
    print(f"確率1等価性3種: save=84直接({s84:.3f})と厳密一致 / crash_at=crash_year1 OK")

    # (h) 夫死亡シナリオ: 決定論を独立トレースと突合（56年・1e-9）
    dth = (50, 2000.0, 150.0, 300.0)
    rows_d = independent_trace(death=dth)
    t_d = simulate(deterministic=True, death=dth, track=True)["trajectory"]
    max_rel = max(abs(total - p50) / max(p50, 1.0)
                  for (_, _, _, _, total), p50 in zip(rows_d, t_d["p50"]))
    print(f"死亡シナリオ(50歳/保険2000/遺族150/支出300) 突合: 最大相対誤差 = {max_rel:.2e}")
    assert max_rel < 1e-9, "死亡シナリオが独立実装と不一致"

    # (h2) 妻側シナリオ: 合成が「手組みのshocks+pension_spouse=0」と厳密一致
    from lifeplan_montecarlo_20260717 import spouse_scenario
    hand = ((42, 200.0),) \
         + tuple((a, 120.0) for a in range(42, 47)) \
         + tuple((a, 70.0) for a in range(47, 53)) \
         + tuple((a, 30.0) for a in range(53, 56)) \
         + tuple((a, -131.0) for a in range(42, 55)) \
         + tuple((a, -107.0) for a in range(55, 58))
    sa = spouse_scenario(42)["score"]
    sb = simulate(shocks=hand, pension_spouse=0.0)["score"]
    assert abs(sa - sb) < 1e-12, f"妻側シナリオ合成NG: {sa} != {sb}"
    print(f"妻側シナリオ(死亡@42): 合成={sa:.3f} 手組みキャッシュフロー表と厳密一致 OK")

    # (i) μ不確実性: 増やすほどスコアが下がる方向（対称でも枯渇リスクは下振れ支配）
    s1 = simulate(mu_sd=0.01)["score"]
    s2 = simulate(mu_sd=0.02)["score"]
    print(f"μ不確実性: σμ=0 {base:.2f} / 0.01 {s1:.2f} / 0.02 {s2:.2f}")
    assert s2 < s1 < base, "μ不確実性の方向性NG"

    print("\n✅ 独立検算 合格（決定論トレース＋実史形状＋収入リスク・死亡・μ不確実性）")
