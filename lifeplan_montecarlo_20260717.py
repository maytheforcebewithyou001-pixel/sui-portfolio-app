# -*- coding: utf-8 -*-
"""ライフプラン モンテカルロ検証 (2026-07-17)

対象: 2026-07-10改訂ライフプラン（三層防衛構造・教育費別建て・基準リターン4%）
手法: T. Rowe Price記事の趣旨に沿い、固定リターン前提を確率分布に置き換えて
      95歳時点の資産残存確率（信頼スコア）を算定する。

単位: 万円・実質ベース（今日の円価値）。年金・生活費・教育費は実質一定と仮定。
資産データ: 保有スプレッドシート直読み7/16計測（リスク資産3,066万）＋現金300万（第一層）。
"""
import numpy as np

from lifeplan_returns_hist import (block_bootstrap_z, load_returns,
                                   sequence_indices, standardized_log_dev)

N = 20_000          # 試行数
AGE_START, AGE_END = 40, 95

# 子の年齢オフセット（実年齢ベース: 子①3歳/子②0歳 @夫40歳）
C1_OFF, C2_OFF = 37, 40

def edu_cost(child_age, track):
    """年間教育費（万円）。小学校までは生活費内として0扱い。"""
    if track == "private":          # 公立中→私立高→私立大（プラン基準）
        if 12 <= child_age <= 14: return 40
        if 15 <= child_age <= 17: return 150
        if 18 <= child_age <= 21: return 250
    else:                            # 分岐: 公立高→国公立大
        if 12 <= child_age <= 17: return 40
        if 18 <= child_age <= 21: return 120
    return 0

def _plan_cost(child_age, plan):
    """段階別カスタム単価。plan = (中学, 高校, 大学, 下宿加算) 万円/年"""
    jhs, hs, univ, lodging = plan
    if 12 <= child_age <= 14: return jhs
    if 15 <= child_age <= 17: return hs
    if 18 <= child_age <= 21: return univ + lodging
    return 0

