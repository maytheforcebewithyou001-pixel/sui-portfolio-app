"use client";

import { useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  Cell,
  LabelList,
  Pie,
  PieChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { fmtInt, fmtIntTrunc, fmtG4, signedYenInt } from "../../lib/format";

// tab_currency.py:9 と同一の通貨識別色
const CCY_COLORS = { JPY: "#00D2FF", USD: "#FFD54F", "現金(JPY)": "#4DB6AC", その他: "#B0B8C0" };
const SURFACE = "#0a0a0f";
const TOOLTIP_STYLE = {
  background: "#12121a",
  border: "1px solid #23232f",
  borderRadius: 6,
  fontSize: 12,
  color: "rgba(255,255,255,0.88)",
};

const ccyColor = (c) => CCY_COLORS[c] ?? CCY_COLORS.その他;

// 通貨列の正規化(tab_currency.py:21-23): 欠損/空/-/nan → JPY
function normCcy(r) {
  const c = String(r["通貨"] ?? "").trim();
  return c === "" || c === "-" || c === "nan" ? "JPY" : c;
}

function HoldingsTable({ rows, columns }) {
  const cols = columns.filter((c) => rows.some((r) => r[c.key] !== undefined));
  return (
    <div className="tablewrap tight">
      <table>
        <thead>
          <tr>
            {cols.map((c) => (
              <th key={c.key} className={c.left ? "l" : ""}>{c.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              {cols.map((c) => (
                <td key={c.key} className={c.left ? "l" : c.cls ? c.cls(r[c.key]) : ""}>
                  {c.fmt ? c.fmt(r[c.key]) : r[c.key] ?? "-"}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Currency() {
  const { snap, error, loading, reload } = useSnapshot();
  const [planMode, setPlanMode] = useState("tsumitate"); // tsumitate | sell
  const [monthlyMan, setMonthlyMan] = useState(7); // 万円/月(tab_currency.py:97 既定7.0)
  const [openCcy, setOpenCcy] = useState({});

  const d = useMemo(() => {
    if (!snap) return null;
    const rows = snap.rows;
    const secTotal = snap.totals.total_asset;
    if (!rows.length || secTotal <= 0) return { empty: true };
    const cash = snap.totals.cash_jpy || 0;
    const TA = secTotal + cash; // 実質配分は現金込み(tab_currency.py:14)

    const byCcy = new Map();
    rows.forEach((r) => {
      const c = normCcy(r);
      const cur = byCcy.get(c) || { ccy: c, value: 0, pnl: 0, dividend: 0, count: 0, rows: [] };
      cur.value += r["評価額(円)"] || 0;
      cur.pnl += r["税引後損益(円)"] || 0;
      cur.dividend += r["予想配当(円)"] || 0;
      cur.count += 1;
      cur.rows.push(r);
      byCcy.set(c, cur);
    });
    const ccyAgg = [...byCcy.values()].sort((a, b) => b.value - a.value);

    const jpyActual = (byCcy.get("JPY")?.value || 0) + cash;
    const usdActual = byCcy.get("USD")?.value || 0;
    return { TA, cash, ccyAgg, byCcy, jpyActual, usdActual };
  }, [snap]);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap || !d) return null;

  const header = <TopBar loadedAt={snap.loadedAt} loading={loading} onReload={reload} />;
  if (d.empty) {
    return (
      <main>
        {header}
        <p className="status">銘柄を追加すると通貨配分が表示されます。</p>
      </main>
    );
  }

  const { TA, cash, ccyAgg, byCcy, jpyActual, usdActual } = d;
  const rate = snap.jpy_usd_rate;
  const tJpy = snap.targets.jpy_pct;
  const tUsd = snap.targets.usd_pct;
  const jpyDiff = jpyActual - TA * (tJpy / 100);
  const usdDiff = usdActual - TA * (tUsd / 100);
  const usdDiffUsd = rate > 0 ? usdDiff / rate : 0;

  // リバランス実行プラン(tab_currency.py:79-126)
  const shift = jpyDiff;
  const thresh = TA * 0.01;
  const withinTarget = Math.abs(shift) <= thresh;
  const frm = shift > 0 ? "JPY" : "USD";
  const to = shift > 0 ? "USD" : "JPY";
  const amt = Math.abs(shift);
  const mYen = monthlyMan * 10000;
  const months = mYen > 0 ? amt / mYen : 0;
  const eta = new Date();
  eta.setMonth(eta.getMonth() + Math.round(months));
  const sellCand = (byCcy.get(frm)?.rows || []).slice().sort((a, b) => (b["評価額(円)"] || 0) - (a["評価額(円)"] || 0)).slice(0, 8);
  const buyCand = (byCcy.get(to)?.rows || []).slice().sort((a, b) => (b["評価額(円)"] || 0) - (a["評価額(円)"] || 0)).slice(0, 8);

  // サマリー表示行(現金行を挿入して評価額降順)
  const dispAgg = cash > 0
    ? [...ccyAgg, { ccy: "現金(JPY)", value: cash, pnl: 0, dividend: 0, count: 0 }].sort((a, b) => b.value - a.value)
    : ccyAgg;

  // 為替感応度(tab_currency.py:223-234)
  const usdTotal = usdActual;
  const fxRows = [-10, -5, -3, -1, 0, 1, 3, 5, 10].map((pct) => ({
    label: `${pct >= 0 ? "+" : ""}${pct}%`,
    newRate: rate * (1 + pct / 100),
    impact: usdTotal * (pct / 100),
  }));

  return (
    <main>
      {header}

      <h3>📐 目標バランスとの差分</h3>
      <p className="caption">
        目標%はSettingsシート「🎯 目標通貨配分」の値よ
        {cash > 0 && `。現金 ${fmtInt(cash)}円（MRF等）を実質JPYに合算済み`}
      </p>
      <div className="grid2even">
        <div className="scard" style={{ borderLeft: "3px solid #00D2FF" }}>
          <h4>JPY {jpyDiff > 0 ? "過剰" : jpyDiff < 0 ? "不足" : "一致"} (目標 {tJpy.toFixed(0)}%)</h4>
          <p className="mv" style={{ fontSize: "1.3rem", color: jpyDiff > 0 ? "#FFD54F" : jpyDiff < 0 ? "#FF5252" : "#9E9E9E" }}>
            {jpyDiff >= 0 ? "+" : "-"}{fmtInt(Math.abs(jpyDiff))}<span>円</span>
          </p>
          <p className="sv">実 {((jpyActual / TA) * 100).toFixed(1)}% / 目標 {tJpy.toFixed(0)}%</p>
        </div>
        <div className="scard" style={{ borderLeft: "3px solid #FFD54F" }}>
          <h4>USD {usdDiff > 0 ? "過剰" : usdDiff < 0 ? "不足" : "一致"} (目標 {tUsd.toFixed(0)}%)</h4>
          <p className="mv" style={{ fontSize: "1.3rem", color: usdDiff > 0 ? "#FFD54F" : usdDiff < 0 ? "#FF5252" : "#9E9E9E" }}>
            {usdDiff >= 0 ? "+" : "-"}{fmtInt(Math.abs(usdDiff))}<span>円</span>{" "}
            / {usdDiffUsd >= 0 ? "+" : "-"}{Math.abs(usdDiffUsd).toLocaleString("ja-JP", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}<span>$</span>
          </p>
          <p className="sv">実 {((usdActual / TA) * 100).toFixed(1)}% / 目標 {tUsd.toFixed(0)}%</p>
        </div>
      </div>

      <h3>🔄 リバランス実行プラン</h3>
      {withinTarget ? (
        <div className="alert up">
          ✅ 目標配分の達成圏内（誤差 {fmtInt(amt)}円・{((amt / TA) * 100).toFixed(1)}%）。今は行動不要よ。
        </div>
      ) : (
        <>
          <div className="alert warn">
            {shift > 0 ? (
              <>JPY建てが目標より <b>{fmtInt(amt)}円 過剰</b>（実 {((jpyActual / TA) * 100).toFixed(1)}% → 目標 {tJpy.toFixed(0)}%）。<b>{fmtInt(amt)}円分を USD建てへ</b>移すと目標に届くわ。</>
            ) : (
              <>JPY建てが目標より <b>{fmtInt(amt)}円 不足</b>。<b>USD建てから {fmtInt(amt)}円分を JPY建てへ</b>移す必要があるわ。</>
            )}
          </div>
          <div className="subtabs">
            <button className={planMode === "tsumitate" ? "active" : ""} onClick={() => setPlanMode("tsumitate")}>
              📈 積立で調整（売らない）
            </button>
            <button className={planMode === "sell" ? "active" : ""} onClick={() => setPlanMode("sell")}>
              ⚡ 即時売却で調整
            </button>
          </div>
          {planMode === "tsumitate" ? (
            <div className="scard">
              <p className="sv">配当ベースの売却ルールを守り、新規資金の積立だけで目標へ寄せるアプローチ</p>
              <label className="inlineinput">
                毎月の {to} 新規投資額（万円/月）
                <input
                  type="number" min="0" max="1000" step="1" value={monthlyMan}
                  onChange={(e) => setMonthlyMan(Number(e.target.value))}
                />
              </label>
              {mYen > 0 ? (
                <>
                  <p>・必要移動額: <b>{fmtInt(amt)}円</b></p>
                  <p>
                    ・月 <b>{fmtInt(monthlyMan)}万円</b> の {to} 積立なら <b>約 {months.toFixed(1)}ヶ月</b>
                    （{eta.getFullYear()}年{String(eta.getMonth() + 1).padStart(2, "0")}月頃）で目標到達
                  </p>
                  <p className="sv">※ 既存資産の評価額・為替変動は考慮しない、新規資金フローのみの単純試算よ。</p>
                </>
              ) : (
                <div className="alert warn">月次投資額を入力してちょうだい。</div>
              )}
            </div>
          ) : (
            <div className="scard">
              <p className="sv">{frm}建て資産を売却して {to}建て資産へ即時に組み替えるアプローチ</p>
              <p>・必要組み替え額: <b>{fmtInt(amt)}円</b></p>
              <div className="alert warn">
                ⚠ 特定口座での売却は譲渡益に20.315%課税。NISA枠の活用や、含み益の小さい銘柄からの売却を優先して。配当目的の保有は配当方針が変わらない限り売却対象外にすべきよ。
              </div>
              {sellCand.length > 0 && (
                <>
                  <h4 className="subhead">{frm}建て 保有上位（売却候補の検討材料）</h4>
                  <HoldingsTable
                    rows={sellCand}
                    columns={[
                      { key: "銘柄コード", label: "銘柄コード", left: true },
                      { key: "銘柄名", label: "銘柄名", left: true },
                      { key: "評価額(円)", label: "評価額(円)", fmt: fmtInt },
                      { key: "税引後損益(円)", label: "税引後損益(円)", fmt: signedYenInt, cls: (v) => (v >= 0 ? "pos" : "neg") },
                    ]}
                  />
                </>
              )}
              {buyCand.length > 0 && (
                <>
                  <h4 className="subhead">{to}建て 保有銘柄（買い増し候補）</h4>
                  <HoldingsTable
                    rows={buyCand}
                    columns={[
                      { key: "銘柄コード", label: "銘柄コード", left: true },
                      { key: "銘柄名", label: "銘柄名", left: true },
                      { key: "評価額(円)", label: "評価額(円)", fmt: fmtInt },
                    ]}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}
      <p className="caption">※ 外国株投信（オルカン等）を実質USD扱いにしたい場合は、各銘柄の「通貨」設定をUSDにしてちょうだい。本プランは設定値に従うわ。</p>

      <h3>💱 通貨配分サマリー</h3>
      <div className="cardsrow">
        {dispAgg.map((r) => (
          <div key={r.ccy} className="scard" style={{ borderLeft: `3px solid ${ccyColor(r.ccy)}`, flex: 1 }}>
            <h4>{r.ccy}{r.ccy === "現金(JPY)" ? "" : " 建て資産"}</h4>
            <p className="mv" style={{ fontSize: "1.3rem", color: ccyColor(r.ccy) }}>
              {fmtInt(r.value)}<span>円</span>
            </p>
            <p className="sv" style={{ fontSize: "1rem" }}>
              {((r.value / TA) * 100).toFixed(1)}% · {r.ccy === "現金(JPY)" ? "MRF・預り金" : `${r.count}銘柄`}
            </p>
            <p className={`sv ${r.pnl >= 0 ? "pos" : "neg"}`}>
              損益 {signedYenInt(r.pnl)} · 配当 {fmtIntTrunc(r.dividend)}円
            </p>
          </div>
        ))}
      </div>

      <div className="grid2">
        <div className="chartbox">
          <h4 className="subhead">🥧 通貨配分チャート</h4>
          <ResponsiveContainer width="100%" height={350}>
            <PieChart>
              <Pie
                data={dispAgg.map((r) => ({ name: r.ccy, value: r.value }))}
                dataKey="value" nameKey="name"
                innerRadius="50%" outerRadius="85%"
                stroke={SURFACE} strokeWidth={2} isAnimationActive={false}
              >
                {dispAgg.map((r) => (
                  <Cell key={r.ccy} fill={ccyColor(r.ccy)} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v, name) => [`${fmtInt(v)}円 (${((v / TA) * 100).toFixed(1)}%)`, name]}
              />
              <text x="50%" y="50%" textAnchor="middle" dominantBaseline="middle" fill="#E0E0E0" fontSize={16}>
                ¥{fmtInt(TA)}
              </text>
            </PieChart>
          </ResponsiveContainer>
        </div>
        <div>
          <h4 className="subhead">📋 通貨別内訳</h4>
          <HoldingsTable
            rows={dispAgg.map((r) => ({
              通貨: r.ccy, 評価額: r.value, 割合: (r.value / TA) * 100, 損益: r.pnl, 配当: r.dividend, 銘柄数: r.count,
            }))}
            columns={[
              { key: "通貨", label: "通貨", left: true },
              { key: "評価額", label: "評価額", fmt: (v) => `${fmtIntTrunc(v)}円` },
              { key: "割合", label: "割合", fmt: (v) => `${v.toFixed(1)}%` },
              { key: "損益", label: "損益", fmt: signedYenInt, cls: (v) => (v >= 0 ? "pos" : "neg") },
              { key: "配当", label: "配当", fmt: (v) => `${fmtIntTrunc(v)}円` },
              { key: "銘柄数", label: "銘柄数" },
            ]}
          />
          <div className="scard" style={{ marginTop: "0.8rem" }}>
            <h4>現在の為替レート</h4>
            <p className="mv" style={{ fontSize: "1.2rem" }}>$1 = ¥{rate.toFixed(2)}</p>
          </div>
        </div>
      </div>

      <h3>📋 通貨別 保有銘柄</h3>
      {ccyAgg.map((r) => (
        <details
          key={r.ccy} className="expander"
          open={!!openCcy[r.ccy]}
          onToggle={(e) => {
            // currentTarget は更新関数の実行時には null になるため、ここで値を確定させる
            const isOpen = e.currentTarget.open;
            setOpenCcy((s) => ({ ...s, [r.ccy]: isOpen }));
          }}
        >
          <summary>
            💰 {r.ccy} — {fmtInt(r.value)}円 ({((r.value / TA) * 100).toFixed(1)}%) · {r.count}銘柄
          </summary>
          <HoldingsTable
            rows={r.rows.slice().sort((a, b) => (b["評価額(円)"] || 0) - (a["評価額(円)"] || 0))}
            columns={[
              { key: "銘柄コード", label: "銘柄コード", left: true },
              { key: "銘柄名", label: "銘柄名", left: true },
              { key: "市場", label: "市場", left: true },
              { key: "口座", label: "口座", left: true },
              { key: "保有株数", label: "保有株数", fmt: fmtG4 },
              { key: "評価額(円)", label: "評価額(円)", fmt: fmtInt },
              { key: "税引後損益(円)", label: "税引後損益(円)", fmt: signedYenInt, cls: (v) => (v >= 0 ? "pos" : "neg") },
              { key: "実質利回り(%)", label: "実質利回り(%)", fmt: (v) => (typeof v === "number" ? `${v.toFixed(2)}%` : "-") },
            ]}
          />
        </details>
      ))}

      {usdTotal > 0 && (
        <>
          <h3>📊 為替感応度分析</h3>
          <p className="caption">USD/JPY が変動した場合のポートフォリオ評価額への影響（USD建て資産のみ対象）</p>
          <div className="chartbox">
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={fxRows} margin={{ top: 30, right: 10, bottom: 10, left: 20 }}>
                <XAxis dataKey="label" tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 11 }} stroke="#1E232F"
                  label={{ value: "USD/JPY 変動幅", position: "insideBottom", offset: -4, fill: "rgba(255,255,255,0.45)", fontSize: 11 }} />
                <YAxis tickFormatter={(v) => v.toLocaleString("ja-JP")} tick={{ fill: "rgba(255,255,255,0.45)", fontSize: 11 }} stroke="#1E232F" width={90} />
                <ReferenceLine y={0} stroke="#4A5060" />
                <Tooltip
                  cursor={{ fill: "rgba(0,210,255,0.05)" }}
                  contentStyle={TOOLTIP_STYLE}
                  formatter={(v) => [signedYenInt(v), "評価額への影響"]}
                />
                <Bar dataKey="impact" isAnimationActive={false} radius={[2, 2, 0, 0]}>
                  {fxRows.map((r) => (
                    <Cell key={r.label} fill={r.impact < 0 ? "#FF5252" : r.impact > 0 ? "#00E676" : "#9E9E9E"} />
                  ))}
                  <LabelList
                    dataKey="impact"
                    content={({ x, y, width, height, value }) => {
                      const cx = x + width / 2;
                      const cy = value >= 0 ? y - 6 : y + height + 14;
                      return (
                        <text x={cx} y={cy} textAnchor="middle" fill="rgba(255,255,255,0.7)" fontSize={10}>
                          {signedYenInt(value).replace("円", "")}
                        </text>
                      );
                    }}
                  />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
          <HoldingsTable
            rows={fxRows.map((r) => ({
              変動幅: r.label, 想定レート: `¥${r.newRate.toFixed(1)}`, USD資産変動: r.impact,
              評価額: TA + r.impact, 全体変動率: (r.impact / TA) * 100,
            }))}
            columns={[
              { key: "変動幅", label: "変動幅", left: true },
              { key: "想定レート", label: "想定レート" },
              { key: "USD資産変動", label: "USD資産変動", fmt: signedYenInt, cls: (v) => (v >= 0 ? "pos" : "neg") },
              { key: "評価額", label: "評価額", fmt: (v) => `${fmtInt(v)}円` },
              { key: "全体変動率", label: "全体変動率", fmt: (v) => `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` },
            ]}
          />
        </>
      )}
    </main>
  );
}
