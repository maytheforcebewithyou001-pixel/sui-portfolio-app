"use client";

import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiGet } from "../../lib/api";

const TOOLTIP_STYLE = {
  background: "#12121a",
  border: "1px solid #23232f",
  borderRadius: 6,
  fontSize: 12,
  color: "rgba(255,255,255,0.88)",
};
const AXIS_TICK = { fill: "#9E9E9E", fontSize: 10 };
const PERIODS = [
  ["全期間", null],
  ["直近1ヶ月", 30],
  ["直近3ヶ月", 90],
  ["直近6ヶ月", 180],
  ["直近1年", 365],
];
const BENCHMARKS = [
  { key: "ACWI", label: "オルカン(ACWI)", color: "#FFD54F" },
  { key: "^GSPC", label: "S&P 500", color: "#00D2FF" },
];

const fmt0 = (n) => Math.round(n).toLocaleString("ja-JP");
const pnlColor = (v) => (v >= 0 ? "#00E676" : "#FF5252");
const pnlSign = (v) => (v >= 0 ? "+" : "");

export default function History() {
  const { snap, error, loading, reload } = useSnapshot();
  const [data, setData] = useState(null);
  const [histError, setHistError] = useState("");
  const [histLoading, setHistLoading] = useState(true);
  const [days, setDays] = useState(null);
  const [showCost, setShowCost] = useState(true);
  const [bsel, setBsel] = useState(["ACWI"]);

  useEffect(() => {
    setHistLoading(true);
    apiGet("/api/history")
      .then((d) => { setData(d); setHistError(""); })
      .catch((e) => setHistError(e.message))
      .finally(() => setHistLoading(false));
  }, []);

  const rows = useMemo(() => {
    if (!data) return [];
    if (!days) return data.history;
    const cutoff = Date.now() - days * 86400000;
    return data.history.filter((r) => new Date(r.date).getTime() >= cutoff);
  }, [data, days]);

  // 期間変化(Streamlit版と同一: 期間の最初と最後の評価額差)
  const change = useMemo(() => {
    if (rows.length < 2) return null;
    const first = rows[0].total;
    const last = rows[rows.length - 1].total;
    const chg = last - first;
    return { chg, pct: first > 0 ? (chg / first) * 100 : 0 };
  }, [rows]);

  // ベンチマーク比較: 期間開始=100に指数化し、日付キーでマージ(あなた=疎、指数=日次)
  const bench = useMemo(() => {
    if (!data || rows.length < 2 || bsel.length === 0) return null;
    const start = rows[0].date;
    const end = rows[rows.length - 1].date;
    const pf0 = rows[0].total;
    const map = new Map();
    rows.forEach((r) => map.set(r.date, { date: r.date, pf: (r.total / pf0) * 100 }));
    const alphas = [];
    const pfRet = (rows[rows.length - 1].total / pf0 - 1) * 100;
    bsel.forEach((k) => {
      const serie = (data.benchmarks[k] || []).filter((p) => p.date >= start && p.date <= end);
      if (serie.length < 2) return;
      const b0 = serie[0].value;
      serie.forEach((p) => {
        const o = map.get(p.date) || { date: p.date };
        o[k] = (p.value / b0) * 100;
        map.set(p.date, o);
      });
      const bret = (serie[serie.length - 1].value / b0 - 1) * 100;
      alphas.push({ key: k, bret, alpha: pfRet - bret });
    });
    const merged = [...map.values()].sort((a, b) => a.date.localeCompare(b.date));
    return { merged, alphas, pfRet };
  }, [data, rows, bsel]);

  const toggleBench = (key) =>
    setBsel((p) => (p.includes(key) ? p.filter((x) => x !== key) : [...p, key]));

  if (loading && !snap) return <main><p className="status">データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const cost = data?.cost_total ?? 0;

  return (
    <main>
      <TopBar loadedAt={snap.loadedAt} marketFetchedAt={snap.market_fetched_at} loading={loading} onReload={reload} />
      <h3>📈 資産推移</h3>

      {histLoading && <p className="caption">資産推移を取得中...</p>}
      {histError && <div className="alert down">エラー: {histError}</div>}

      {data && data.history.length === 0 && (
        <p className="caption">記録がありません。Streamlit版ヘッダーの「💾 記録」で記録を開始できます。</p>
      )}

      {data && data.history.length > 0 && (
        <>
          <div className="subtabs" style={{ marginTop: "0.4rem" }}>
            {PERIODS.map(([label, d]) => (
              <button key={label} className={days === d ? "active" : ""} onClick={() => setDays(d)}>{label}</button>
            ))}
          </div>
          <label className="chkrow">
            <input type="checkbox" checked={showCost} onChange={(e) => setShowCost(e.target.checked)} />
            投資元本ラインを表示
          </label>
          {change && (
            <p className="caption">
              期間変化:{" "}
              <b style={{ color: pnlColor(change.chg) }}>
                {pnlSign(change.chg)}{fmt0(change.chg)}円 ({pnlSign(change.chg)}{change.pct.toFixed(1)}%)
              </b>
            </p>
          )}

          {rows.length === 0 ? (
            <p className="caption">選択期間内に記録がありません。</p>
          ) : (
            <div className="chartbox">
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={rows} margin={{ top: 10, right: 30, bottom: 10, left: 20 }}>
                  <CartesianGrid stroke="#2B3240" strokeDasharray="2 2" />
                  <XAxis dataKey="date" tick={AXIS_TICK} stroke="#2B3240" minTickGap={40}
                    tickFormatter={(t) => t.slice(0, 7).replace("-", "/")} />
                  <YAxis tick={AXIS_TICK} stroke="#2B3240" width={90} domain={["auto", "auto"]}
                    tickFormatter={fmt0} />
                  <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [`${fmt0(v)}円`, "評価額"]} />
                  <Legend wrapperStyle={{ fontSize: 11, color: "#B0B8C0" }} />
                  {showCost && cost > 0 && (
                    <ReferenceLine y={cost} stroke="#FFD54F" strokeDasharray="6 4"
                      label={{ value: "投資元本(概算)", fill: "#FFD54F", fontSize: 10, position: "insideBottomLeft" }} />
                  )}
                  <Line type="monotone" dataKey="total" name="評価額" stroke="#00E676" strokeWidth={2}
                    dot={{ r: 3, fill: "#FFFFFF", strokeWidth: 0 }} isAnimationActive={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {rows.length >= 2 && (
            <>
              <h4 className="subhead">📊 ベンチマーク比較（期間開始=100に指数化）</h4>
              <div className="pickrow">
                {BENCHMARKS.map((b) => (
                  <button
                    key={b.key}
                    className={`pick ${bsel.includes(b.key) ? "on" : ""}`}
                    style={bsel.includes(b.key) ? { borderColor: b.color, color: b.color } : undefined}
                    onClick={() => toggleBench(b.key)}
                  >
                    {b.label}
                  </button>
                ))}
              </div>

              {bsel.length === 0 && <p className="caption">ベンチマークを1つ以上選択してください。</p>}
              {bsel.length > 0 && !bench && (
                <p className="caption">ベンチマーク価格を取得できませんでした。</p>
              )}
              {bench && bench.alphas.length === 0 && (
                <p className="caption">選択期間内のベンチマーク価格が不足しています。</p>
              )}

              {bench && bench.alphas.length > 0 && (
                <>
                  <div className="chartbox">
                    <ResponsiveContainer width="100%" height={300}>
                      <LineChart data={bench.merged} margin={{ top: 10, right: 30, bottom: 10, left: 20 }}>
                        <CartesianGrid stroke="#2B3240" strokeDasharray="2 2" />
                        <XAxis dataKey="date" tick={AXIS_TICK} stroke="#2B3240" minTickGap={40}
                          tickFormatter={(t) => t.slice(0, 7).replace("-", "/")} />
                        <YAxis tick={AXIS_TICK} stroke="#2B3240" width={60} domain={["auto", "auto"]}
                          label={{ value: "指数(開始=100)", angle: -90, position: "insideLeft", fill: "#9E9E9E", fontSize: 11 }}
                          tickFormatter={(v) => Math.round(v)} />
                        <Tooltip contentStyle={TOOLTIP_STYLE}
                          formatter={(v, n) => [Number(v).toFixed(2), n]} />
                        <Legend wrapperStyle={{ fontSize: 11, color: "#B0B8C0" }} />
                        <Line type="monotone" dataKey="pf" name="あなたの評価額" stroke="#00E676" strokeWidth={2}
                          dot={{ r: 2.5, fill: "#00E676", strokeWidth: 0 }} connectNulls isAnimationActive={false} />
                        {bsel.map((k) => {
                          const b = BENCHMARKS.find((x) => x.key === k);
                          return (
                            <Line key={k} type="monotone" dataKey={k} name={`${b.label}(円換算)`}
                              stroke={b.color} strokeWidth={1.5} dot={false} connectNulls isAnimationActive={false} />
                          );
                        })}
                      </LineChart>
                    </ResponsiveContainer>
                  </div>
                  {bench.alphas.map(({ key, bret, alpha }) => {
                    const b = BENCHMARKS.find((x) => x.key === key);
                    return (
                      <p className="caption" key={key}>
                        {b.label}対比 α:{" "}
                        <b style={{ color: pnlColor(alpha) }}>{pnlSign(alpha)}{alpha.toFixed(2)}pt</b>{" "}
                        （あなた {pnlSign(bench.pfRet)}{bench.pfRet.toFixed(2)}% vs {b.label} {pnlSign(bret)}{bret.toFixed(2)}%）
                      </p>
                    );
                  })}
                  <p className="caption">
                    ※ ベンチマークはETF(ACWI/S&P500)を円換算し期間開始=100に指数化した簡易比較。投信オルカンの基準価額とは厳密には一致しない。
                  </p>
                </>
              )}
            </>
          )}
        </>
      )}
    </main>
  );
}