def simulate(mu=0.04, sigma=0.18, save=200.0, spend=360.0, spend_after70=None,
             edu_track="private", retire_age=60, pension_scale=1.0,
             calm65=None, deterministic=False, seed=20260717, track=False,
             risk0=3066.0, cash0=300.0, pension_self=None,
             pension_spouse=80.0, spouse_from=69,
             age_end=95, edu_plan=None, reemploy_until=None, reemploy_income=0.0,
             pension_from=None, cash_real=0.0, shocks=None, crash_year1=None,
             tax_rate=0.0, guardrail=None, calm65_if_above=None, ar1_rho=None,
             ideco=None, ret_model="iid", hist_returns=None, block_len=5,
             returns_seq=None, n_paths=None, mu_sd=None, bonus_risk=None,
             disable_risk=None, death=None, crash_at=None, save_cut=None,
             edu_inflow=21.0, spend_change_age=70):
    """1シナリオを N 本実行して統計を返す。

    mu: 複利（幾何）リターンの中央値。プランの「想定株式リターン4%」は決定論の
        複利4%を意味するため、これに合わせる（対数正規の中央値=exp(ln(1+mu))-1=mu、
        算術平均はσ18%でおよそ mu+1.7pt）。
    save: 就労中の年間新規貯蓄（本体へ）。教育費支払年は教育費へ優先充当（積立停止OK ルール）。
          既定200万/年 = 月7万積立84万＋賞与約120万（2026-07-17 岡部確定値。年初NISA枠の
          残りは特定オルカン売却の内部振替で埋める想定のため新規貯蓄に含めない）
    calm65: (mu, sigma) 65歳以降の安定運用への切替
    track: Trueで年齢別の資産パーセンタイル軌跡と累積枯渇率を結果に含める（GUI用。乱数消費は不変）
    risk0/cash0: 初期リスク資産・現金（既定=7/16計測3,066万・第一層300万）
    pension_self: 夫の年金（万円/年、退職年齢から）。None=ねんきんネット実データ形状
                  （60歳開始年のみ134、以降146）。数値指定時は全期間その額
    pension_spouse/spouse_from: 妻の年金額と開始時の夫年齢（既定80万/夫69歳=妻65歳）
    age_end: 検討終了年齢（既定95）
    edu_plan: 段階別カスタム教育費 {"c1": (中,高,大,下宿), "c2": (...)}。指定時はedu_trackを無視
    reemploy_until/reemploy_income: 再雇用（退職〜この年齢まで、手取り万円/年で生活費と相殺。
                                    年金・再雇用収入が支出を上回る余剰は本体へ積み増し）
    pension_from: 夫の年金受給開始年齢。None=退職と同時（従来互換）
    cash_real: 現金の実質リターン（インフレ考慮なら -インフレ率）
    shocks: 一時支出 ((年齢, 万円), ...)。介護・リフォーム等
    crash_year1: 初年度リターンを固定注入（例 -0.40）。ストレステスト用
    tax_rate: 本体取り崩しへの実効課税ハイカット（例 0.10 = 譲渡益課税20.315%×含み益率5割）。
              教育口座（こどもNISA）と現金は非課税扱い
    guardrail: (発動閾値, 減額幅) 例 (0.06, 0.10) = 取り崩し率6%超の年は支出を10%絞る
    calm65_if_above: calm65併用時、65歳時点資産がこの額以上のパスだけ安定運用へ切替（万円）
    ar1_rho: log-returnのAR(1)自己相関（負で平均回帰）。None=年次i.i.d.（従来）
    ideco: (年間拠出, 年間節税還付, 開始年齢, 受取年齢, 出口実効税率)
           例 (24.0, 7.2, 41, 60, 0.12)。拠出は就労中のみ save から振替（還付は save へ加算）、
           口座は本体と同一リターンで拘束運用、受取年齢で (1-出口税率) を本体へ一括払出。
           拘束中は教育費・生活費・ショックの取り崩し原資に使えない
    ret_model: "iid"=年次独立の対数正規（従来・既定） / "bootstrap"=実史形状の
               循環ブロック・ブートストラップ。bootstrapは対数リターンの標準化偏差zを
               実史から連続block_len年単位で抽出し exp(ln(1+μ)+σ·z)-1 で再構成する
               （幾何平均μ・対数分散σ²は従来と厳密一致、形状・連鎖のみ実史）。
               指定時は ar1_rho を無視。deterministic=True時も無視
    hist_returns: bootstrap用の実史リターン配列（小数）。None=組込S&P500形状
                  （lifeplan_returns_hist、CSVで差し替え可）
    block_len: ブートストラップのブロック長（年）。1=単純ブートストラップ
    returns_seq: 年次リターン系列を直接注入（開始年総当たりリプレイ用、len>=年数）。
                 指定時は全パス同一の決定論リプレイになり、mu/sigma/calm65/ar1_rho/
                 crash_year1のリターン生成は無効。n_paths=1と併用推奨
    n_paths: 試行数の上書き（None=モジュール既定N。リプレイは1で十分）
    mu_sd: μの推定不確実性（対数リターンSD、例 0.01）。パスごとに一定の
           μオフセットを N(0, mu_sd) から1回引く=「μを知らないリスク」。
           calm65やbootstrapにも同じオフセットが乗る。deterministic時は無視
    bonus_risk: (年発生確率, 賞与額万円, 継続年数k)。就労中、確率pで賞与がk年
                連続消滅するスペルを注入（save から賞与額を減額、下限0）
    disable_risk: (年発生確率, 以後の年間貯蓄)。就労不能の吸収状態。一度発生
                  したら就労完了まで貯蓄が指定額に固定される
    death: (死亡年齢, 保険金万円, 遺族収入万円/年, 以後支出万円/年)。夫死亡の
           決定論シナリオ。死亡年に保険金を本体へ加算、以後は就労扱い終了・
           支出=以後支出・夫年金の代わりに遺族収入（遺族厚生年金+妻就労等の
           合算、pension_scale適用）。妻自身の年金(pension_spouse)は従来どおり
           spouse_fromから加算。spend_after70・再雇用は死亡後無効。ideco併用不可
    crash_at: (年齢, リターン)。任意年齢に固定リターンを注入（crash_year1の一般化）
    save_cut: (開始年齢, 年数, その間の年間貯蓄)。決定論の貯蓄カット窓
              （複合ストレス用: 暴落と同時に賞与消滅を注入する等）
    edu_inflow: 教育費別建て口座への年間流入（万円/子、各子18歳まで）。
                既定21=児童手当+東京018由来（従来互換）。0で流入なし=
                教育費は当年貯蓄→本体→現金だけで賄う想定
    spend_change_age: spend_after70 が切り替わる年齢（既定70=従来互換。
                      ローン完済年齢に合わせて動かす）

    ※収入系の乱数(mu_sd/bonus_risk/disable_risk)は市場乱数と別ストリーム。
      同一seedなら市場パスを固定したまま収入リスクだけon/offして比較できる。
    """
    if death is not None and ideco is not None:
        raise ValueError("death と ideco の併用は未対応")
    rng = np.random.default_rng(seed)
    NP = N if n_paths is None else int(n_paths)
    ages = np.arange(AGE_START, int(age_end) + 1)
    boot_z = None
    if ret_model == "bootstrap" and not deterministic and returns_seq is None:
        hr = (np.asarray(hist_returns, float) if hist_returns is not None
              else load_returns()[1])
        boot_z = block_bootstrap_z(standardized_log_dev(hr), NP, len(ages),
                                   block_len, rng)
    if returns_seq is not None and len(returns_seq) < len(ages):
        raise ValueError(f"returns_seqが短い: {len(returns_seq)} < {len(ages)}年")

    # 収入系・パラメータ系の乱数は市場と別ストリーム（seedにソルトを混ぜる）
    mu_off = 0.0
    if mu_sd is not None and not deterministic and returns_seq is None:
        mu_off = float(mu_sd) * np.random.default_rng([seed, 11]).standard_normal(NP)
    rng_b = np.random.default_rng([seed, 13]) if bonus_risk is not None else None
    rng_d = np.random.default_rng([seed, 17]) if disable_risk is not None else None
    b_rem = np.zeros(NP, int)         # 賞与消滅スペルの残年数
    disabled = np.zeros(NP, bool)     # 就労不能の吸収状態
    shock_map = {}
    if shocks:
        for a, m in shocks:
            shock_map[int(a)] = shock_map.get(int(a), 0.0) + float(m)

    risk = np.full(NP, float(risk0))  # 本体リスク資産（オルカン等）
    edu  = np.zeros(NP)               # 教育費別建て口座（こどもNISA、同一リターン）
    cash = np.full(NP, float(cash0))  # 第一層現金（実質リターン0）
    ide  = np.zeros(NP)               # iDeCo口座（受取年齢まで拘束、本体と同一リターン）

    fail_age   = np.full(NP, -1)
    cash_hit   = np.zeros(NP, bool)  # 現金第一層に手を付けたか
    edu_spill  = np.zeros(NP, bool)  # 教育費が本体へ波及したか
    first5     = np.zeros(NP)        # 序盤5年の累積リターン（順序リスク分析用）
    traj       = [] if track else None   # 年齢別パーセンタイル軌跡
    calm_flag  = None                # 状態依存切替の判定結果（65歳時点で確定）
    e_state    = np.zeros(NP)        # AR(1)用のlog-return偏差状態

    for j, age in enumerate(ages):
        if calm65 is not None and calm65_if_above is not None and age == 65:
            calm_flag = (risk + edu + cash) >= float(calm65_if_above)
        mixed = (calm65 is not None and calm65_if_above is not None
                 and age >= 65 and not deterministic)
        if returns_seq is not None:
            # 実史リプレイ: 与えた年次系列をそのまま注入（全パス同一の決定論）
            r = np.full(NP, float(returns_seq[j]))
        elif mixed:
            # パス別に運用レジームを混在（安定化は資産が閾値以上のパスのみ）
            z = boot_z[:, j] if boot_z is not None else rng.standard_normal(NP)
            mu_v = np.where(calm_flag, np.log(1 + calm65[0]), np.log(1 + mu))
            s_v = np.where(calm_flag, calm65[1], sigma)
            r = np.exp(mu_v + mu_off + s_v * z) - 1
        else:
            m, s = (calm65 if (calm65 and age >= 65) else (mu, sigma))
            if deterministic:
                r = np.full(NP, m)
            elif boot_z is not None:
                # 実史形状ブートストラップ: 幾何平均m・対数分散s²は従来と一致
                r = np.exp(np.log(1 + m) + mu_off + s * boot_z[:, j]) - 1
            elif ar1_rho is not None:
                # log-return偏差にAR(1)。定常分散をσ^2に保つ（初年は無条件分布から）
                z = rng.standard_normal(NP)
                if j == 0:
                    e_state = s * z
                else:
                    e_state = ar1_rho * e_state + s * np.sqrt(1 - ar1_rho ** 2) * z
                r = np.exp(np.log(1 + m) + mu_off + e_state) - 1
            else:
                mu_l = np.log(1 + m)          # 中央値複利 = m（プランの複利前提に整合）
                r = np.exp(rng.normal(mu_l + mu_off, s, NP)) - 1
        if crash_year1 is not None and j == 0:   # 初年度暴落の注入（乱数消費は維持）
            r = np.full(NP, float(crash_year1))
        if crash_at is not None and age == int(crash_at[0]):   # 任意年齢の暴落注入
            r = np.full(NP, float(crash_at[1]))
        if j < 5:
            first5 = (1 + first5) * (1 + r) - 1

        risk *= (1 + r)
        edu  *= (1 + r)
        ide  *= (1 + r)
        if cash_real:
            cash *= (1.0 + cash_real)

        # --- 夫死亡シナリオ（決定論）: 死亡年に保険金、以後は遺族家計へ移行
        dead = death is not None and age >= int(death[0])
        if death is not None and age == int(death[0]):
            risk = risk + float(death[1])

        # --- 教育費別建て口座への流入（既定: 児童手当+東京018由来 月1.75万/人、18歳まで）
        c1, c2 = age - C1_OFF, age - C2_OFF
        edu += ((edu_inflow if c1 < 18 else 0.0)
                + (edu_inflow if c2 < 18 else 0.0))

        # --- 教育費支出
        if edu_plan is not None:
            need = _plan_cost(c1, edu_plan["c1"]) + _plan_cost(c2, edu_plan["c2"])
        else:
            need = edu_cost(c1, edu_track) + edu_cost(c2, edu_track)

        working = (age < retire_age) and not dead
        sav_y = save
        if save_cut is not None:
            a0, ny, amt = save_cut
            if int(a0) <= age < int(a0) + int(ny):
                sav_y = float(amt)               # 決定論の貯蓄カット窓
        sav = sav_y if working else 0.0
        if working and (bonus_risk is not None or disable_risk is not None):
            sav = np.full(NP, float(sav))
            if bonus_risk is not None:           # 賞与消滅スペル（k年連続）
                p_b, amt_b, k_b = bonus_risk
                start = (b_rem <= 0) & (rng_b.random(NP) < float(p_b))
                b_rem = np.where(start, int(k_b), b_rem)
                off = b_rem > 0
                b_rem = np.maximum(b_rem - 1, 0)
                sav = np.where(off, np.maximum(sav - float(amt_b), 0.0), sav)
            if disable_risk is not None:         # 就労不能（吸収状態）
                p_d, save_after = disable_risk
                disabled |= rng_d.random(NP) < float(p_d)
                sav = np.where(disabled, float(save_after), sav)
        if ideco is not None:
            i_an, i_ref, i_from, i_until, i_tax = ideco
            if working and int(i_from) <= age < int(i_until):
                sav = sav - float(i_an) + float(i_ref)   # 拠出は貯蓄から振替、節税還付を加算
                ide = ide + float(i_an)
            if age == int(i_until):                      # 一括受取（出口実効税率控除後）を本体へ
                risk = risk + ide * (1.0 - float(i_tax))
                ide = np.zeros(NP)

        # 教育費は (1)当年貯蓄の振替 → (2)別建て口座 → (3)本体 → (4)現金 の順
        use_sav = np.minimum(sav, need)             # savはスカラーまたはパス別ベクトル
        need = need - use_sav
        risk += (sav - use_sav)                     # 余った貯蓄は本体へ
        pay = np.minimum(edu, need);  edu  -= pay
        rem = need - pay
        spill = rem > 1e-9
        edu_spill |= spill
        g = np.minimum(risk, rem / (1.0 - tax_rate))   # 本体売却は課税ハイカット込み
        risk -= g; rem = rem - g * (1.0 - tax_rate)
        pay = np.minimum(cash, rem); cash -= pay; rem_e = rem - pay

        # --- 老後の生活費 − 年金 − 再雇用収入（実質）
        net = 0.0
        if not working:
            if dead:
                # 遺族家計: 支出=以後支出、夫年金の代わりに遺族収入。再雇用なし
                sp = float(death[3])
                pension = float(death[2]) * pension_scale
                if age >= spouse_from:               # 妻自身の年金は従来どおり加算
                    pension += float(pension_spouse) * pension_scale
                income = 0.0
            else:
                sp = spend
                if spend_after70 is not None and age >= int(spend_change_age):
                    sp = spend_after70
                p_start = retire_age if pension_from is None else int(pension_from)
                pension = 0.0
                if age >= p_start:
                    if pension_self is None:
                        # ねんきんネット実データ形状（60歳受給開始年のみ134）は従来互換時のみ
                        p_self = 134.0 if (pension_from is None and age == retire_age) else 146.0
                    else:
                        p_self = float(pension_self)
                    pension = p_self * pension_scale
                if age >= spouse_from:               # 妻の年金（既定: 夫69歳=妻65歳から基礎）
                    pension += float(pension_spouse) * pension_scale
                income = (float(reemploy_income)
                          if (reemploy_until is not None and age < int(reemploy_until)) else 0.0)
            net = sp - pension - income
            if net < 0.0:                            # 収入超過分は本体へ積み増し
                risk += -net
                net = 0.0
            elif guardrail is not None and net > 0.0:
                # 可変支出: 取り崩し率が閾値を超えた年は支出を減額幅だけ絞る
                trig, cut = guardrail
                tight = net / np.maximum(risk + cash, 1.0) > trig
                net_cut = max(0.0, sp * (1.0 - cut) - pension - income)
                net = np.where(tight, net_cut, net)
        g = np.minimum(risk, net / (1.0 - tax_rate))
        risk -= g; rem2 = net - g * (1.0 - tax_rate)
        pay = np.minimum(cash, rem2); cash -= pay; rem_r = rem2 - pay

        # --- 一時支出ショック（介護・リフォーム等、就労中でも発生）
        s_amt = shock_map.get(int(age), 0.0)
        if s_amt > 0:
            g = np.minimum(risk, s_amt / (1.0 - tax_rate))
            risk -= g; rs = s_amt - g * (1.0 - tax_rate)
            pay = np.minimum(cash, rs); cash -= pay; rem_s = rs - pay
        elif s_amt < 0:                              # マイナス=一時収入（相続等）→本体へ
            risk += -s_amt
            rem_s = 0.0
        else:
            rem_s = 0.0

        cash_hit |= (cash < float(cash0) - 0.1)
        depleted = (rem_e > 1e-9) | (rem_r > 1e-9) | (rem_s > 1e-9)
        fail_age = np.where((fail_age < 0) & depleted, age, fail_age)

        if track:
            t = risk + edu + cash + ide
            traj.append(np.percentile(t, [5, 25, 50, 75, 95]))

    total = risk + edu + cash + ide
    ok = fail_age < 0
    # 順序リスク: 序盤5年が累積マイナスだった試行に限定した成功率
    bad_start = first5 < 0
    seq = ok[bad_start].mean() * 100 if bad_start.any() else float("nan")
    out_traj = None
    if track:
        tp = np.array(traj)   # (年数, 5)
        out_traj = {
            "ages": ages.tolist(),
            "p5": tp[:, 0], "p25": tp[:, 1], "p50": tp[:, 2],
            "p75": tp[:, 3], "p95": tp[:, 4],
            "depletion": np.array([((fail_age >= 0) & (fail_age <= a)).mean() * 100
                                   for a in ages]),
        }
    return {
        "score": ok.mean() * 100,
        "trajectory": out_traj,
        "fail_age_med": float(np.median(fail_age[~ok])) if (~ok).any() else None,
        "terminal_p5": float(np.percentile(total, 5)),
        "terminal_p50": float(np.percentile(total, 50)),
        "terminal_p95": float(np.percentile(total, 95)),
        "cash_hit": cash_hit.mean() * 100,
        "edu_spill": edu_spill.mean() * 100,
        "seq_score": seq,
        "bad_start_pct": bad_start.mean() * 100,
    }

