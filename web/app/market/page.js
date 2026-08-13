"use client";

import { useEffect, useState } from "react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
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
const PERIODS = ["1週間", "1ヶ月", "3ヶ月", "1年"];
const WEEK_OPTIONS = [
  ["12週", 12],
  ["26週", 26],
  ["52週", 52],
];

const fmt2 = (n) => n.toLocaleString("ja-JP", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtOku = (n) => `${n >= 0 ? "+" : ""}${Math.round(n).toLocaleString("ja-JP")}`;

function IndexCard({ item, period }) {
  if (item.status !== "ok") {
    return (
      <div className="idxcard">
        <div className="idxinfo">
          <p className="nm">{item.name}</p>
          <p className="neg">{item.status}</p>
        </div>
      </div>
    );
  }
  const up = item.pct >= 0;
  const color = up ? "#00E676" : "#FF5252";
  const sign = up ? "+" : "";
  const vals = item.series.map((s) => s.v);
  const mn = Math.min(...vals);
  const mx = Math.max(...vals);
  const mg = mx !== mn ? (mx - mn) * 0.1 : item.last * 0.1;
  return (
    <div className="idxcard">
      <div className="idxinfo">
        <p className="nm">{item.name}</p>
        <p className="val">{fmt2(item.last)}</p>
        <p className="chg" style={{ color }}>
          {sign}{fmt2(item.diff)}
          <br />({sign}{item.pct.toFixed(2)}%)
        </p>
      </div>
      <div className="idxchart">
        <ResponsiveContainer width="100%" height={180}>
          <AreaChart data={item.series} margin={{ top: 10, right: 10, bottom: 20, left: 0 }}>
            <CartesianGrid stroke="#2B3240" strokeDasharray="2 2" />
            <XAxis
              dataKey="t" tick={AXIS_TICK} stroke="#2B3240" minTickGap={30}
              tickFormatter={(t) => (period === "1年" ? t.slice(0, 7).replace("-", "/") : t.slice(5).replace("-", "/"))}
            />
            <YAxis
              domain={[mn - mg, mx + mg]} tick={AXIS_TICK} stroke="#2B3240" width={55}
              tickFormatter={(v) => v.toLocaleString("ja-JP", { maximumFractionDigits: 0 })}
            />
            <Tooltip
              contentStyle={TOOLTIP_STYLE}
              formatter={(v) => [fmt2(v), item.name]}
              labelFormatter={(l) => l}
            />
            <Area type="monotone" dataKey="v" stroke={color} strokeWidth={2}
              fill={up ? "rgba(0,230,118,0.15)" : "rgba(255,82,82,0.15)"} isAnimationActive={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function InvestorFlow() {
  const [weeks, setWeeks] = useState(12);
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [picked, setPicked] = useState(["FrgnBal", "IndBal"]);
  const [showCum, setShowCum] = useState(true);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    apiGet(`/api/market/investor-flow?weeks=${weeks}`)
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [weeks]);

  const toggle = (key) =>
    setPicked((p) => (p.includes(key) ? p.filter((x) => x !== key) : [...p, key]));

  return (
    <>
      <h3>📡 投資部門別 売買フロー (TSEPrime)</h3>
      <p className="caption">
        誰が買い、誰が売っているか（週次ネット買越額）。公表は翌週木曜のため約1週遅れ。中期の地合い確認用で、短期売買のトリガーには使えない。
      </p>
      <details className="expander">
        <summary>📖 この指標の読み方</summary>
        <ul className="readme">
          <li><b>海外投資家 = 方向性のドライバー</b>。プライム売買代金の6〜7割を占め、TOPIXの中期トレンドは海外勢の連続買越/売越とかなり連動する。単週の額より「<b>何週連続・累計いくら</b>」を見る。</li>
          <li><b>個人 = 逆張り指標</b>。下落時に買い、上昇時に売る構造的傾向がある。個人の大幅買越=下値を拾っている（底堅い）、大幅売越=上昇の戻り売り。</li>
          <li><b>信託銀行 = 年金のリバランス</b>。3月・9月の期末前後は機械的売買が出るためカレンダー要因として割り引く。</li>
          <li>投資信託・事業法人などは単独ではノイズが多く、補助的に見る程度でいい。</li>
        </ul>
      </details>

      <div className="subtabs">
        {WEEK_OPTIONS.map(([label, w]) => (
          <button key={w} className={weeks === w ? "active" : ""} onClick={() => setWeeks(w)}>{label}</button>
        ))}
      </div>

      {loading && <p className="caption">取得中...</p>}
      {error && <div className="alert down">エラー: {error}</div>}
      {data && !data.available && <div className="alert warn">{data.reason}</div>}

      {data?.available && (
        <>
          {data.summary.length > 0 && (
            <div className="flowsummary">
              {data.summary.map((s) => (
                <span key={s.col}>
                  <span className="lbl">{s.col === "FrgnBal" ? "🌐" : "👤"} {s.label}:</span>{" "}
                  <b style={{ color: s.sign > 0 ? "#26A69A" : "#EF5350" }}>
                    {s.weeks}週連続{s.sign > 0 ? "買越" : "売越"}
                  </b>{" "}
                  <span style={{ color: s.sign > 0 ? "#26A69A" : "#EF5350" }}>累計 {fmtOku(s.cum_oku)}億円</span>{" "}
                  <span className="sub">(直近週 {fmtOku(s.latest_oku)}億)</span>
                </span>
              ))}
            </div>
          )}

          <div className="pickrow">
            {data.columns.map((c) => (
              <button
                key={c.key}
                className={`pick ${picked.includes(c.key) ? "on" : ""}`}
                style={picked.includes(c.key) ? { borderColor: c.color, color: c.color } : undefined}
                onClick={() => toggle(c.key)}
              >
                {c.label}
              </button>
            ))}
          </div>

          {picked.length === 0 ? (
            <p className="caption">部門を1つ以上選択してね</p>
          ) : (
            <>
              <div className="chartbox">
                <ResponsiveContainer width="100%" height={360}>
                  <BarChart data={data.rows} margin={{ top: 10, right: 50, bottom: 30, left: 20 }}>
                    <CartesianGrid stroke="#2B3240" strokeDasharray="2 2" />
                    <XAxis dataKey="date" tick={AXIS_TICK} stroke="#2B3240" minTickGap={20}
                      tickFormatter={(t) => (weeks > 26 ? t.slice(0, 7).replace("-", "/") : t.slice(5).replace("-", "/"))} />
                    <YAxis yAxisId="l" tick={AXIS_TICK} stroke="#2B3240" width={80}
                      tickFormatter={(v) => Math.round(v).toLocaleString("ja-JP")}
                      label={{ value: "ネット買越額 (億円)", angle: -90, position: "insideLeft", fill: "#9E9E9E", fontSize: 11, offset: -10 }} />
                    <YAxis yAxisId="r" orientation="right" tick={{ ...AXIS_TICK, fill: "#EF9A9A" }} stroke="#2B3240" width={60}
                      domain={["auto", "auto"]}
                      tickFormatter={(v) => Math.round(v).toLocaleString("ja-JP")} />
                    <ReferenceLine yAxisId="l" y={0} stroke="#777" />
                    <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, n) => [`${fmtOku(v)}億円`, n]} />
                    <Legend wrapperStyle={{ fontSize: 11, color: "#B0B8C0" }} />
                    {picked.map((k) => {
                      const c = data.columns.find((x) => x.key === k);
                      return <Bar key={k} yAxisId="l" dataKey={k} name={c?.label ?? k} fill={c?.color ?? "#888"} isAnimationActive={false} />;
                    })}
                  </BarChart>
                </ResponsiveContainer>
                {data.topix.length > 0 && (
                  <ResponsiveContainer width="100%" height={120}>
                    <LineChart data={data.topix} margin={{ top: 4, right: 50, bottom: 10, left: 20 }}>
                      <CartesianGrid stroke="#2B3240" strokeDasharray="2 2" />
                      <XAxis dataKey="date" tick={AXIS_TICK} stroke="#2B3240" minTickGap={20}
                        tickFormatter={(t) => t.slice(5).replace("-", "/")} />
                      <YAxis tick={{ ...AXIS_TICK, fill: "#EF9A9A" }} stroke="#2B3240" width={80} domain={["auto", "auto"]}
                        tickFormatter={(v) => Math.round(v).toLocaleString("ja-JP")}
                        label={{ value: "TOPIX", angle: -90, position: "insideLeft", fill: "#EF9A9A", fontSize: 11, offset: -10 }} />
                      <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v) => [Math.round(v).toLocaleString("ja-JP"), "TOPIX"]} />
                      <Line type="monotone" dataKey="close" stroke="#EF9A9A" strokeWidth={1.5} dot={false} isAnimationActive={false} />
                    </LineChart>
                  </ResponsiveContainer>
                )}
              </div>

              <label className="chkrow">
                <input type="checkbox" checked={showCum} onChange={(e) => setShowCum(e.target.checked)} />
                累積買越額グラフを表示（TOPIXと重ねてマネー流入の中長期トレンドを確認）
              </label>

              {showCum && (
                <div className="chartbox">
                  <ResponsiveContainer width="100%" height={320}>
                    <LineChart
                      data={(() => {
                        const acc = {};
                        return data.rows.map((r) => {
                          const o = { date: r.date };
                          picked.forEach((k) => {
                            acc[k] = (acc[k] ?? 0) + (r[k] ?? 0);
                            o[k] = acc[k];
                          });
                          return o;
                        });
                      })()}
                      margin={{ top: 10, right: 50, bottom: 30, left: 20 }}
                    >
                      <CartesianGrid stroke="#2B3240" strokeDasharray="2 2" />
                      <XAxis
                        dataKey="date" tick={AXIS_TICK} stroke="#2B3240" minTickGap={20}
                        // 月表記は重複するため、月が変わる週だけラベルを出す(Plotlyの自動間引き相当)
                        tickFormatter={(t, i) => {
                          const rows = data.rows;
                          const prev = i > 0 ? rows[i - 1]?.date?.slice(0, 7) : null;
                          return t.slice(0, 7) === prev ? "" : t.slice(0, 7).replace("-", "/");
                        }}
                      />
                      <YAxis tick={AXIS_TICK} stroke="#2B3240" width={80}
                        tickFormatter={(v) => Math.round(v).toLocaleString("ja-JP")}
                        label={{ value: "累積買越額 (億円)", angle: -90, position: "insideLeft", fill: "#9E9E9E", fontSize: 11, offset: -10 }} />
                      <ReferenceLine y={0} stroke="#777" />
                      <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, n) => [`${fmtOku(v)}億円`, n]} />
                      <Legend wrapperStyle={{ fontSize: 11, color: "#B0B8C0" }} />
                      {picked.map((k) => {
                        const c = data.columns.find((x) => x.key === k);
                        return <Line key={k} type="monotone" dataKey={k} name={c?.label ?? k} stroke={c?.color ?? "#888"} strokeWidth={2} dot={false} isAnimationActive={false} />;
                      })}
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}

              {picked.includes("TrstBnkBal") && (
                <p className="caption">※ 信託銀行は年金基金の売買を反映。3月・9月の期末前後は機械的なリバランス売買が出やすく、相場観のシグナルではない。</p>
              )}

              <h4 className="subhead">直近4週 ネット買越額 (億円)</h4>
              <div className="tablewrap tight">
                <table>
                  <thead>
                    <tr>
                      <th className="l">週末日</th>
                      {picked.map((k) => <th key={k}>{data.columns.find((c) => c.key === k)?.label ?? k}</th>)}
                    </tr>
                  </thead>
                  <tbody>
                    {data.rows.slice(-4).map((r) => (
                      <tr key={r.date}>
                        <td className="l">{r.date}</td>
                        {picked.map((k) => <td key={k}>{r[k] == null ? "-" : Math.round(r[k]).toLocaleString("ja-JP")}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {data.signals.length > 0 && (
                <>
                  <h4 className="subhead">フロー検出シグナル</h4>
                  <ul className="readme">
                    {data.signals.map((s, i) => <li key={i}>{s}</li>)}
                  </ul>
                </>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}

export default function Market() {
  const { snap, error, loading, reload } = useSnapshot();
  const [period, setPeriod] = useState("1ヶ月");
  const [indices, setIndices] = useState(null);
  const [idxError, setIdxError] = useState("");
  const [idxLoading, setIdxLoading] = useState(true);

  useEffect(() => {
    setIdxLoading(true);
    apiGet(`/api/market/indices?period=${encodeURIComponent(period)}`)
      .then((d) => { setIndices(d); setIdxError(""); })
      .catch((e) => setIdxError(e.message))
      .finally(() => setIdxLoading(false));
  }, [period]);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  return (
    <main>
      <TopBar loadedAt={snap.loadedAt} loading={loading} onReload={reload} />
      <div className="subtabs" style={{ marginTop: "0.4rem" }}>
        {PERIODS.map((p) => (
          <button key={p} className={period === p ? "active" : ""} onClick={() => setPeriod(p)}>{p}</button>
        ))}
      </div>
      {idxLoading && <p className="caption">指標データを取得中...</p>}
      {idxError && <div className="alert down">エラー: {idxError}</div>}
      {indices && (
        <div className="idxgrid">
          {indices.indices.map((it) => <IndexCard key={it.ticker} item={it} period={period} />)}
        </div>
      )}
      <InvestorFlow />
    </main>
  );
}
