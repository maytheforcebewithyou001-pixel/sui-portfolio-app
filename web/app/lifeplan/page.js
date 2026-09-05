"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  Cell,
  Line,
  ComposedChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiGet, apiPost } from "../../lib/api";

const TOOLTIP_STYLE = {
  background: "#12121a",
  border: "1px solid #23232f",
  borderRadius: 6,
  fontSize: 12,
  color: "rgba(255,255,255,0.88)",
};
const AXIS_TICK = { fill: "rgba(255,255,255,0.45)", fontSize: 11 };

const fmt0 = (n) => Math.round(n).toLocaleString("ja-JP");
const fmt1 = (n) => (Math.round(n * 10) / 10).toLocaleString("ja-JP", { minimumFractionDigits: 1 });

// ── 既定値（UI初期表示=運用値: save220 + 企業年金一時金-281.15万@60歳。8/16確定） ──
// risk0 はポートフォリオ参照(null=スナップショット確定後に注入)。
// 年金は公的統計の平均値(夫196=男性平均月16.3万×12・妻126=女性平均月10.5万×12、基礎込み)。
// 教育口座への自動流入(こどもNISA)は計上しない(edu_inflow=0、8/16岡部指定)
const DEFAULTS = {
  risk0: null, cash0: 300, save: 220, retireAge: 60,
  mu: 4.0, sigma: 18, retModel: "iid", blockLen: 5,
  spend: 360, use70: false, spend70: 320, loanAge: 70,
  grOn: false, grTrig: 6, grCut: 10,
  reOn: false, reUntil: 65, reIncome: 240,
  pSelf: 196, pFrom: 65, pSp: 126, spFrom: 69, pensionScale: 1.0,
  jhs1: 40, hs1: 150, un1: 250, lo1: 0, same2: true,
  jhs2: 40, hs2: 150, un2: 250, lo2: 0,
  ageEnd: 95, infl: 0, taxh: 0,
  crashOn: false, crashPct: -40, crashAge: 40, ccOn: false, ccYears: 3,
  // 住宅ローン金利ショック(既定OFF)。残高3,000=契約(2021/6借入3,480万・35年・当初0.405%)からの2026/9時点計算値
  // (令和7年控除30.7万=1%×3,060万と整合)。現行金利は契約時の値なので、基準金利改定通知の実行金利に置き換える
  loanOn: false, loanBal: 3000, loanRate: 0.405, loanEnd: 70, loanShockAge: 45, loanDelta: 2,
  shocks: [{ age: 60, amount: -281.15 }],
};

// 元利均等の月額返済(残高と同じ単位)。エンジン loan_shock_extra と同一式(表示用)
function annuityPay(balance, rate, months) {
  if (months <= 0) return 0;
  const r = rate / 12;
  if (Math.abs(r) < 1e-12) return balance / months;
  return (balance * r) / (1 - Math.pow(1 + r, -months));
}

// 金利ショックの返済増分プレビュー(万円)。エンジンと同じ「ショック時点の残高を残期間で再計算」
function loanShockPreview(bal, ratePct, endAge, shockAge, deltaPct) {
  const rate = ratePct / 100;
  const total = (endAge - 40) * 12;
  const k = (shockAge - 40) * 12;
  const basePay = annuityPay(bal, rate, total);
  const r = rate / 12;
  const balK = Math.abs(r) < 1e-12
    ? bal - basePay * k
    : bal * Math.pow(1 + r, k) - (basePay * (Math.pow(1 + r, k) - 1)) / r;
  const newPay = annuityPay(balK, rate + deltaPct / 100, total - k);
  return { basePay, newPay, balK, yearly: (newPay - basePay) * 12, years: Math.max(endAge - shockAge, 0) };
}

// 繰上げ-0.4%/月・繰下げ+0.7%/月の換算(基準=65歳受給額)
function pensionApplied(pSelf, pFrom) {
  const g = pFrom < 65 ? 1 - 0.048 * (65 - pFrom) : 1 + 0.084 * (pFrom - 65);
  return Math.round(pSelf * g * 10) / 10;
}

// GUIの「既定値から動かした時だけ渡す」パターン(179-231行)を踏襲。
// キー未指定=エンジン既定が適用され、従来版との数値一致が保たれる
function buildParams(s) {
  const p = {
    mu: s.mu / 100,
    sigma: s.sigma / 100,
    save: s.save,
    spend: s.spend,
    spend_after70: s.use70 ? s.spend70 : null,
    retire_age: s.retireAge,
    pension_scale: s.pensionScale,
    risk0: s.risk0,               // ポートフォリオ参照値(手入力で上書き可)
    edu_inflow: 0,                // こどもNISA等の教育口座流入は計上しない(8/16指定)
    pension_self: pensionApplied(s.pSelf, s.pFrom),
    pension_from: s.pFrom,
    pension_spouse: s.pSp,
    spouse_from: s.spFrom,
  };
  if (s.cash0 !== 300) p.cash0 = s.cash0;
  if (s.use70 && s.loanAge !== 70) p.spend_change_age = s.loanAge;
  const c1 = [s.jhs1, s.hs1, s.un1, s.lo1];
  const c2 = s.same2 ? c1 : [s.jhs2, s.hs2, s.un2, s.lo2];
  const eduCustom = !(c1.join() === "40,150,250,0" && c2.join() === "40,150,250,0");
  if (eduCustom) p.edu_plan = { c1, c2 };
  if (s.reOn) {
    p.reemploy_until = s.reUntil;
    p.reemploy_income = s.reIncome;
  }
  if (s.ageEnd !== 95) p.age_end = s.ageEnd;
  if (s.infl > 0) p.cash_real = -s.infl / 100;
  if (s.crashOn) {
    if (s.crashAge === 40) p.crash_year1 = s.crashPct / 100;
    else p.crash_at = [s.crashAge, s.crashPct / 100];
    if (s.ccOn) p.save_cut = [s.crashAge, s.ccYears, 84];
  }
  if (s.loanOn && s.loanBal > 0 && s.loanDelta !== 0 && s.loanShockAge < s.loanEnd) {
    p.loan_shock = [s.loanBal, s.loanRate / 100, s.loanEnd, s.loanShockAge, s.loanDelta / 100];
  }
  const rows = s.shocks
    .filter((r) => r.amount !== 0 && r.age >= 40 && r.age <= s.ageEnd)
    .map((r) => [Math.trunc(r.age), r.amount]);
  if (rows.length) p.shocks = rows;
  if (s.grOn) p.guardrail = [s.grTrig / 100, s.grCut / 100];
  if (s.taxh > 0) p.tax_rate = s.taxh / 100;
  if (s.retModel === "bootstrap") {
    p.ret_model = "bootstrap";
    p.block_len = s.blockLen;
  }
  return p;
}

