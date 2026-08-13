"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  Treemap,
  XAxis,
  YAxis,
} from "recharts";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { fmtInt, fmtIntTrunc, fmtPct1 } from "../../lib/format";

// カテゴリカル8色(dataviz検証済み・ダーク面#0A0E13で全チェック合格・固定順)
const CAT = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const OTHER_COLOR = "#5a5f6b";
const SURFACE = "#0a0a0f";
const TOOLTIP_STYLE = {
  background: "#12121a",
  border: "1px solid #23232f",
  borderRadius: 6,
  fontSize: 12,
  color: "rgba(255,255,255,0.88)",
};

// 発散スケール: 損失#FF5252 ←→ 無彩色#9E9E9E ←→ 利益#00E676 (t∈[-1,1])
function divergingColor(t) {
  const lerp = (a, b, u) => Math.round(a + (b - a) * u);
  const mix = (c1, c2, u) => `rgb(${lerp(c1[0], c2[0], u)},${lerp(c1[1], c2[1], u)},${lerp(c1[2], c2[2], u)})`;
  const RED = [255, 82, 82];
  const GRAY = [158, 158, 158];
  const GREEN = [0, 230, 118];
  return t < 0 ? mix(GRAY, RED, Math.min(-t, 1)) : mix(GRAY, GREEN, Math.min(t, 1));
}

// 評価額>0 の行を key 列でグループ集計し降順に
function groupSum(rows, keyFn) {
  const m = new Map();
  rows.forEach((r) => {
    const v = r["評価額(円)"] || 0;
    if (v <= 0) return;
    const k = keyFn(r);
    m.set(k, (m.get(k) || 0) + v);
  });
  return [...m.entries()]
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value);
}

// 円グラフは上位8+「その他」に畳む(色は固定順・テーブル側に全行)
function foldForPie(items) {
  if (items.length <= CAT.length) return items.map((d, i) => ({ ...d, fill: CAT[i] }));
  const head = items.slice(0, CAT.length).map((d, i) => ({ ...d, fill: CAT[i] }));
  const rest = items.slice(CAT.length).reduce((s, d) => s + d.value, 0);
  return [...head, { name: "その他", value: rest, fill: OTHER_COLOR }];
}

function NisaCard({ label, val, lifetime, annual, color }) {
  const pct = Math.min((val / lifetime) * 100, 100);
  const rem = Math.max(lifetime - val, 0);
  const remY = Math.max(annual - val, 0);
  return (
    <div className="scard" style={{ borderLeft: `3px solid ${color}` }}>
      <h4>{label}</h4>
      <p className="mv" style={{ color }}>
        {fmtInt(val)}
        <span>円</span>
      </p>
      <p className="sv">
        生涯上限 {fmtInt(lifetime / 1e4)}万 → 残 {fmtInt(rem)}円 ({(100 - pct).toFixed(1)}%)
      </p>
      <div className="track">
        <div className="fill" style={{ width: `${pct.toFixed(1)}%`, background: color }} />
      </div>
      <p className="sv" style={{ marginTop: 4 }}>
        年間上限 {fmtInt(annual / 1e4)}万 → 今年の残枠概算 {fmtInt(remY)}円
      </p>
    </div>
  );
}