def _spouse_shocks(d_age, mode, childcare, funeral, care_cost, insurance,
                   age_end=95):
    """妻側シナリオの年齢別キャッシュフロー表を shocks 形式で構築する。

    正=支出（保育・家事外注、葬儀、介護費）、負=収入（遺族基礎年金/障害基礎年金、
    保険金）。子年齢は夫年齢基準（子①=夫-37、子②=夫-40）。年金額は2026年度近似
    （基礎83万+子加算24万/人、障害基礎2級=満額基礎と同額）。"""
    sh = []
    if insurance:
        sh.append((int(d_age), -float(insurance)))
    if mode == "death" and funeral:
        sh.append((int(d_age), float(funeral)))
    for a in range(int(d_age), int(age_end) + 1):
        c2 = a - C2_OFF                       # 末子(子②)の年齢
        if c2 < 7:
            cc = childcare[0]                 # 未就学: 保育+シッター+家事外注
        elif c2 <= 12:
            cc = childcare[1]                 # 小学生: 学童+外注
        elif c2 <= 15:
            cc = childcare[2]                 # 中学生: 縮小
        else:
            cc = 0.0
        if cc:
            sh.append((a, float(cc)))
        kids = (1 if a - C1_OFF < 18 else 0) + (1 if c2 < 18 else 0)
        if mode == "death":
            ben = (83.0 + 24.0 * kids) if kids else 0.0   # 遺族基礎年金(夫が受給)
        else:
            ben = 83.0 + 24.0 * kids          # 障害基礎年金2級+子加算（終身）
            if care_cost:
                sh.append((a, float(care_cost)))          # 妻の介護・療養費
        if ben:
            sh.append((a, -float(ben)))
    return tuple(sh)


