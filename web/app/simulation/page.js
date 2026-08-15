"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  LabelList,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiPost } from "../../lib/api";
import { fmtInt, fmtIntTrunc } from "../../lib/format";

const TOOLTIP_STYLE = {
  background: "#12121a",
  border: "1px solid #23232f",
  borderRadius: 6,
  fontSize: 12,
  color: "rgba(255,255,255,0.88)",
};
const AXIS_TICK = { fill: "rgba(255,255,255,0.45)", fontSize: 11 };
const LEGEND_STYLE = { fontSize: 12, color: "rgba(255,255,255,0.7)" };

const SUBTABS = [
  { key: "goal", label: "🎯 ゴール逆算" },
  { key: "future", label: "🚀 資産推移" },
  { key: "acc", label: "💰 積立シム" },
  { key: "wd", label: "🏔️ 取り崩しシム" },
];

// 入力変更を400msデバウンスしてAPIへ
function useDebouncedSim(payload, path, enabled) {
  const [rows, setRows] = useState(null);
  const [busy, setBusy] = useState(false);
  const key = JSON.stringify(payload);
  useEffect(() => {
    if (!enabled) return;
    let alive = true;
    setBusy(true);
    const t = setTimeout(async () => {
      try {
        const res = await apiPost(path, JSON.parse(key));
        if (alive) setRows(res.rows);
      } catch {
        if (alive) setRows(null);
      } finally {
        if (alive) setBusy(false);
      }
    }, 400);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [key, path, enabled]);
  return { rows, busy };
}

function NumInput({ label, value, onChange, step = 1, min, max }) {
  return (
    <label className="inlineinput" style={{ margin: 0 }}>
      {label}
      <input
        type="number" value={value} step={step} min={min} max={max}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

// ── ゴール逆算(tab_simulation.py:10-22、タブ内ロジックのため同式をJS実装) ──
function GoalSection({ TA, goalOku, ratePct }) {
  const goal = goalOku * 1e8;
  const r = ratePct / 100;
  const data = [10, 15, 20, 25, 30].map((y) => {
    const sf = goal - TA * Math.pow(1 + r, y);
    const pm = sf > 0 ? sf / ((Math.pow(1 + r, y) - 1) / r) : 0;
    return { label: `${y}年後`, value: pm, text: pm > 0 ? `${fmtIntTrunc(pm)}円` : "達成確実！" };
  });
  // recharts はゼロ値バーのラベルを描かないため、極小のプロット値でラベルだけ成立させる
  const maxPm = Math.max(...data.map((d) => d.value), 1);
  data.forEach((d) => { d.plot = d.value > 0 ? d.value : maxPm * 0.004; });
  return (
    <>
      <h3>🎯 {goalOku}億円ゴール 年間必要積立額 (年利{ratePct}%)</h3>
      <div className="chartbox">
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={data} layout="vertical" margin={{ top: 10, right: 120, bottom: 10, left: 10 }}>
            <XAxis type="number" tickFormatter={(v) => `${v.toLocaleString("ja-JP")}円`} tick={AXIS_TICK} stroke="#1E232F" />
            <YAxis type="category" dataKey="label" width={70} tick={{ ...AXIS_TICK, fill: "rgba(255,255,255,0.88)" }} stroke="#1E232F" />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(v, _n, entry) => [entry?.payload?.text ?? `${fmtInt(v)}円`, "年間積立額"]}
            />
            <Bar dataKey="plot" fill="#00D2FF" isAnimationActive={false} barSize={22} radius={[0, 4, 4, 0]}>
              <LabelList
                dataKey="text"
                content={({ x, y, width, height, value }) => (
                  <text
                    x={(x ?? 0) + (width ?? 0) + 8}
                    y={(y ?? 0) + (height ?? 0) / 2}
                    dominantBaseline="middle"
                    fill={value === "達成確実！" ? "#00E676" : "rgba(255,255,255,0.85)"}
                    fontSize={12}
                  >
                    {value}
                  </text>
                )}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </>
  );
}

// ── 積立系の積み上げバー(元本+運用益) ──
function StackedChart({ rows, goal, goalOku, height = 400 }) {
  return (
    <div className="chartbox">
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={rows} margin={{ top: 20, right: 10, bottom: 10, left: 20 }}>
          <XAxis dataKey="経過年数" tick={AXIS_TICK} stroke="#1E232F" />
          <YAxis tickFormatter={(v) => v.toLocaleString("ja-JP")} tick={AXIS_TICK} stroke="#1E232F" width={100} />
          <Tooltip
            contentStyle={TOOLTIP_STYLE}
            formatter={(v, name) => [`${fmtInt(v)}円`, name]}
          />
          <Legend wrapperStyle={LEGEND_STYLE} />
          <Bar dataKey="積立元本(円)" name="積立元本" stackId="a" fill="#4A90D9" isAnimationActive={false} />
          <Bar dataKey="運用益(円)" name="運用益" stackId="a" fill="#00D2FF" isAnimationActive={false} radius={[3, 3, 0, 0]} />
          {goal > 0 && (
            <ReferenceLine
              y={goal}
              stroke="#FF1744"
              strokeWidth={2}
              strokeDasharray="6 4"
              label={{ value: `目標(${goalOku}億円)`, position: "insideTopRight", fill: "#FF1744", fontSize: 11 }}
            />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function Simulation() {
  const { snap, error, loading, reload } = useSnapshot();
  const [sub, setSub] = useState("goal");

  // サイドバー相当(app.py:185-190 の既定値)
  const [goalOku, setGoalOku] = useState(1.2);
  const [ratePct, setRatePct] = useState(6.0);
  const [yearlyAddMan, setYearlyAddMan] = useState(120);

  // 資産推移
  const [futureYears, setFutureYears] = useState(10);

  // 積立シム(tab_simulation.py:59-65 の既定値。初期資産はTA確定後に注入)
  const [accInit, setAccInit] = useState(null);
  const [accMonthly, setAccMonthly] = useState(50000);
  const [accRate, setAccRate] = useState(5.0);
  const [accYears, setAccYears] = useState(10);

  // 取り崩しシム(tab_simulation.py:100-129 の既定値)
  const [wdMode, setWdMode] = useState("fixed");
  const [wdInit, setWdInit] = useState(null);
  const [wdRate, setWdRate] = useState(4.0);
  const [wdMaxYears, setWdMaxYears] = useState(40);
  const [wdAmount, setWdAmount] = useState(null);
  const [wdRatePct, setWdRatePct] = useState(4.0);
  const [wdInflation, setWdInflation] = useState(2.0);

  const TA = snap ? snap.totals.total_asset_all ?? snap.totals.total_asset : 0;

  // TA確定後に初期値を一度だけ注入(Streamlitのvalue=int(TA)相当)
  useEffect(() => {
    if (snap && accInit === null) setAccInit(Math.trunc(TA));
    if (snap && wdInit === null) {
      const ia = TA > 0 ? Math.trunc(TA) : 30000000;
      setWdInit(ia);
      setWdAmount(ia > 0 ? Math.trunc(ia * 0.04) : 1200000);
    }
  }, [snap, TA, accInit, wdInit]);

  const future = useDebouncedSim(
    { initial: TA, annual_rate: ratePct / 100, years: futureYears, yearly_addition: yearlyAddMan * 10000 },
    "/api/simulate/future",
    !!snap && sub === "future" && TA > 0
  );
  const acc = useDebouncedSim(
    { initial: accInit ?? 0, annual_rate: accRate / 100, years: accYears, yearly_addition: accMonthly * 12 },
    "/api/simulate/future",
    !!snap && sub === "acc" && accInit !== null
  );
  const wd = useDebouncedSim(
    {
      initial: wdInit ?? 0,
      annual_rate: wdRate / 100,
      mode: wdMode,
      annual_withdrawal: wdMode === "rate" ? 0 : wdAmount ?? 0,
      withdrawal_rate: wdMode === "rate" ? wdRatePct / 100 : 0,
      inflation_rate: wdMode === "inflation" ? wdInflation / 100 : 0,
      max_years: wdMaxYears,
    },
    "/api/simulate/withdrawal",
    !!snap && sub === "wd" && wdInit !== null
  );

  const wdStats = useMemo(() => {
    if (!wd.rows?.length) return null;
    const depleted = wd.rows.find((r) => r["残高(円)"] <= 0);
    const last = wd.rows[wd.rows.length - 1];
    return {
      depletedYear: depleted ? depleted["年"] : null,
      finalYear: last["年"],
      finalBalance: last["残高(円)"],
      totalWithdrawn: last["累計取崩(円)"],
    };
  }, [wd.rows]);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const header = <TopBar loadedAt={snap.loadedAt} marketFetchedAt={snap.market_fetched_at} loading={loading} onReload={reload} />;
  if (!snap.rows.length || TA <= 0) {
    return (
      <main>
        {header}
        <p className="status">銘柄を追加するとシミュレーションが表示されます。</p>
      </main>
    );
  }

  const goal = goalOku * 1e8;
  const futureLast = future.rows?.length ? future.rows[future.rows.length - 1] : null;
  const accLast = acc.rows?.length ? acc.rows[acc.rows.length - 1] : null;
  const accContributed = accMonthly * 12 * accYears;
  const accRoi = accLast && accLast["積立元本(円)"] > 0 ? (accLast["運用益(円)"] / accLast["積立元本(円)"]) * 100 : 0;

  return (
    <main>
      {header}

      <div className="subtabs" style={{ marginTop: "0.4rem" }}>
        {SUBTABS.map((t) => (
          <button key={t.key} className={sub === t.key ? "active" : ""} onClick={() => setSub(t.key)}>
            {t.label}
          </button>
        ))}
      </div>

      {(sub === "goal" || sub === "future") && (
        <div className="paramrow">
          <NumInput label="🎯 目標金額(億円)" value={goalOku} onChange={setGoalOku} step={0.1} min={0.5} max={10} />
          <NumInput label="📈 想定年利(%)" value={ratePct} onChange={setRatePct} step={0.5} min={1} max={20} />
          {sub === "future" && (
            <NumInput label="💰 年間積立額(万円)" value={yearlyAddMan} onChange={setYearlyAddMan} step={10} min={0} />
          )}
        </div>
      )}

      {sub === "goal" && <GoalSection TA={TA} goalOku={goalOku} ratePct={ratePct} />}

      {sub === "future" && (
        <>
          <h3>🚀 未来の資産推移</h3>
          <div className="subtabs">
            {[1, 3, 5, 10, 20, 30].map((y) => (
              <button key={y} className={futureYears === y ? "active" : ""} onClick={() => setFutureYears(y)}>
                {y}年後
              </button>
            ))}
          </div>
          {futureLast && (
            <div className="grid3" style={{ marginBottom: "0.8rem" }}>
              <div className="scard"><h4>予測評価額</h4><p className="mv" style={{ color: "#00D2FF" }}>{fmtInt(futureLast["予測評価額(円)"])}<span>円</span></p></div>
              <div className="scard"><h4>積立元本</h4><p className="mv">{fmtInt(futureLast["積立元本(円)"])}<span>円</span></p></div>
              <div className="scard"><h4>運用益</h4><p className="mv" style={{ color: "#00E676" }}>{fmtInt(futureLast["運用益(円)"])}<span>円</span></p></div>
            </div>
          )}
          {future.rows && <StackedChart rows={future.rows} goal={goal} goalOku={goalOku} />}
          {future.busy && <p className="caption">計算中...</p>}
        </>
      )}

      {sub === "acc" && (
        <>
          <h3>💰 積立シミュレーター</h3>
          <p className="caption">初期資産・月額積立・年利・期間を自由に設定。初期資産0なら純粋な積立シム。</p>
          <div className="paramrow">
            <NumInput label="初期資産(円)" value={accInit ?? 0} onChange={setAccInit} step={100000} min={0} />
            <NumInput label="月額積立(円)" value={accMonthly} onChange={setAccMonthly} step={10000} min={0} />
            <NumInput label="年利(%)" value={accRate} onChange={setAccRate} step={0.1} min={-20} max={50} />
            <NumInput label="期間(年)" value={accYears} onChange={setAccYears} step={1} min={1} max={60} />
          </div>
          {accLast && (
            <div className="grid4" style={{ marginBottom: "0.8rem" }}>
              <div className="scard"><h4>{accYears}年後の評価額</h4><p className="mv" style={{ color: "#00D2FF" }}>{fmtInt(accLast["予測評価額(円)"])}<span>円</span></p></div>
              <div className="scard">
                <h4>元本合計</h4>
                <p className="mv">{fmtInt(accLast["積立元本(円)"])}<span>円</span></p>
                <p className="sv">初期 {fmtIntTrunc(accInit ?? 0)} + 積立 {fmtInt(accContributed)}</p>
              </div>
              <div className="scard"><h4>運用益</h4><p className="mv" style={{ color: "#00E676" }}>{fmtInt(accLast["運用益(円)"])}<span>円</span></p></div>
              <div className="scard"><h4>元本比リターン</h4><p className="mv" style={{ color: "#00E676" }}>+{accRoi.toFixed(1)}%</p></div>
            </div>
          )}
          {acc.rows && <StackedChart rows={acc.rows} goal={0} goalOku={0} height={380} />}
          {acc.busy && <p className="caption">計算中...</p>}
        </>
      )}

      {sub === "wd" && (
        <>
          <h3>🏔️ 取り崩しシミュレーター (4%ルール対応)</h3>
          <p className="caption">リタイア後の資産寿命を試算。3モード切替: 固定額 / 残高比率 / インフレ調整。</p>
          <div className="subtabs">
            {[
              ["fixed", "固定額 (インフレ調整なし)"],
              ["rate", "残高比率 (毎年残高の◯%)"],
              ["inflation", "インフレ調整 (初年度額を毎年増額)"],
            ].map(([k, label]) => (
              <button key={k} className={wdMode === k ? "active" : ""} onClick={() => setWdMode(k)}>
                {label}
              </button>
            ))}
          </div>
          <div className="paramrow">
            <NumInput label="初期資産(円)" value={wdInit ?? 0} onChange={setWdInit} step={1000000} min={0} />
            <NumInput label="年利(%)" value={wdRate} onChange={setWdRate} step={0.1} min={-20} max={50} />
            <NumInput label="試算年数(上限)" value={wdMaxYears} onChange={setWdMaxYears} step={5} min={5} max={60} />
            {wdMode === "fixed" && (
              <NumInput label="年間取り崩し額(円)" value={wdAmount ?? 0} onChange={setWdAmount} step={100000} min={0} />
            )}
            {wdMode === "rate" && (
              <NumInput label="取り崩し率(%)" value={wdRatePct} onChange={setWdRatePct} step={0.1} min={0.1} max={20} />
            )}
            {wdMode === "inflation" && (
              <>
                <NumInput label="初年度取り崩し額(円)" value={wdAmount ?? 0} onChange={setWdAmount} step={100000} min={0} />
                <NumInput label="インフレ率(%)" value={wdInflation} onChange={setWdInflation} step={0.1} min={0} max={20} />
              </>
            )}
          </div>

          {wdStats && (
            <div className="grid3" style={{ marginBottom: "0.8rem" }}>
              <div className="scard">
                <h4>資産寿命</h4>
                {wdStats.depletedYear !== null ? (
                  <>
                    <p className="mv" style={{ color: "#FF5252" }}>{wdStats.depletedYear}年</p>
                    <p className="sv">この年で枯渇</p>
                  </>
                ) : (
                  <>
                    <p className="mv" style={{ color: "#00E676" }}>{wdStats.finalYear}年超</p>
                    <p className="sv">上限{wdMaxYears}年内では枯渇せず</p>
                  </>
                )}
              </div>
              <div className="scard">
                <h4>{wdStats.finalYear}年後残高</h4>
                <p className="mv" style={{ color: wdStats.finalBalance < (wdInit ?? 0) * 0.5 ? "#FF5252" : "#00E676" }}>
                  {fmtInt(wdStats.finalBalance)}<span>円</span>
                </p>
              </div>
              <div className="scard">
                <h4>累計取り崩し</h4>
                <p className="mv">{fmtInt(wdStats.totalWithdrawn)}<span>円</span></p>
              </div>
            </div>
          )}

          {wd.rows && (
            <>
              <div className="chartbox">
                <ResponsiveContainer width="100%" height={280}>
                  <AreaChart data={wd.rows} margin={{ top: 20, right: 10, bottom: 0, left: 20 }} syncId="wd">
                    <XAxis dataKey="年" tick={AXIS_TICK} stroke="#1E232F" />
                    <YAxis tickFormatter={(v) => v.toLocaleString("ja-JP")} tick={AXIS_TICK} stroke="#1E232F" width={100} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${fmtInt(v)}円`, "残高"]} labelFormatter={(l) => `${l}年目`} />
                    <Area type="monotone" dataKey="残高(円)" name="残高" stroke="#00D2FF" strokeWidth={2.5} fill="rgba(0,210,255,0.15)" isAnimationActive={false} />
                    {wdStats?.depletedYear !== null && wdStats && (
                      <ReferenceLine x={wdStats.depletedYear} stroke="#FF5252" strokeWidth={2} strokeDasharray="6 4"
                        label={{ value: `枯渇 (${wdStats.depletedYear}年目)`, position: "top", fill: "#FF5252", fontSize: 11 }} />
                    )}
                  </AreaChart>
                </ResponsiveContainer>
                <ResponsiveContainer width="100%" height={140}>
                  <BarChart data={wd.rows} margin={{ top: 4, right: 10, bottom: 10, left: 20 }} syncId="wd">
                    <XAxis dataKey="年" tick={AXIS_TICK} stroke="#1E232F" label={{ value: "経過年数", position: "insideBottom", offset: -4, fill: "rgba(255,255,255,0.45)", fontSize: 11 }} />
                    <YAxis tickFormatter={(v) => v.toLocaleString("ja-JP")} tick={AXIS_TICK} stroke="#1E232F" width={100} />
                    <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${fmtInt(v)}円`, "年間取崩"]} labelFormatter={(l) => `${l}年目`} />
                    <Bar dataKey="取り崩し額(円)" name="年間取崩" fill="#FFA726" opacity={0.85} isAnimationActive={false} />
                  </BarChart>
                </ResponsiveContainer>
                <p className="caption" style={{ paddingLeft: "0.4rem" }}>上=残高 / 下=年間取崩（Streamlit版の2軸重ねを上下分割で表示）</p>
              </div>

              <details className="expander" style={{ marginTop: "0.8rem" }}>
                <summary>年次データ</summary>
                <div className="tablewrap tight">
                  <table>
                    <thead>
                      <tr><th>年</th><th>残高(円)</th><th>取り崩し額(円)</th><th>累計取崩(円)</th></tr>
                    </thead>
                    <tbody>
                      {wd.rows.map((r) => (
                        <tr key={r["年"]}>
                          <td>{r["年"]}</td>
                          <td>{fmtInt(r["残高(円)"])}</td>
                          <td>{fmtInt(r["取り崩し額(円)"])}</td>
                          <td>{fmtInt(r["累計取崩(円)"])}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            </>
          )}
          {wd.busy && <p className="caption">計算中...</p>}
        </>
      )}
    </main>
  );
}