function DonutWithTable({ items, total, nameLabel = "銘柄" }) {
  const pieData = foldForPie(items);
  return (
    <div className="grid2">
      <div className="chartbox">
        <ResponsiveContainer width="100%" height={320}>
          <PieChart>
            <Pie
              data={pieData}
              dataKey="value"
              nameKey="name"
              innerRadius="52%"
              outerRadius="85%"
              stroke={SURFACE}
              strokeWidth={2}
              isAnimationActive={false}
            >
              {pieData.map((d, i) => (
                <Cell key={i} fill={d.fill} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(v, name) => [`${fmtInt(v)}円 (${((v / total) * 100).toFixed(1)}%)`, name]}
            />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <div className="tablewrap tight">
        <table>
          <thead>
            <tr>
              <th className="l">{nameLabel}</th>
              <th>評価額(円)</th>
              <th>割合</th>
            </tr>
          </thead>
          <tbody>
            {items.map((d, i) => (
              <tr key={d.name}>
                <td className="l">
                  <span
                    className="chip"
                    style={{ background: i < CAT.length ? CAT[i] : OTHER_COLOR }}
                  />
                  {d.name}
                </td>
                <td>{fmtIntTrunc(d.value)}円</td>
                <td>{fmtPct1((d.value / total) * 100)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ツリーマップのセル(大きさ=評価額、色=前日比)
function HeatCell(props) {
  const { x, y, width, height, name } = props;
  const fill = props.fill ?? props.payload?.fill;
  const chgLabel = props.chgLabel ?? props.payload?.chgLabel;
  if (width <= 0 || height <= 0) return null;
  const showText = width > 64 && height > 34;
  return (
    <g>
      <rect x={x} y={y} width={width} height={height} fill={fill} stroke={SURFACE} strokeWidth={2} />
      {showText && (
        <>
          <text x={x + 6} y={y + 16} fill="#0b0e13" fontSize={11} fontWeight={700}>
            {String(name).slice(0, Math.floor(width / 9))}
          </text>
          <text x={x + 6} y={y + 30} fill="#0b0e13" fontSize={11}>
            {chgLabel}
          </text>
        </>
      )}
    </g>
  );
}

export default function Analysis() {
  const { snap, error, loading, reload } = useSnapshot();
  const [targets, setTargets] = useState(null); // {sector: pct}
  const [showTargets, setShowTargets] = useState(false);

  const derived = useMemo(() => {
    if (!snap) return null;
    const rows = snap.rows;
    const TA = snap.totals.total_asset;
    if (!rows.length || TA <= 0) return { empty: true };

    const nisaG = rows
      .filter((r) => String(r["口座区分"] ?? "").includes("成長"))
      .reduce((s, r) => s + (r["評価額(円)"] || 0), 0);
    const nisaT = rows
      .filter((r) => String(r["口座区分"] ?? "").includes("積立"))
      .reduce((s, r) => s + (r["評価額(円)"] || 0), 0);

    const byName = groupSum(rows, (r) => `${r["銘柄コード"]} ${r["銘柄名"]}`);
    const bySector = groupSum(rows, (r) => String(r["セクター"] ?? "未分類"));

    // ヒートマップ対象: 日本株/米国株のみ(手動入力資産は除外)
    const heatRows = rows.filter(
      (r) => ["日本株", "米国株"].includes(r["市場"]) && (r["評価額(円)"] || 0) > 0
    );
    const maxAbs = Math.max(...heatRows.map((r) => Math.abs(r["前日比"] ?? 0)), 0.01);
    const heat = heatRows.map((r) => {
      const chg = typeof r["前日比"] === "number" ? r["前日比"] : 0;
      return {
        name: String(r["銘柄名"]),
        size: r["評価額(円)"],
        fill: divergingColor(chg / maxAbs),
        chgLabel: `${chg > 0 ? "+" : ""}${chg.toFixed(2)}%`,
      };
    });

    const sectors = bySector.map((d) => d.name).sort((a, b) => a.localeCompare(b, "ja"));
    const sectorPct = Object.fromEntries(bySector.map((d) => [d.name, (d.value / TA) * 100]));
    const sectorAmt = Object.fromEntries(bySector.map((d) => [d.name, d.value]));
    return { TA, nisaG, nisaT, byName, bySector, heat, sectors, sectorPct, sectorAmt };
  }, [snap]);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap || !derived) return null;

  const header = <TopBar loadedAt={snap.loadedAt} loading={loading} onReload={reload} />;
  if (derived.empty) {
    return (
      <main>
        {header}
        <p className="status">銘柄を追加すると分析が表示されます。</p>
      </main>
    );
  }

  const { TA, nisaG, nisaT, byName, bySector, heat, sectors, sectorPct, sectorAmt } = derived;
  const L = snap.nisa_limits;

  // リバランス: 目標未設定セクターは現在割合(0.1%丸め)を既定値に
  const tp = targets ?? Object.fromEntries(sectors.map((s) => [s, Math.round((sectorPct[s] ?? 0) * 10) / 10]));
  const targetTotal = sectors.reduce((s, k) => s + (tp[k] || 0), 0);
  const rebalance = sectors
    .map((s) => {
      const cp = sectorPct[s] ?? 0;
      const ca = sectorAmt[s] ?? 0;
      const tgt = tp[s] || 0;
      return { sector: s, cur: cp, target: tgt, dev: cp - tgt, curAmt: ca, adjust: ca - TA * (tgt / 100) };
    })
    .sort((a, b) => Math.abs(b.dev) - Math.abs(a.dev));
  const actions = rebalance.filter((r) => Math.abs(r.dev) > 1.0);
  const devMax = Math.max(...rebalance.map((r) => Math.abs(r.dev)), 1);

  const nisaTotal = nisaG + nisaT;
  const nisaTotalPct = Math.min((nisaTotal / L.total_lifetime) * 100, 100);

  return (
    <main>
      {header}

      <h3>🌿 NISA 枠残高</h3>
      <div className="grid3">
        <NisaCard label="成長投資枠" val={nisaG} lifetime={L.growth_lifetime} annual={L.growth_annual} color="#00E676" />
        <NisaCard label="積立投資枠" val={nisaT} lifetime={L.tsumitate_lifetime} annual={L.tsumitate_annual} color="#69F0AE" />
        <div className="scard" style={{ borderLeft: "3px solid #00D2FF" }}>
          <h4>NISA 合計</h4>
          <p className="mv" style={{ color: "#00D2FF" }}>
            {fmtInt(nisaTotal)}
            <span>円</span>
          </p>
          <p className="sv">
            生涯上限 1,800万 → 残 {fmtInt(Math.max(L.total_lifetime - nisaTotal, 0))}円 ({(100 - nisaTotalPct).toFixed(1)}%)
          </p>
          <div className="track">
            <div
              className="fill"
              style={{ width: `${nisaTotalPct.toFixed(1)}%`, background: "linear-gradient(90deg,#00D2FF,#00E676)" }}
            />
          </div>
          <p className="sv" style={{ marginTop: 4 }}>※評価額ベースの概算。実際の枠は投資元本で管理されます。</p>
        </div>
      </div>

      <h3>📊 銘柄構成</h3>
      <DonutWithTable items={byName} total={TA} />

      <h3>🏢 セクター別割合</h3>
      <DonutWithTable items={bySector} total={TA} nameLabel="セクター" />

      <h3>🗺️ ヒートマップ</h3>
      <p className="caption">四角の大きさ＝評価額、色＝前日比。手動入力資産は除外。</p>
      {heat.length > 0 && (
        <div className="chartbox">
          <ResponsiveContainer width="100%" height={500}>
            <Treemap data={heat} dataKey="size" nameKey="name" content={<HeatCell />} isAnimationActive={false}>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v, _n, entry) => [
                  `${fmtInt(v)}円 / 前日比 ${entry?.payload?.chgLabel ?? "-"}`,
                  entry?.payload?.name,
                ]}
              />
            </Treemap>
          </ResponsiveContainer>
        </div>
      )}

      <h3>⚖️ リバランス提案</h3>
      <details className="expander" open={showTargets} onToggle={(e) => setShowTargets(e.currentTarget.open)}>
        <summary>🎯 目標配分を設定（%）</summary>
        <div className="targetgrid">
          {sectors.map((s) => (
            <label key={s}>
              {s}
              <input
                type="number"
                min="0"
                max="100"
                step="1"
                value={tp[s]}
                onChange={(e) => setTargets({ ...tp, [s]: Number(e.target.value) })}
              />
            </label>
          ))}
        </div>
        {Math.abs(targetTotal - 100) > 0.5 ? (
          <div className="alert warn">⚠ 目標合計: {targetTotal.toFixed(1)}%</div>
        ) : (
          <div className="alert up">✓ 目標合計: {targetTotal.toFixed(1)}%</div>
        )}
      </details>

      <div className="chartbox">
        <ResponsiveContainer width="100%" height={Math.max(sectors.length * 40, 200)}>
          <BarChart data={rebalance} layout="vertical" margin={{ top: 10, right: 40, bottom: 10, left: 10 }}>
            <XAxis
              type="number"
              domain={[-Math.ceil(devMax), Math.ceil(devMax)]}
              tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 11 }}
              stroke="#1E232F"
              label={{ value: "乖離（%）", position: "insideBottom", offset: -4, fill: "rgba(255,255,255,0.45)", fontSize: 11 }}
            />
            <YAxis
              type="category"
              dataKey="sector"
              width={120}
              tick={{ fill: "rgba(255,255,255,0.88)", fontSize: 12 }}
              stroke="#1E232F"
            />
            <ReferenceLine x={0} stroke="#4A5060" />
            <Tooltip
              cursor={{ fill: "rgba(0,210,255,0.05)" }}
              contentStyle={TOOLTIP_STYLE}
              formatter={(v) => [`${v > 0 ? "+" : ""}${v.toFixed(1)}%`, "乖離"]}
            />
            <Bar dataKey="dev" isAnimationActive={false} barSize={18} radius={[2, 2, 2, 2]}>
              {rebalance.map((r) => (
                <Cell
                  key={r.sector}
                  fill={r.dev > 1 ? "#FF5252" : r.dev < -1 ? "#00E676" : "#9E9E9E"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="caption">🔴 比重オーバー / 🟢 比重不足 / 灰 適正範囲(±1%)</p>

      {actions.length > 0 ? (
        <>
          <h4 className="subhead">📋 調整アクション</h4>
          {actions.map((r) =>
            r.adjust > 0 ? (
              <div key={r.sector} className="alert down">
                📉 <b>{r.sector}</b> 現在{r.cur.toFixed(1)}%→目標{r.target.toFixed(1)}%{" "}
                <span style={{ color: "#FF5252", fontWeight: 700 }}>約¥{fmtInt(Math.abs(r.adjust))}売却</span>
              </div>
            ) : (
              <div key={r.sector} className="alert up">
                📈 <b>{r.sector}</b> 現在{r.cur.toFixed(1)}%→目標{r.target.toFixed(1)}%{" "}
                <span style={{ color: "#69F0AE", fontWeight: 700 }}>約¥{fmtInt(Math.abs(r.adjust))}買い増し</span>
              </div>
            )
          )}
        </>
      ) : (
        <div className="alert up">✓ 全セクター±1%以内。リバランス不要。</div>
      )}
    </main>
  );
}