def spouse_scenario(d_age, mode="death", insurance=0.0,
                    childcare=(120.0, 70.0, 30.0), funeral=200.0,
                    care_cost=80.0, **kw):
    """妻の死亡("death")/重度就労不能("disable")シナリオ。

    検証済みプリミティブの合成: 年齢別キャッシュフローを shocks に注入し、
    妻の老齢基礎年金(pension_spouse)は消失（死亡）または障害基礎年金へ置換
    （就労不能、こちらは_spouse_shocks側で終身注入）として0固定にする。
    childcare=(末子未就学, 小学生, 中学生)の年額万円。kwはsimulate()へ。
    遺族基礎年金の夫受給は年収850万未満の生計維持要件を満たす前提（613万<850万）。"""
    if mode not in ("death", "disable"):
        raise ValueError('mode は "death" か "disable"')
    extra = _spouse_shocks(d_age, mode, childcare, funeral, care_cost,
                           insurance, int(kw.get("age_end", 95)))
    base = tuple(tuple(x) for x in (kw.pop("shocks", ()) or ()))
    kw.pop("pension_spouse", None)
    kw.pop("spouse_from", None)
    return simulate(shocks=base + extra, pension_spouse=0.0, **kw)


def historical_sequences(mu=0.04, sigma=0.18, hist_returns=None, hist_years=None,
                         raw=False, **kw):
    """開始年総当たりの実史シーケンス・リプレイ（乱数ゼロ・再現性100%）。

    実史の全開始年について「その年から退役期間が始まっていたら」を決定論で走らせ、
    リターン順序リスク（序盤暴落の致命度）をモンテカルロと別角度で検証する。
    トリニティ・スタディと同じ発想。系列端は循環でつなぐ（56年ホライズン対応）。

    raw=False（既定）: 標準化形状に (mu, sigma) を貼り直して注入。水準はプラン前提・
                       並び順と形状だけ実史 → MC基準ケースと直接比較できる
    raw=True: 実史リターンをそのまま注入（組込系列は名目USDなので解釈注意）
    kw: simulate() に渡す前提（save/spend/retire_age等）。ret_model/ar1_rho/
        crash_year1/calm65系はリプレイでは無効なので渡さないこと
    返り値: {"success_rate", "n_starts", "results"(開始年ごと), "worst"(終端下位5)}
    """
    for bad in ("ret_model", "returns_seq", "deterministic", "track",
                "ar1_rho", "crash_year1", "crash_at", "mu_sd",
                "bonus_risk", "disable_risk", "calm65", "calm65_if_above"):
        if bad in kw:
            raise ValueError(f"historical_sequencesでは {bad} は指定不可"
                             "（リターン側は注入系列が決める。確率的な収入リスクも"
                             "1パスのリプレイでは無意味。deathとsave_cutは決定論なので可）")
    if hist_returns is None:
        hist_years, hr = load_returns()
    else:
        hr = np.asarray(hist_returns, float)
        hist_years = (np.asarray(hist_years) if hist_years is not None
                      else np.arange(len(hr)))
    n_years = int(kw.get("age_end", 95)) - AGE_START + 1
    z = standardized_log_dev(hr)
    results = []
    for i in range(len(hr)):
        idx = sequence_indices(i, n_years, len(hr))
        seq = hr[idx] if raw else np.exp(np.log(1 + mu) + sigma * z[idx]) - 1
        r = simulate(mu=mu, sigma=sigma, returns_seq=seq, n_paths=1, **kw)
        results.append({"start": int(hist_years[i]),
                        "ok": r["score"] > 50.0,
                        "fail_age": r["fail_age_med"],
                        "terminal": r["terminal_p50"],
                        "wrapped": i + n_years > len(hr)})
    ok_n = sum(1 for x in results if x["ok"])
    return {"success_rate": ok_n / len(results) * 100,
            "n_starts": len(results), "n_ok": ok_n,
            "results": results,
            "worst": sorted(results, key=lambda x: x["terminal"])[:5]}


