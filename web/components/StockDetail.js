"use client";

import { useEffect, useState } from "react";
import {
  Area,
  Bar,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { apiGet } from "../lib/api";
import { fmtInt, fmtNum } from "../lib/format";

const TOOLTIP_STYLE = {
  background: "#12121a",
  border: "1px solid #23232f",
  borderRadius: 6,
  fontSize: 12,
  color: "rgba(255,255,255,0.88)",
};

// tab_portfolio.py の指標ツールチップと同一文言
const TIP = {
  前日終値: "前営業日の市場終了時の株価",
  配当利回り: "年間配当金 ÷ 株価 x 100。高いほど配当収入が多い",
  "1株配当": "1株あたりの年間配当金額",
  PER: "株価収益率(Price Earnings Ratio)。株価 ÷ EPS。低いほど割安の目安",
  PBR: "株価純資産倍率(Price Book-value Ratio)。株価 ÷ BPS。1倍未満は解散価値以下",
  EPS: "1株当たり純利益(Earnings Per Share)。当期純利益 ÷ 発行済株式数",
  BPS: "1株当たり純資産(Book-value Per Share)。純資産 ÷ 発行済株式数",
  ROE: "自己資本利益率(Return On Equity)。当期純利益 ÷ 自己資本 x 100。経営効率の指標",
};
const TIP_RISK = {
  HV20: "20日ヒストリカルボラティリティ。日次リターン標準偏差の年率換算(%)",
  HV60: "60日ヒストリカルボラティリティ。長めの値動きの大きさ",
  "β (vs TOPIX)": "TOPIX変動1%に対する銘柄変動率。1.0=同等、>1.3=高ベータ",
  MDD: "最大ドローダウン。期間中の高値からの最大下落幅(%)",
  シャープ: "シャープレシオ(年率)。リターン÷リスク、1.0超で優秀",
  TOPIX相対: "期間始点から見たTOPIX対比の超過リターン(ppt)",
};

const fv = (v, digits = 2) => (v == null ? "-" : Number(v).toLocaleString("ja-JP", { maximumFractionDigits: digits, minimumFractionDigits: 0 }));

function MiniStat({ label, value, tip }) {
  return (
    <div title={tip || TIP[label] || ""} style={{ cursor: tip || TIP[label] ? "help" : "default" }}>
      <h4>{label}</h4>
      <p className="mv" style={{ fontSize: "1rem" }}>{value}</p>
    </div>
  );
}

export default function StockDetail({ row }) {
  const [bundle, setBundle] = useState(null);
  const [err, setErr] = useState("");
  const [loading, setLoading] = useState(false);

  const code = row ? String(row["銘柄コード"]) : "";
  const market = row ? String(row["市場"]) : "";
  const supported = market === "日本株" || market === "米国株";

  useEffect(() => {
    setBundle(null);
    setErr("");
    if (!row || !supported) return;
    const qs = new URLSearchParams({
      code,
      market,
      shares: String(row["保有株数"] ?? 0),
      buy_price: String(row["取得単価(円)"] ?? row["取得単価"] ?? 0),
      buy_date: String(row["取得日"] ?? ""),
    });
    let cancelled = false;
    setLoading(true);
    apiGet(`/api/stock/detail?${qs}`)
      .then((d) => !cancelled && setBundle(d))
      .catch((e) => !cancelled && setErr(e.message))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code, market, row]);

  if (!row) {
    return (
      <>
        <h3>🔎 銘柄詳細</h3>
        <p className="caption">↑ テーブルの行をクリックして銘柄を選択</p>
      </>
    );
  }

  const pnl = row["税引後損益(円)"] ?? 0;
  const pnlColor = pnl >= 0 ? "#00E676" : "#FF5252";
  const dod = row["前日比"];
  const buyDate = String(row["取得日"] ?? "");
  const ccy = market === "米国株" ? "$" : "¥";
  const d = bundle?.detail;
  const risk = bundle?.risk;
  const chart = bundle?.chart;
  const fin = bundle?.fin;

  return (
    <>
      <h3>🔎 銘柄詳細</h3>
      <div className="scard" style={{ borderLeft: "3px solid #00D2FF" }}>
        <h4>
          {code} {String(row["銘柄名"])} [{market}]
        </h4>
        <p className="mv">
          現在値 {fmtNum(row["現在値(円)"])}
          <span>円</span>{" "}
          <span style={{ fontSize: "0.9rem", color: pnlColor }}>
            {pnl >= 0 ? "+" : ""}
            {fmtInt(pnl)}円
          </span>
        </p>
        <p className="sv">
          取得単価 {fmtNum(row["取得単価(円)"] ?? row["取得単価"])}円 · {fmtNum(row["保有株数"])}株
          {typeof dod === "number" ? ` · 前日比 ${dod >= 0 ? "+" : ""}${dod.toFixed(2)}%` : ""}
          {buyDate ? ` · 取得日 ${buyDate}` : ""}
        </p>
      </div>

      {!supported && <p className="caption">投資信託・その他資産は株価チャート非対応です。</p>}
      {supported && loading && <p className="status">詳細データを取得中...</p>}
      {supported && err && <p className="status">詳細取得エラー: {err}</p>}

      {d && (
        <div className="grid4" style={{ marginTop: "0.8rem" }}>
          <div className="scard">
            <MiniStat label="前日終値" value={`${ccy}${fv(d["前日終値"])}`} />
            <MiniStat label="配当利回り" value={`${fv(d["配当利回り(%)"])}%`} />
          </div>
          <div className="scard">
            <MiniStat label="1株配当" value={`${ccy}${fv(d["1株配当"])}`} />
            <MiniStat label="PER" value={`${fv(d["PER"])}倍`} />
          </div>
          <div className="scard">
            <MiniStat label="PBR" value={`${fv(d["PBR"])}倍`} />
            <MiniStat label="EPS" value={`${ccy}${fv(d["EPS"])}`} />
          </div>
          <div className="scard">
            <MiniStat label="BPS" value={`${ccy}${fv(d["BPS"])}`} />
            <MiniStat label="ROE" value={`${fv(d["ROE(%)"])}%`} />
            <h4 style={{ marginTop: "0.4rem" }}>次回決算発表</h4>
            <p className="mv" style={{ fontSize: "0.9rem" }}>{d["次回決算発表"] || "-"}</p>
            <p className="sv">四半期末 {d["直近四半期末"] || "-"}</p>
          </div>
        </div>
      )}

      {risk && (
        <>
          <h3 style={{ marginTop: "1rem" }}>📐 リスク指標（1年）</h3>
          <div className="grid6">
            {[
              ["HV20", risk.HV20, "%", 1],
              ["HV60", risk.HV60, "%", 1],
              ["β (vs TOPIX)", risk.beta, "", 2],
              ["MDD", risk.MDD, "%", 1],
              ["シャープ", risk.Sharpe, "", 2],
              ["TOPIX相対", risk.relative_perf, "ppt", 1],
            ].map(([lbl, v, suf, dg]) => (
              <div key={lbl} className="scard">
                <MiniStat
                  label={lbl}
                  tip={TIP_RISK[lbl]}
                  value={v == null ? "-" : `${lbl === "TOPIX相対" && v >= 0 ? "+" : ""}${Number(v).toFixed(dg)}${suf}`}
                />
              </div>
            ))}
          </div>
        </>
      )}

      {chart && chart.points?.length >= 2 && (
        <div className="chartbox" style={{ marginTop: "1rem" }}>
          <p style={{ fontSize: "0.9rem", color: chart.pnl_val >= 0 ? "#00E676" : "#FF5252", margin: "0 0 4px" }}>
            損益 {chart.pnl_val >= 0 ? "+" : ""}
            {fmtInt(chart.pnl_val)}円 ({chart.pnl_val >= 0 ? "+" : ""}
            {chart.pnl_pct.toFixed(1)}%)
          </p>
          <ResponsiveContainer width="100%" height={330}>
            <ComposedChart data={chart.points} margin={{ top: 8, right: 12, bottom: 4, left: 12 }}>
              <XAxis dataKey="t" tick={{ fontSize: 10, fill: "#8a8f9c" }} minTickGap={60} />
              <YAxis
                tickFormatter={(v) => fmtInt(v)}
                tick={{ fontSize: 10, fill: "#8a8f9c" }}
                width={80}
                domain={["auto", "auto"]}
              />
              <Tooltip
                contentStyle={TOOLTIP_STYLE}
                formatter={(v) => [`${fmtInt(v)}円`, "評価額"]}
              />
              <Area type="monotone" dataKey="v" stroke="#00D2FF" strokeWidth={2} fill="rgba(0,210,255,0.08)" isAnimationActive={false} />
              <ReferenceLine y={chart.cost_total} stroke="#FFD54F" strokeWidth={1.5} strokeDasharray="6 4" label={{ value: "元本", fill: "#FFD54F", fontSize: 11, position: "insideTopLeft" }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {fin && fin.rows?.length > 0 && (
        <>
          <h3 style={{ marginTop: "1rem" }}>📈 業績推移（過去8期分）</h3>
          <div className="chartbox">
            <ResponsiveContainer width="100%" height={320}>
              <ComposedChart data={fin.rows} margin={{ top: 8, right: 12, bottom: 4, left: 12 }}>
                <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#8a8f9c" }} />
                <YAxis yAxisId="left" tick={{ fontSize: 10, fill: "#8a8f9c" }} width={64}
                       label={{ value: "売上/利益(億円)", angle: -90, position: "insideLeft", fill: "#8a8f9c", fontSize: 11 }} />
                <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: "#8a8f9c" }} width={56}
                       label={{ value: "EPS(円)", angle: 90, position: "insideRight", fill: "#8a8f9c", fontSize: 11 }} />
                <Tooltip contentStyle={TOOLTIP_STYLE} formatter={(v, name) => [fmtNum(v), name]} />
                {fin.metrics.includes("売上") && <Bar yAxisId="left" dataKey="売上" fill="#00D2FF" isAnimationActive={false} />}
                {fin.metrics.includes("営業利益") && <Bar yAxisId="left" dataKey="営業利益" fill="#69F0AE" isAnimationActive={false} />}
                {fin.metrics.includes("純利益") && <Bar yAxisId="left" dataKey="純利益" fill="#FFD54F" isAnimationActive={false} />}
                {fin.metrics.includes("EPS") && (
                  <Line yAxisId="right" type="monotone" dataKey="EPS" stroke="#FF8F00" strokeWidth={2} strokeDasharray="4 3" dot={{ r: 3 }} isAnimationActive={false} />
                )}
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      {bundle?.revisions?.length > 0 && (
        <div style={{ marginTop: "0.6rem" }}>
          <b style={{ fontSize: "0.9rem" }}>業績修正検出</b>
          {bundle.revisions.map((m, i) => (
            <p key={i} className="sv" style={{ margin: "2px 0" }}>・{m}</p>
          ))}
        </div>
      )}
    </>
  );
}