// 「?」トグルで用語の意味とスコアへの影響を表示(ホバーでも title で読める)
function HelpToggle({ help, open, onToggle }) {
  if (!help) return null;
  return (
    <button
      type="button" title={help} onClick={onToggle}
      style={{
        background: "none", border: "1px solid #2a2a38", borderRadius: "50%",
        color: open ? "#00D2FF" : "rgba(255,255,255,0.45)", cursor: "pointer",
        width: 18, height: 18, lineHeight: "15px", fontSize: 11, padding: 0, flex: "0 0 auto",
      }}
    >
      ?
    </button>
  );
}

function NumInput({ label, value, onChange, step = 1, min, max, disabled, help }) {
  const [showHelp, setShowHelp] = useState(false);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6 }}>
        <label className="inlineinput" style={{ margin: 0, opacity: disabled ? 0.45 : 1, flex: 1 }}>
          {label}
          <input
            type="number" value={value} step={step} min={min} max={max} disabled={disabled}
            onChange={(e) => onChange(Number(e.target.value))}
          />
        </label>
        <HelpToggle help={help} open={showHelp} onToggle={() => setShowHelp(!showHelp)} />
      </div>
      {help && showHelp && <p className="caption" style={{ margin: 0 }}>{help}</p>}
    </div>
  );
}

function Check({ label, checked, onChange, help }) {
  const [showHelp, setShowHelp] = useState(false);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <label className="chkrow" style={{ margin: 0, flex: 1 }}>
          <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
          {label}
        </label>
        <HelpToggle help={help} open={showHelp} onToggle={() => setShowHelp(!showHelp)} />
      </div>
      {help && showHelp && <p className="caption" style={{ margin: 0 }}>{help}</p>}
    </div>
  );
}

function Section({ title, open, children }) {
  return (
    <details className="expander" open={open}>
      <summary>{title}</summary>
      <div style={{ display: "flex", flexDirection: "column", gap: "0.55rem", padding: "0.6rem 0.2rem 0.3rem" }}>
        {children}
      </div>
    </details>
  );
}