def fmt(name, r):
    fa = f"{r['fail_age_med']:.0f}歳" if r["fail_age_med"] else "—"
    print(f"{name:<44} スコア {r['score']:5.1f} | 枯渇中央値 {fa:>4} | "
          f"終端P5 {r['terminal_p5']:>8,.0f} / P50 {r['terminal_p50']:>8,.0f} | "
          f"現金接触 {r['cash_hit']:4.1f}% | 教育波及 {r['edu_spill']:4.1f}% | "
          f"序盤逆風時 {r['seq_score']:4.1f}%")

if __name__ == "__main__":
    print("=== ライフプラン モンテカルロ検証 (N=20,000, 実質ベース, 万円, 貯蓄200万/年確定版) ===\n")
    fmt("0. 決定論 複利4%固定（プラン従来法・参考）", simulate(deterministic=True))
    fmt("1. 基準ケース 複利4%/σ18%・貯蓄200万", simulate())
    fmt("2. プラン下限 複利3%/σ18%", simulate(mu=0.03))
    fmt("3. 保守 複利2.3%/σ20%（算術4%相当）", simulate(mu=0.023, sigma=0.20))
    fmt("4. 教育ライト分岐（公立高・国公立大）", simulate(edu_track="light"))
    fmt("5. 老後支出420万/年（月35万）", simulate(spend=420))
    fmt("6. 70歳以降320万/年（ローン完済反映）", simulate(spend_after70=320))
    fmt("7. 65歳まで就労", simulate(retire_age=65))
    fmt("8. 65歳以降 安定運用 複利2.5%/σ11%", simulate(calm65=(0.025, 0.11)))
    fmt("9. 年金1割減（マクロ経済スライド）", simulate(pension_scale=0.9))
    fmt("10. 複合悲観 複利3%+年金9掛+支出420万", simulate(mu=0.03, pension_scale=0.9, spend=420))
    fmt("11. 複合改善 教育ライト+70歳以降320万", simulate(edu_track="light", spend_after70=320))
    fmt("12. 貯蓄84万（保守・貯蓄下振れ時）", simulate(save=84))

    print("\n=== ランダム要素の拡張: 実史形状（2026-07-26追加、水準はプランμ/σ貼直し） ===\n")
    fmt("13. ブロックBS(5年) 複利4%/σ18%", simulate(ret_model="bootstrap"))
    fmt("14. ブロックBS(5年) 複利3%/σ18%", simulate(mu=0.03, ret_model="bootstrap"))
    fmt("15. 単純BS(1年・連鎖なし比較用) 複利4%", simulate(ret_model="bootstrap", block_len=1))
    hs = historical_sequences()
    print(f"16. 開始年総当たり(S&P500形状{hs['results'][0]['start']}-"
          f"{hs['results'][-1]['start']}, μ4%/σ18%貼直し): "
          f"成功 {hs['n_ok']}/{hs['n_starts']}開始年 = {hs['success_rate']:.1f}%")
    for w in hs["worst"]:
        fa = f"枯渇{w['fail_age']:.0f}歳" if w["fail_age"] else "完走"
        print(f"    最悪側: {w['start']}年開始 → {fa} / 終端 {w['terminal']:,.0f}万"
              f"{'（循環接続あり）' if w['wrapped'] else ''}")

    print("\n=== 収入リスク・μ不確実性・複合ストレス（2026-07-26第2弾） ===\n")
    fmt("17. 賞与消滅 p=5%/年×2年継続(116万減)", simulate(bonus_risk=(0.05, 116, 2)))
    fmt("18. 賞与消滅 p=10%/年×2年継続", simulate(bonus_risk=(0.10, 116, 2)))
    fmt("19. 就労不能 p=0.2%/年→以後貯蓄84万", simulate(disable_risk=(0.002, 84)))
    fmt("20. 就労不能 p=0.2%/年→以後貯蓄0(保守)", simulate(disable_risk=(0.002, 0)))
    fmt("21. μ不確実性 σμ=0.5%", simulate(mu_sd=0.005))
    fmt("22. μ不確実性 σμ=1%", simulate(mu_sd=0.01))
    fmt("23. 複合: 49歳-40%暴落のみ", simulate(crash_at=(49, -0.40)))
    fmt("24. 複合: 49歳-40%+賞与3年消滅(相関ストレス)",
        simulate(crash_at=(49, -0.40), save_cut=(49, 3, 84)))
    print()
    for ins in (0, 1000, 2000, 3000):
        fmt(f"25. 夫45歳死亡 保険金{ins}万(遺族収入150/支出300 仮定)",
            simulate(death=(45, float(ins), 150.0, 300.0)))