export default function Lifeplan() {
  const { snap, error, loading, reload } = useSnapshot();
  const [s, setS] = useState(DEFAULTS);
  const set = (k) => (v) => setS((prev) => ({ ...prev, [k]: v }));

  // リスク資産の初期値はポートフォリオ参照(万円換算)。スナップショット確定後に一度だけ注入
  const TA = snap ? snap.totals.total_asset_all ?? snap.totals.total_asset : 0;
  const taMan = TA > 0 ? Math.round(TA / 10000) : null;
  useEffect(() => {
    if (taMan !== null && s.risk0 === null) set("risk0")(taMan);
  }, [taMan, s.risk0]);

  const params = useMemo(() => buildParams(s), [s]);
  const key = JSON.stringify(params);
  const ready = s.risk0 !== null;
  const [res, setRes] = useState(null);
  const [busy, setBusy] = useState(false);
  const [mcErr, setMcErr] = useState(null);

  useEffect(() => {
    if (!ready) return;
    let alive = true;
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const r = await apiPost("/api/lifeplan/mc", { params: JSON.parse(key) });
        if (alive) {
          setRes(r);
          setMcErr(null);
        }
      } catch (e) {
        if (alive) setMcErr(String(e.message || e));
      } finally {
        if (alive) setBusy(false);
      }
    }, 500);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [key, ready]);

  const [yMode, setYMode] = useState("p75");
  const [view, setView] = useState("sim");            // sim | replay | hist
  const [pinned, setPinned] = useState(null);         // A/B比較の固定側 {res, label}
  const [solver, setSolver] = useState({ target: 90, busy: false, result: null, lever: null });
  const [replay, setReplay] = useState({ data: null, busy: false, err: null });
  const [hist, setHist] = useState({ rows: null, busy: false, err: null });
  const [memo, setMemo] = useState("");
  const [saveMsg, setSaveMsg] = useState(null);
  const [ai, setAi] = useState({ busy: false, text: null, err: null });

  // 教育費総額(実質・2人分): 中3年+高3年+(大+下宿)4年
  const eduTotal = useMemo(() => {
    const one = (j, h, u, l) => j * 3 + h * 3 + (u + l) * 4;
    const c1 = one(s.jhs1, s.hs1, s.un1, s.lo1);
    const c2 = s.same2 ? c1 : one(s.jhs2, s.hs2, s.un2, s.lo2);
    return c1 + c2;
  }, [s]);

  const runReplay = async () => {
    setReplay({ data: null, busy: true, err: null });
    try {
      const d = await apiPost("/api/lifeplan/replay", { params });
      setReplay({ data: d, busy: false, err: null });
    } catch (e) {
      setReplay({ data: null, busy: false, err: String(e.message || e) });
    }
  };

  const loadHist = async () => {
    setHist((h) => ({ ...h, busy: true, err: null }));
    try {
      const d = await apiGet("/api/lifeplan/mc/history");
      setHist({ rows: d.history, busy: false, err: null });
    } catch (e) {
      setHist({ rows: null, busy: false, err: String(e.message || e) });
    }
  };

  const saveRun = async () => {
    if (!res) return;
    setSaveMsg("保存中...");
    try {
      const metrics = {
        score: res.score, fail_age_med: res.fail_age_med,
        terminal_p50: res.terminal_p50, terminal_p5: res.terminal_p5,
        cash_hit: res.cash_hit, seq_score: res.seq_score,
      };
      const d = await apiPost("/api/lifeplan/mc/history", { memo, params, metrics });
      setSaveMsg(`保存済み (${d.dt})`);
      setMemo("");
      loadHist();
    } catch (e) {
      setSaveMsg(`保存エラー: ${String(e.message || e)}`);
    }
  };

  const runSolver = async (lever) => {
    setSolver((sv) => ({ ...sv, busy: true, lever, result: null }));
    try {
      const d = await apiPost("/api/lifeplan/solve", { params, target: solver.target, lever });
      setSolver((sv) => ({ ...sv, busy: false, result: { ...d, lever } }));
    } catch (e) {
      setSolver((sv) => ({ ...sv, busy: false, result: { error: String(e.message || e) } }));
    }
  };

  const runAi = async () => {
    if (!res) return;
    setAi({ busy: true, text: null, err: null });
    try {
      const inputs = {
        "信頼スコア": `${res.score.toFixed(1)}%(95歳時点の資産残存確率、推奨帯80〜95%)`,
        "枯渇年齢中央値": res.fail_age_med ? `${Math.round(res.fail_age_med)}歳` : "枯渇なし",
        "終端資産中央値": `${fmt0(res.terminal_p50)}万円(P5 ${fmt0(res.terminal_p5)}万/P95 ${fmt0(res.terminal_p95)}万)`,
        "序盤5年逆風時の成功率": res.seq_score == null ? "—" : `${res.seq_score.toFixed(1)}%`,
        "前提_資産": `リスク資産${fmt0(s.risk0 ?? 0)}万(ポートフォリオ参照)+現金${fmt0(s.cash0)}万`,
        "前提_収支": `年間貯蓄${s.save}万を${s.retireAge}歳まで、老後支出${s.spend}万/年${s.use70 ? `(${s.loanAge}歳以降${s.spend70}万)` : ""}`,
        "前提_リターン": `実質複利${s.mu}%・σ${s.sigma}%(${s.retModel === "bootstrap" ? "実史形状BS" : "対数正規iid"})`,
        "前提_年金": `夫${s.pSelf}万@${s.pFrom}歳・妻${s.pSp}万@夫${s.spFrom}歳(平均値ベース、スケール${s.pensionScale})`,
        "前提_教育費": `総額${fmt0(eduTotal)}万(2人分・実質、教育口座流入なし)`,
        "一時支出": s.shocks.filter((r) => r.amount !== 0).map((r) => `${r.age}歳${r.amount > 0 ? "-" : "+"}${fmt0(Math.abs(r.amount))}万`).join("、") || "なし",
        "住宅ローン金利ショック": params.loan_shock
          ? (() => {
              const v = loanShockPreview(s.loanBal, s.loanRate, s.loanEnd, s.loanShockAge, s.loanDelta);
              return `${s.loanShockAge}歳で${s.loanRate}%→${(s.loanRate + s.loanDelta).toFixed(1)}%(残高${fmt0(s.loanBal)}万、返済 年+${fmt1(v.yearly)}万を${s.loanEnd}歳の完済まで)`;
            })()
          : "なし",
      };
      const d = await apiPost("/api/ai/lifeplan/generate", { inputs });
      setAi({ busy: false, text: d.text, err: null });
    } catch (e) {
      setAi({ busy: false, text: null, err: String(e.message || e) });
    }
  };
  const fan = useMemo(() => {
    if (!res) return null;
    const t = res.trajectory;
    return t.ages.map((age, i) => ({
      age,
      band95: [t.p5[i], t.p95[i]],
      band50: [t.p25[i], t.p75[i]],
      p5: t.p5[i], p25: t.p25[i], p50: t.p50[i], p75: t.p75[i], p95: t.p95[i],
      dep: t.depletion[i],
    }));
  }, [res]);
  const yDomain = useMemo(() => {
    if (!fan) return [0, 1];
    const top = yMode === "p75"
      ? Math.max(...fan.map((d) => d.p75)) * 1.15
      : Math.max(...fan.map((d) => d.p95)) * 1.05;
    return [0, Math.round(top)];
  }, [fan, yMode]);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const score = res?.score;
  const band =
    score == null ? null
      : score > 95 ? { label: "推奨帯超え——支出増や早期退職の余地あり", color: "#00E676" }
      : score >= 80 ? { label: "推奨帯（80〜95%）内 ✅", color: "#00E676" }
      : { label: "推奨帯未達——調整レバーの検討を ⚠️", color: "#FF5252" };

  return (
    <main>
      <TopBar loadedAt={snap.loadedAt} marketFetchedAt={snap.market_fetched_at} loading={loading} onReload={reload} />

      <h3 style={{ marginTop: "0.6rem" }}>🎲 ライフプラン モンテカルロ検証</h3>
      <p className="caption">
        95歳時点の資産残存確率(信頼スコア)を20,000試行で算定。実質ベース・万円。
        リスク資産はポートフォリオから参照、年金は公的統計の平均値、貯蓄は運用値220万/年+企業年金一時金281万@60歳。
        教育口座への自動流入(こどもNISA)は計上しない。研究系レバー(収入リスク・死亡シナリオ等)はローカルGUI側にあります。
      </p>

      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-start", flexWrap: "wrap" }}>
        {/* ── 前提入力 ── */}
        <div style={{ flex: "0 0 300px", minWidth: 280, display: "flex", flexDirection: "column", gap: "0.5rem" }}>
          <Section title="資産・貯蓄" open>
            <NumInput label="リスク資産(万円)" value={s.risk0 ?? 0} onChange={set("risk0")} step={50} min={0} max={30000}
              help="ポートフォリオから参照(現在の総リスク資産評価額を万円換算)。手入力で上書き可、「↺運用値既定に戻す」で参照値へ復帰。増やせば全域で上振れし、序盤暴落への耐性も上がる" />
            <NumInput label="現金・第一層(万円)" value={s.cash0} onChange={set("cash0")} step={50} min={0} max={5000}
              help="三層防衛の第一層。リターン0の緩衝材で枯渇直前の最後の砦。増やしてもスコアへの寄与は小さい(リターンを生まないため)" />
            <NumInput label="年間新規貯蓄(万円/年)" value={s.save} onChange={set("save")} step={10} min={0} max={400}
              help="就労中の年間新規貯蓄。感応度の目安: +20万/年でスコア約+1.7pt。教育費支払年は教育費へ優先充当される" />
            <NumInput label="就労完了年齢" value={s.retireAge} onChange={set("retireAge")} step={1} min={55} max={70}
              help="この年齢で貯蓄が止まり、生活費−年金の取り崩しが始まる。延長は「貯蓄が増える+取り崩し期間が減る」の両効きで大幅改善" />
          </Section>

          <Section title="リターン前提" open>
            <NumInput label="複利リターン(%・実質)" value={s.mu} onChange={set("mu")} step={0.5} min={0} max={7}
              help="株式の実質複利リターン(中央値)。プラン基準4%、σ18%時の算術平均は約+1.7pt上。最も感応度が高いレバー——実測: 4%→3%でスコア88.2→80.3(-7.9pt)" />
            <NumInput label="ボラティリティ σ(%)" value={s.sigma} onChange={set("sigma")} step={1} min={5} max={30}
              help="年次リターンのばらつき。大きいほど下位パスの枯渇が増えてスコア低下(上位パスも伸びるが枯渇確率には下側だけ効く)。μより感応度は低い" />
            <div className="subtabs" style={{ margin: 0 }}>
              {[["iid", "対数正規 i.i.d."], ["bootstrap", "実史形状ブートストラップ"]].map(([k, label]) => (
                <button key={k} className={s.retModel === k ? "active" : ""} onClick={() => set("retModel")(k)}>
                  {label}
                </button>
              ))}
            </div>
            <p className="caption" style={{ margin: 0 }}>
              i.i.d.=正規分布・年次独立(既定)。ブートストラップ=実史(S&P500 1928-2024)の分布形状と暴落→回復の連鎖だけ借り、水準は上のμ・σを貼り直す。実測: 切替で88.2→90.0=正規仮定の方が保守側
            </p>
            {s.retModel === "bootstrap" && (
              <NumInput label="ブロック長(年)" value={s.blockLen} onChange={set("blockLen")} step={1} min={1} max={10}
                help="連続何年をひと塊で実史から抽出するか。5=暴落と回復の並びが保存される。1=単純ブートストラップ(連鎖なし)" />
            )}
          </Section>

          <Section title="老後・年金" open>
            <NumInput label="老後生活費(万円/年・年金差引前)" value={s.spend} onChange={set("spend")} step={12} min={240} max={600}
              help="年金差引前の総支出額(月30万=360。不足分ではなく使う金額そのもの)。年金・再雇用収入はモデルが自動相殺。実測: -10万/年≒+1.3pt=積立増より高効率の改善レバー" />
            <Check label="ローン完済後は支出を変える" checked={s.use70} onChange={set("use70")}
              help="住宅ローン完済以降の支出減を反映(完済年齢は下で調整)。実測: 70歳以降320万に減らすだけで年金スライド▲0.6%級の悪化を単独で吸収できる規模。前倒しするほど改善" />
            {s.use70 && (
              <>
                <NumInput label="完済年齢(支出が変わる年齢)" value={s.loanAge} onChange={set("loanAge")} step={1} min={55} max={90}
                  help="この年齢以降の支出が下の金額に切り替わる。既定70=現行ローンの完済予定" />
                <NumInput label="完済後の支出(万円/年)" value={s.spend70} onChange={set("spend70")} step={12} min={240} max={600}
                  help="こちらも年金差引前の総支出額" />
              </>
            )}
            <Check label="ガードレール支出(下落時に絞る)" checked={s.grOn} onChange={set("grOn")}
              help="取り崩し率が閾値を超えた年だけ生活費を減額する可変支出ルール。「下落しても定額で使い続ける」固定支出前提の悲観バイアスを現実の行動に近づけ、スコアは上がる方向" />
            {s.grOn && (
              <>
                <NumInput label="発動閾値: 取り崩し率(%)" value={s.grTrig} onChange={set("grTrig")} step={1} min={4} max={10}
                  help="その年の取り崩し額÷資産がこの率を超えたら発動。低いほど頻繁に節約する想定になる" />
                <NumInput label="減額幅(%)" value={s.grCut} onChange={set("grCut")} step={5} min={5} max={25}
                  help="発動年に生活費を何%絞るか" />
              </>
            )}
            <Check label="再雇用(退職後の減収勤務)" checked={s.reOn} onChange={set("reOn")}
              help="退職後の減収勤務。収入は生活費と相殺し、余剰は本体へ積み増し。実測: 60〜64歳を月10万(120万/年)で+2.7pt。65歳以降も働く想定は年齢を延ばして反映" />
            {s.reOn && (
              <>
                <NumInput label="再雇用は何歳まで" value={s.reUntil} onChange={set("reUntil")} step={1} min={61} max={75}
                  help="この年齢の前年まで働く。65超に延ばせば年金と併給しながらの就労を表現できる" />
                <NumInput label="再雇用の手取り(万円/年)" value={s.reIncome} onChange={set("reIncome")} step={10} min={0} max={500} />
              </>
            )}
            <NumInput label="夫の年金(万円/年・65歳受給額)" value={s.pSelf} onChange={set("pSelf")} step={2} min={80} max={280}
              help="既定196=厚生年金受給者男性の平均値(平均年金月額約16.3万×12、基礎年金含む・令和5年度末)。ねんきんネットの見込額があれば置き換えると精度が上がる" />
            <NumInput label="夫年金の受給開始年齢" value={s.pFrom} onChange={set("pFrom")} step={1} min={60} max={75}
              help="繰上げ-0.4%/月・繰下げ+0.7%/月で受給額を自動換算(60歳=-24%、70歳=+42%)。遅らせるほど年額は増えるが、その間は資産取り崩しで凌ぐことになる" />
            {s.pFrom !== 65 && (
              <p className="caption" style={{ margin: 0 }}>
                → 適用額 {fmt1(pensionApplied(s.pSelf, s.pFrom))}万円/年（{s.pFrom}歳から。繰上げ-0.4%/月・繰下げ+0.7%/月換算）
              </p>
            )}
            <NumInput label="妻の年金(万円/年)" value={s.pSp} onChange={set("pSp")} step={5} min={0} max={200}
              help="既定126=厚生年金受給者女性の平均値(平均年金月額約10.5万×12、基礎含む)。専業主婦期間が長い場合は基礎満額80前後へ下げる" />
            <NumInput label="妻年金の開始(夫の年齢)" value={s.spFrom} onChange={set("spFrom")} step={1} min={61} max={75}
              help="既定69=4歳差の妻が65歳になる時点" />
            <NumInput label="年金スケール(1.0=満額)" value={s.pensionScale} onChange={set("pensionScale")} step={0.05} min={0.7} max={1.1}
              help="年金額全体への一括乗数。マクロ経済スライドによる実質減の検証用。実測(8/11試算): スライド▲0.4〜0.9%×25年相当でスコア85.8〜83.1(-2.4〜-5.1pt)" />
          </Section>

          <Section title="教育費(万円/年)">
            <p className="caption" style={{ margin: 0 }}>
              年額単価の目安: 公立中40・私立中140／公立高40・私立高150／国公立大120・私立大250。
              既定=プラン基準(公立中→私立高→私立大)。支払いは当年貯蓄→本体→現金の順(こどもNISA等の教育口座流入は計上しない)。
              私立→公立系へ下げると改善、私立中や下宿を足すと教育ピーク(55〜59歳)の本体負担が増えて低下
            </p>
            <NumInput label="子① 中学" value={s.jhs1} onChange={set("jhs1")} step={10} min={40} max={200}
              help="中学3年間(子①が12〜14歳=夫49〜51歳)の年額" />
            <NumInput label="子① 高校" value={s.hs1} onChange={set("hs1")} step={10} min={40} max={200}
              help="高校3年間(15〜17歳)の年額" />
            <NumInput label="子① 大学" value={s.un1} onChange={set("un1")} step={10} min={0} max={300}
              help="大学4年間(18〜21歳)の年額" />
            <NumInput label="子① 下宿加算(大学期)" value={s.lo1} onChange={set("lo1")} step={10} min={0} max={200}
              help="下宿・仕送りがある場合の大学期上乗せ(家賃+生活費補助で年100〜150万が相場)" />
            <Check label="子②も同じ" checked={s.same2} onChange={set("same2")} />
            {!s.same2 && (
              <>
                <NumInput label="子② 中学" value={s.jhs2} onChange={set("jhs2")} step={10} min={40} max={200} />
                <NumInput label="子② 高校" value={s.hs2} onChange={set("hs2")} step={10} min={40} max={200} />
                <NumInput label="子② 大学" value={s.un2} onChange={set("un2")} step={10} min={0} max={300} />
                <NumInput label="子② 下宿加算(大学期)" value={s.lo2} onChange={set("lo2")} step={10} min={0} max={200} />
              </>
            )}
          </Section>

          <Section title="ストレス・詳細">
            <NumInput label="検討終了年齢" value={s.ageEnd} onChange={set("ageEnd")} step={1} min={90} max={105}
              help="スコア=この年齢まで資産が残る確率。長寿リスクの感応度確認用——延ばすほど取り崩し期間が伸びてスコア低下" />
            <NumInput label="インフレ率(%・現金の実質目減り)" value={s.infl} onChange={set("infl")} step={0.5} min={0} max={4}
              help="現金第一層の実質リターン=−インフレ率として作用。株式・生活費・教育費は実質ベースで織込済み、年金の実質減は年金スケールで別途表現する" />
            <NumInput label="取り崩し課税ハイカット(%)" value={s.taxh} onChange={set("taxh")} step={1} min={0} max={15}
              help="特定口座の譲渡益課税20.315%×含み益率の実効値(含み益5割なら約10%)。本体からの取り崩しにのみ適用、こどもNISA・現金は非課税扱い" />
            <Check label="暴落を注入(ストレステスト)" checked={s.crashOn} onChange={set("crashOn")}
              help="指定年齢のリターンを固定下落に差し替える。全パス共通の決定論ストレス——「その年に必ず暴落したら」の下限確認用" />
            {s.crashOn && (
              <>
                <NumInput label="下落率(%)" value={s.crashPct} onChange={set("crashPct")} step={5} min={-60} max={-10}
                  help="-40%=リーマン級。-20%=よくある弱気相場" />
                <NumInput label="暴落の年齢" value={s.crashAge} onChange={set("crashAge")} step={1} min={40} max={94}
                  help="40=今すぐ(回復期間が長く意外と軽傷)。49=教育費突入直前が急所——資産が育った直後に大型支出が始まりリカバリー時間がない" />
                <Check label="同時に賞与も消滅(相関ストレス)" checked={s.ccOn} onChange={set("ccOn")}
                  help="2008年型=資産下落と収入減が同時に来る想定。暴落年から貯蓄を84万/年(賞与ゼロ相当)に落とす" />
                {s.ccOn && (
                  <NumInput label="賞与消滅の年数" value={s.ccYears} onChange={set("ccYears")} step={1} min={1} max={5} />
                )}
              </>
            )}
            <Check label="住宅ローン金利ショック" checked={s.loanOn} onChange={set("loanOn")}
              help="変動金利がショック年齢で一気に上がり以後戻らない決定論ストレス。返済増分(元利均等で即時再計算。5年・125%ルールは適用せず保守側)を就労中は年間貯蓄から差し引き、退職後は老後支出に上乗せ、完済年齢で消える。団信前提で死亡後は適用しない。実測(実運用基準94.2・残高3,000万): 45歳で+2pt→92.2、+3pt→90.8、41歳で+3pt→89.4" />
            {s.loanOn && (
              <>
                <NumInput label="ローン残高(万円・現在)" value={s.loanBal} onChange={set("loanBal")} step={100} min={0} max={20000}
                  help="既定3,000=2021年6月借入3,480万・35年・0.405%の2026年9月時点残高(元利均等で計算、控除30.7万=1%×3,060万と整合)。残高照会の値があれば置き換えて" />
                <NumInput label="現行金利(%)" value={s.loanRate} onChange={set("loanRate")} step={0.005} min={0} max={10}
                  help="優遇後の実行金利=基準金利−引下げ幅2.370%。既定0.405は契約時の値で、2024年以降の基準金利引き上げ分は未反映——直近の改定通知の実行金利に置き換えて" />
                <NumInput label="完済年齢" value={s.loanEnd} onChange={set("loanEnd")} step={1} min={41} max={105}
                  help="この年齢から返済なし。上の「完済年齢(支出が変わる年齢)」と揃える" />
                <NumInput label="金利上昇の年齢" value={s.loanShockAge} onChange={set("loanShockAge")} step={1} min={40} max={104}
                  help="早いほど残高が大きく残期間も長いので痛い。住宅ローン控除が切れる入居13年後の前後を試すのが実用的" />
                <NumInput label="上昇幅(%pt)" value={s.loanDelta} onChange={set("loanDelta")} step={0.5} min={-5} max={15}
                  help="+2=0.405%→2.405%。日本の変動金利は短プラ連動で政策金利に追随する。予想を当てるのではなく「どこまで上がっても平気か」の閾値を探す用途" />
                {s.loanShockAge >= s.loanEnd ? (
                  <p className="caption" style={{ margin: 0, color: "var(--gold)" }}>⚠ 金利上昇の年齢は完済年齢より前にして(未適用)</p>
                ) : (() => {
                  const v = loanShockPreview(s.loanBal, s.loanRate, s.loanEnd, s.loanShockAge, s.loanDelta);
                  return (
                    <p className="caption" style={{ margin: 0 }}>
                      → 月返済 {fmt1(v.basePay)}万 → {fmt1(v.newPay)}万(年{v.yearly >= 0 ? "+" : ""}{fmt1(v.yearly)}万)を
                      {s.loanShockAge}〜{s.loanEnd - 1}歳の{v.years}年間計上。ショック時点の残高 {fmt0(v.balK)}万
                    </p>
                  );
                })()}
              </>
            )}
            <p className="caption" style={{ margin: "0.3rem 0 0" }}>
              一時支出(介護・リフォーム・車等)。マイナス金額=一時収入(相続・退職一時金等)。
              既定の-281.15万@60歳=企業年金一時金(実測+1.4pt)。同年齢に複数行あれば合算される
            </p>
            {s.shocks.map((row, i) => (
              <div key={i} style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                <NumInput label="年齢" value={row.age}
                  onChange={(v) => set("shocks")(s.shocks.map((r, j) => (j === i ? { ...r, age: v } : r)))}
                  step={1} min={40} max={105} />
                <NumInput label="金額(万円)" value={row.amount}
                  onChange={(v) => set("shocks")(s.shocks.map((r, j) => (j === i ? { ...r, amount: v } : r)))}
                  step={10} />
                <button className="ghost" onClick={() => set("shocks")(s.shocks.filter((_, j) => j !== i))}>✕</button>
              </div>
            ))}
            <button className="ghost" onClick={() => set("shocks")([...s.shocks, { age: 80, amount: 0 }])}>
              ＋ 一時支出を追加
            </button>
          </Section>

          <button className="ghost" onClick={() => setS({ ...DEFAULTS, risk0: taMan })}>↺ 運用値既定に戻す</button>
        </div>

        {/* ── 結果表示 ── */}
        <div style={{ flex: "1 1 480px", minWidth: 320 }}>
          <div className="subtabs">
            {[["sim", "シミュレーション"], ["replay", "開始年リプレイ"], ["hist", "実行履歴"]].map(([k, label]) => (
              <button key={k} className={view === k ? "active" : ""}
                onClick={() => { setView(k); if (k === "hist" && hist.rows === null) loadHist(); }}>
                {label}
              </button>
            ))}
          </div>

          {view === "sim" && (<>
          {mcErr && <p className="status">計算エラー: {mcErr}</p>}
          {res && (
            <>
              <div className="grid3" style={{ marginBottom: "0.6rem" }}>
                <div className="scard">
                  <h4>信頼スコア</h4>
                  <p className="mv" style={{ color: band.color }}>{score.toFixed(1)}<span>%</span></p>
                  <p className="sv" style={{ color: band.color }}>{band.label}</p>
                </div>
                <div className="scard">
                  <h4>枯渇年齢 中央値</h4>
                  <p className="mv">{res.fail_age_med ? `${Math.round(res.fail_age_med)}歳` : "枯渇なし"}</p>
                </div>
                <div className="scard">
                  <h4>{s.ageEnd}歳時点 中央値</h4>
                  <p className="mv">{fmt0(res.terminal_p50)}<span>万</span></p>
                  <p className="sv">P5 {fmt0(res.terminal_p5)}万 / P95 {fmt0(res.terminal_p95)}万</p>
                </div>
              </div>
              <div className="grid3" style={{ marginBottom: "0.8rem" }}>
                <div className="scard">
                  <h4>現金接触率</h4>
                  <p className="mv">{res.cash_hit.toFixed(1)}<span>%</span></p>
                  <p className="sv">第一層現金に手を付けた確率</p>
                </div>
                <div className="scard">
                  <h4>教育費 総額</h4>
                  <p className="mv">{fmt0(eduTotal)}<span>万</span></p>
                  <p className="sv">2人分・実質(49〜61歳に集中)</p>
                </div>
                <div className="scard">
                  <h4>序盤5年逆風時の成功率</h4>
                  <p className="mv">{res.seq_score == null ? "—" : `${res.seq_score.toFixed(1)}%`}</p>
                  <p className="sv">順序リスク耐性(逆風試行 {res.bad_start_pct.toFixed(1)}%)</p>
                </div>
              </div>

              <div className="subtabs">
                {[["p75", "P75基準(拡大)"], ["p95", "P95まで(全体)"]].map(([k, label]) => (
                  <button key={k} className={yMode === k ? "active" : ""} onClick={() => setYMode(k)}>
                    {label}
                  </button>
                ))}
              </div>
              <div className="chartbox">
                <ResponsiveContainer width="100%" height={360}>
                  <ComposedChart data={fan} margin={{ top: 10, right: 14, bottom: 4, left: 10 }}>
                    <XAxis dataKey="age" tick={AXIS_TICK} stroke="#1E232F" domain={[40, s.ageEnd]}
                      type="number" allowDecimals={false} tickCount={12} />
                    <YAxis tickFormatter={(v) => v.toLocaleString("ja-JP")} tick={AXIS_TICK} stroke="#1E232F"
                      width={72} domain={yDomain} allowDataOverflow />
                    <Tooltip
                      contentStyle={TOOLTIP_STYLE}
                      labelFormatter={(l) => `${l}歳`}
                      formatter={(v, name) => {
                        if (Array.isArray(v)) return null;
                        return [`${fmt0(v)}万`, name];
                      }}
                    />
                    <Area dataKey="band95" name="P5-P95" stroke="none" fill="#1f77b4" fillOpacity={0.15} isAnimationActive={false} />
                    <Area dataKey="band50" name="P25-P75" stroke="none" fill="#1f77b4" fillOpacity={0.3} isAnimationActive={false} />
                    <Line dataKey="p50" name="中央値" stroke="#d62728" strokeWidth={2.5} dot={false} isAnimationActive={false} />
                    <Line dataKey="p5" name="P5" stroke="rgba(255,255,255,0.25)" strokeWidth={1} dot={false} isAnimationActive={false} />
                    <ReferenceLine x={s.retireAge} stroke="rgba(255,255,255,0.25)" strokeDasharray="4 4"
                      label={{ value: "就労完了", position: "insideTopLeft", fill: "rgba(255,255,255,0.45)", fontSize: 10 }} />
                    {s.crashOn && (
                      <ReferenceLine x={s.crashAge} stroke="#FF5252" strokeDasharray="4 4"
                        label={{ value: `暴落${s.crashPct}%`, position: "insideTopRight", fill: "#FF5252", fontSize: 10 }} />
                    )}
                    {params.loan_shock && (
                      <ReferenceLine x={s.loanShockAge} stroke="#FFD54F" strokeDasharray="4 4"
                        label={{ value: `金利+${s.loanDelta}%`, position: "insideBottomRight", fill: "#FFD54F", fontSize: 10 }} />
                    )}
                  </ComposedChart>
                </ResponsiveContainer>
                <p className="caption" style={{ paddingLeft: "0.4rem" }}>
                  総資産(本体+教育口座+現金)の分布推移。薄い帯=P5〜P95、濃い帯=P25〜P75、赤線=中央値。
                  P5が0に張り付く年齢が「下位5%シナリオの枯渇時期」
                </p>
              </div>

              <div className="chartbox" style={{ marginTop: "0.8rem" }}>
                <ResponsiveContainer width="100%" height={220}>
                  <AreaChart data={fan} margin={{ top: 10, right: 14, bottom: 4, left: 10 }}>
                    <XAxis dataKey="age" tick={AXIS_TICK} stroke="#1E232F" domain={[40, s.ageEnd]}
                      type="number" allowDecimals={false} tickCount={12} />
                    <YAxis tickFormatter={(v) => `${v}%`} tick={AXIS_TICK} stroke="#1E232F" width={52} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(l) => `${l}歳`}
                      formatter={(v) => [`${v.toFixed(1)}%`, "累積枯渇確率"]} />
                    <Area dataKey="dep" name="累積枯渇確率" stroke="#d62728" strokeWidth={1.5}
                      fill="#d62728" fillOpacity={0.35} isAnimationActive={false} />
                  </AreaChart>
                </ResponsiveContainer>
                <p className="caption" style={{ paddingLeft: "0.4rem" }}>
                  その年齢までに資産が尽きた試行の割合。{s.ageEnd}歳時点の値 = 100 − 信頼スコア
                </p>
              </div>

              {/* ── 目標逆算ソルバー ── */}
              <div className="scard" style={{ marginTop: "0.8rem" }}>
                <h4>🎯 目標スコア逆算</h4>
                <div style={{ display: "flex", gap: "0.6rem", alignItems: "flex-end", flexWrap: "wrap", marginTop: "0.4rem" }}>
                  <NumInput label="目標スコア(%)" value={solver.target}
                    onChange={(v) => setSolver((sv) => ({ ...sv, target: v }))} step={1} min={50} max={99} />
                  <button className="ghost" disabled={solver.busy} onClick={() => runSolver("save")}>貯蓄増で逆算</button>
                  <button className="ghost" disabled={solver.busy} onClick={() => runSolver("spend")}>支出減で逆算</button>
                </div>
                {solver.busy && <p className="caption">二分探索中(十数回シミュレーション)...</p>}
                {solver.result && !solver.busy && (
                  <p className="caption" style={{ marginTop: "0.4rem" }}>
                    {solver.result.error ? `エラー: ${solver.result.error}`
                      : solver.result.already ? `現条件で既に目標達成(スコア${solver.result.score.toFixed(1)}%)`
                      : !solver.result.achievable
                        ? `${solver.result.lever === "save" ? "貯蓄400万/年" : "支出240万/年"}の上限でも届かない(上限時${solver.result.score.toFixed(1)}%)——複数レバーの併用が必要`
                        : solver.result.lever === "save"
                          ? `年間貯蓄を ${fmt1(solver.result.needed_value)}万円 へ増額(現${fmt0(solver.result.current_value)}万、+${fmt1(solver.result.needed_value - solver.result.current_value)}万)でスコア${solver.result.score.toFixed(1)}%`
                          : `老後支出を ${fmt1(solver.result.needed_value)}万円/年 へ削減(現${fmt0(solver.result.current_value)}万、-${fmt1(solver.result.current_value - solver.result.needed_value)}万)でスコア${solver.result.score.toFixed(1)}%`}
                  </p>
                )}
              </div>

              {/* ── A/B比較 ── */}
              <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", marginTop: "0.8rem", flexWrap: "wrap" }}>
                <button className="ghost" onClick={() => setPinned({ res, eduTotal, risk0: s.risk0 })}>
                  📌 この結果を比較に固定
                </button>
                {pinned && <button className="ghost" onClick={() => setPinned(null)}>固定解除</button>}
              </div>
              {pinned && res && (
                <div className="tablewrap tight" style={{ marginTop: "0.5rem" }}>
                  <table>
                    <thead>
                      <tr><th>指標</th><th>固定(A)</th><th>現在(B)</th><th>Δ</th></tr>
                    </thead>
                    <tbody>
                      {[
                        ["信頼スコア(%)", pinned.res.score, res.score, 1],
                        ["終端P50(万)", pinned.res.terminal_p50, res.terminal_p50, 0],
                        ["終端P5(万)", pinned.res.terminal_p5, res.terminal_p5, 0],
                        ["現金接触率(%)", pinned.res.cash_hit, res.cash_hit, 1],
                        ["序盤逆風時(%)", pinned.res.seq_score ?? NaN, res.seq_score ?? NaN, 1],
                        ["教育費総額(万)", pinned.eduTotal, eduTotal, 0],
                      ].map(([label, a, b, dp]) => {
                        const d = b - a;
                        return (
                          <tr key={label}>
                            <td>{label}</td>
                            <td>{Number.isFinite(a) ? a.toFixed(dp) : "—"}</td>
                            <td>{Number.isFinite(b) ? b.toFixed(dp) : "—"}</td>
                            <td style={{ color: d >= 0 ? "#00E676" : "#FF5252" }}>
                              {Number.isFinite(d) ? `${d >= 0 ? "+" : ""}${d.toFixed(dp)}` : "—"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}

              {/* ── AI所見(である調・AIライフプラン履歴へ保存) ── */}
              <div style={{ marginTop: "0.8rem" }}>
                <button className="ghost" disabled={ai.busy} onClick={runAi}>
                  {ai.busy ? "生成中..." : "🤖 この結果でAI所見を生成"}
                </button>
                {ai.err && <p className="status">AI生成エラー: {ai.err}</p>}
                {ai.text && (
                  <div className="aireport" style={{ marginTop: "0.5rem" }}>
                    <div className="md" style={{ whiteSpace: "pre-wrap" }}>{ai.text}</div>
                    <p className="caption">AI総評タブのライフプラン履歴にも保存済み</p>
                  </div>
                )}
              </div>

              <details className="expander" style={{ marginTop: "0.8rem" }}>
                <summary>モデルの前提と限界</summary>
                <div className="md" style={{ padding: "0.6rem 0.4rem" }}>
                  <ul>
                    <li>実質ベース: 生活費・教育費・年金は今日の円価値で一定。現金の実質リターン0</li>
                    <li>年金: 夫=ねんきんネット試算(60歳134万→61歳以降146万/年)、妻=基礎80万/年を夫69歳から(仮定)</li>
                    <li>妻の勤労収入はゼロ仮定(実態があれば上振れ要因)</li>
                    <li>教育費: 別建て口座(流入42万/年、各子18歳まで)→当年貯蓄振替→本体→現金の順で充当</li>
                    <li>リターン: 既定=年次i.i.d.対数正規。「複利4%」は中央値複利=4%の意味(算術平均≈5.7%)</li>
                    <li>実史形状: ブートストラップは実史(S&P500 1928-2024)の形状・連鎖のみ借り、水準はμ・σを貼り直す</li>
                    <li>住宅ローン: 返済は生活費・貯蓄の裏側に内包。金利ショックは元利均等の即時再計算(5年・125%ルール非適用=キャッシュフローは保守側)、1回で以後戻らない決定論、団信前提で死亡後は不適用</li>
                    <li>収入リスク・死亡保障・状態依存切替などの研究系レバーはローカルのStreamlit GUIで検証する</li>
                  </ul>
                </div>
              </details>
            </>
          )}
          {busy && <p className="caption">計算中...</p>}
          {!res && !busy && !mcErr && <p className="status">シミュレーション待機中...</p>}
          </>)}

          {view === "replay" && (
            <>
              <p className="caption">
                実史の全開始年リプレイ(乱数ゼロの決定論・トリニティ・スタディ方式)——
                「その年から市場履歴が始まっていたら」をS&P500の1928〜2024年全開始年で走らせ、
                モンテカルロと別角度でリターン順序リスクを検証する。系列の形状と並び順だけ借りて水準は現在のμ・σを貼り直すため、左のMCと直接比較できるわ。
              </p>
              <button className="ghost" disabled={replay.busy || !ready} onClick={runReplay}>
                {replay.busy ? "97開始年をリプレイ中..." : "▶ 現在の条件でリプレイ実行"}
              </button>
              {replay.err && <p className="status">エラー: {replay.err}</p>}
              {replay.data && (
                <>
                  <div className="grid3" style={{ margin: "0.8rem 0" }}>
                    <div className="scard">
                      <h4>完走した開始年</h4>
                      <p className="mv">{replay.data.n_ok} / {replay.data.n_starts}</p>
                      <p className="sv">{replay.data.success_rate.toFixed(1)}%</p>
                    </div>
                    <div className="scard">
                      <h4>最悪の開始年</h4>
                      {(() => {
                        const worst = [...replay.data.results].sort((a, b) => a.terminal - b.terminal)[0];
                        return (
                          <>
                            <p className="mv">{worst.start}年</p>
                            <p className="sv">終端 {fmt0(worst.terminal)}万{worst.fail_age ? ` / 枯渇${Math.round(worst.fail_age)}歳` : ""}</p>
                          </>
                        );
                      })()}
                    </div>
                    <div className="scard">
                      <h4>終端資産 中央値</h4>
                      {(() => {
                        const t = replay.data.results.map((r) => r.terminal).sort((a, b) => a - b);
                        return <p className="mv">{fmt0(t[Math.floor(t.length / 2)])}<span>万</span></p>;
                      })()}
                    </div>
                  </div>
                  {replay.data.dropped.length > 0 && (
                    <p className="caption">⚠ リプレイでは無効の設定を除外: {replay.data.dropped.join(", ")}(注入系列が全年のリターンを決めるため)</p>
                  )}
                  <div className="chartbox">
                    <ResponsiveContainer width="100%" height={340}>
                      <BarChart data={replay.data.results} margin={{ top: 10, right: 14, bottom: 4, left: 10 }}>
                        <XAxis dataKey="start" tick={AXIS_TICK} stroke="#1E232F"
                          ticks={replay.data.results.map((r) => r.start).filter((y) => y % 10 === 0)} />
                        <YAxis tickFormatter={(v) => v.toLocaleString("ja-JP")} tick={AXIS_TICK} stroke="#1E232F" width={72} />
                        <Tooltip contentStyle={TOOLTIP_STYLE} labelFormatter={(l) => `${l}年開始`}
                          formatter={(v, _n, e) => [`${fmt0(v)}万${e?.payload?.fail_age ? `(枯渇${Math.round(e.payload.fail_age)}歳)` : ""}`, "95歳時点"]} />
                        <Bar dataKey="terminal" isAnimationActive={false}>
                          {replay.data.results.map((e, i) => (
                            <Cell key={i} fill={e.ok ? "#1f77b4" : "#d62728"} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                    <p className="caption" style={{ paddingLeft: "0.4rem" }}>
                      青=完走・赤=枯渇。悪い開始年の常連=1929年型・1973-74年型・2000年型の序盤直撃パターン。
                      56年に足りない開始年は系列先頭へ循環接続
                    </p>
                  </div>
                </>
              )}
            </>
          )}

          {view === "hist" && (
            <>
              <p className="caption">
                実行履歴はスプレッドシートのLifeplanHistoryシートに保存(年次7/15のスコア記録用)。
                パラメータJSONごと保存するから、年金平均値化のような前提変更をまたいでも条件を完全再現できるわ
              </p>
              <div style={{ display: "flex", gap: "0.6rem", alignItems: "flex-end", flexWrap: "wrap" }}>
                <label className="inlineinput" style={{ margin: 0, flex: "1 1 220px" }}>
                  メモ(例: 年次点検2026 / 教育ライト検討)
                  <input type="text" value={memo} maxLength={100} onChange={(e) => setMemo(e.target.value)} />
                </label>
                <button className="ghost" disabled={!res} onClick={saveRun}>💾 現在の結果を保存</button>
                <button className="ghost" disabled={hist.busy} onClick={loadHist}>🔄 再読込</button>
              </div>
              {saveMsg && <p className="caption">{saveMsg}</p>}
              {hist.err && <p className="status">履歴取得エラー: {hist.err}</p>}
              {hist.busy && <p className="caption">読込中...</p>}
              {hist.rows && hist.rows.length === 0 && <p className="status">履歴はまだないわ。「現在の結果を保存」が最初の1件になる。</p>}
              {hist.rows && hist.rows.length > 0 && (
                <div className="tablewrap tight" style={{ marginTop: "0.6rem" }}>
                  <table>
                    <thead>
                      <tr><th>日時</th><th>メモ</th><th>スコア</th><th>終端P50(万)</th><th>現金接触</th><th>主な前提</th></tr>
                    </thead>
                    <tbody>
                      {hist.rows.map((r, i) => (
                        <tr key={i}>
                          <td>{r.dt}</td>
                          <td>{r.memo}</td>
                          <td>{r.score != null ? `${r.score.toFixed(1)}%` : "—"}</td>
                          <td>{r.metrics.terminal_p50 != null ? fmt0(r.metrics.terminal_p50) : "—"}</td>
                          <td>{r.metrics.cash_hit != null ? `${Number(r.metrics.cash_hit).toFixed(1)}%` : "—"}</td>
                          <td className="caption" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {Object.entries(r.params).filter(([k]) => ["risk0", "save", "spend", "mu"].includes(k))
                              .map(([k, v]) => `${k}=${k === "mu" ? `${(v * 100).toFixed(1)}%` : fmt0(v)}`).join(" ") || "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}
