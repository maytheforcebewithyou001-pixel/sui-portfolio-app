"use client";

import { useMemo, useState } from "react";
import StockDetail from "../components/StockDetail";
import TopBar from "../components/TopBar";
import { useSnapshot } from "../lib/useSnapshot";
import { fmtYen, signed, pnlCls, fmtNum } from "../lib/format";

// 保有一覧の表示列(display_dfの列名そのまま)
const COLUMNS = [
  { key: "銘柄コード", label: "コード", left: true },
  { key: "銘柄名", label: "銘柄名", left: true },
  { key: "市場", label: "市場", left: true },
  { key: "口座区分", label: "口座", left: true },
  { key: "保有株数", label: "数量" },
  { key: "現在値(円)", label: "現在値" },
  { key: "前日比", label: "前日比" },
  { key: "取得額(円)", label: "取得額" },
  { key: "評価額(円)", label: "評価額" },
  { key: "含み損益(円)", label: "含み損益" },
  { key: "税引後損益(円)", label: "税引後損益" },
  { key: "予想配当(円)", label: "予想配当" },
  { key: "実質利回り(%)", label: "利回り%" },
  { key: "口座", label: "証券会社", left: true },
  { key: "取得日", label: "取得日", left: true },
];

// 取得額は導出列: 評価額-含み損益(calc.py:116 の profit 定義の逆算。米国株の取得時為替も
// この差分に織り込み済み)。集約行でも合算値の差でそのまま成立する
const cellVal = (r, key) =>
  key === "取得額(円)" ? (r["評価額(円)"] || 0) - (r["含み損益(円)"] || 0) : r[key];

// 大幅変動: |前日比|>=3% を銘柄単位で1件に(app.py:432 の重複排除と同一)
function bigMovers(rows) {
  const seen = new Set();
  return rows.filter((r) => {
    if (typeof r["前日比"] !== "number" || Math.abs(r["前日比"]) < 3.0) return false;
    const key = `${r["銘柄コード"]}|${r["銘柄名"]}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

// 同一銘柄(コード|銘柄名)の複数口座行を1行に集約した表示用の行を作る。
// 数量・金額系は合計、実質利回りは calc.py:126 と同じ定義(予想配当÷評価額)で合算値から再計算
const SUM_KEYS = ["保有株数", "評価額(円)", "含み損益(円)", "税引後損益(円)", "予想配当(円)"];

function aggregate(rows) {
  const head = { ...rows[0] };
  for (const k of SUM_KEYS) {
    head[k] = rows.reduce((s, r) => s + (typeof r[k] === "number" ? r[k] : 0), 0);
  }
  // 同一口座の複数ロット(VT等)もあるため「口座数」ではなく内訳件数で表記する
  head["口座区分"] = `全口座(${rows.length})`;
  const brokers = new Set(rows.map((r) => String(r["口座"] || "")));
  head["口座"] = brokers.size === 1 ? [...brokers][0] : "-";
  const dates = new Set(rows.map((r) => String(r["取得日"] || "")));
  head["取得日"] = dates.size === 1 ? [...dates][0] : "-";
  const value = head["評価額(円)"];
  head["実質利回り(%)"] = value > 0 ? Math.round((head["予想配当(円)"] / value) * 10000) / 100 : 0;
  return head;
}

// 評価額メトリクスの前日比: 各行の前日比%から前日評価額を逆算して合算する。
// 前日比が無い行(国債・その他資産)と現金は変動0扱いで分母にのみ算入
function dayChangeTotal(rows, cashJpy) {
  let cur = cashJpy;
  let prev = cashJpy;
  rows.forEach((r) => {
    const v = r["評価額(円)"] || 0;
    const d = r["前日比"];
    cur += v;
    prev += typeof d === "number" && isFinite(d) && d > -100 ? v / (1 + d / 100) : v;
  });
  return { diff: cur - prev, pct: prev > 0 ? ((cur - prev) / prev) * 100 : 0 };
}

// 集中リスク: 単一銘柄30%超 or HHI2500超(app.py:437-448 と同一。分母は証券のみ)
function concentration(rows, totalAsset) {
  if (!rows.length || totalAsset <= 0) return null;
  const shares = rows.map((r) => (r["評価額(円)"] || 0) / totalAsset);
  const hhi = shares.reduce((s, x) => s + x * x, 0) * 10000;
  let top = 0;
  let topName = "";
  rows.forEach((r, i) => {
    if (shares[i] > top) {
      top = shares[i];
      topName = r["銘柄名"];
    }
  });
  if (top * 100 >= 30.0) return { kind: "single", name: topName, pct: top * 100, hhi };
  if (hhi >= 2500) return { kind: "hhi", hhi };
  return null;
}

export default function Dashboard() {
  const { snap, error, loading, reload } = useSnapshot();
  const [sort, setSort] = useState({ key: "評価額(円)", dir: -1 });
  const [selRow, setSelRow] = useState(null);
  const [expanded, setExpanded] = useState(() => new Set());

  // 同一銘柄を1グループにまとめ、集約行(head)基準でソート。子行は展開時のみ表示
  const groups = useMemo(() => {
    if (!snap) return [];
    const map = new Map();
    snap.rows.forEach((r) => {
      const key = `${r["銘柄コード"]}|${r["銘柄名"]}`;
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(r);
    });
    const gs = [...map.entries()].map(([key, rs]) => ({
      key,
      rows: rs,
      grouped: rs.length > 1,
      head: rs.length > 1 ? aggregate(rs) : rs[0],
    }));
    gs.sort((a, b) => {
      const va = cellVal(a.head, sort.key);
      const vb = cellVal(b.head, sort.key);
      if (va == null) return 1;
      if (vb == null) return -1;
      if (typeof va === "number" && typeof vb === "number") return (va - vb) * sort.dir;
      return String(va).localeCompare(String(vb), "ja") * sort.dir;
    });
    return gs;
  }, [snap, sort]);

  const toggleGroup = (key) =>
    setExpanded((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const t = snap.totals;
  const tgp = t.total_gross_profit;
  const pnlPct = t.total_asset - tgp > 0 ? (tgp / (t.total_asset - tgp)) * 100 : 0;
  const movers = bigMovers(snap.rows);
  const conc = concentration(snap.rows, t.total_asset);
  const day = dayChangeTotal(snap.rows, t.cash_jpy);

  return (
    <main>
      <TopBar loadedAt={snap.loadedAt} marketFetchedAt={snap.market_fetched_at} loading={loading} onReload={reload} />

      <div className="metrics">
        <div className="metric">
          <span className="label">評価額</span>
          <span className="big">{fmtYen(t.total_asset_all)}</span>
          <span className={`sub ${pnlCls(day.diff)}`}>
            前日比 {signed(day.diff)} ({day.diff >= 0 ? "+" : ""}
            {day.pct.toFixed(2)}%)
          </span>
          <span className="sub">
            (証券 {fmtYen(t.total_asset)} + 現金 {fmtYen(t.cash_jpy)})
          </span>
        </div>
        <div className="metric">
          <span className="label">損益</span>
          <span className={`mid ${pnlCls(tgp)}`}>{signed(tgp)}</span>
          <span className={`sub ${pnlCls(t.total_net_profit)}`}>
            (税引後 {signed(t.total_net_profit)})
          </span>
          <span className={`sub ${pnlCls(tgp)}`}>
            {tgp >= 0 ? "+" : ""}
            {pnlPct.toFixed(1)}%
          </span>
        </div>
        <div className="metric">
          <span className="label">年間配当(税引後)</span>
          <span className="mid gold">{fmtYen(t.total_dividend_after_tax)}</span>
          <span className="sub">{t.avg_dividend_yield.toFixed(2)}%</span>
        </div>
        <div className="metric">
          <span className="label">銘柄 / USD/JPY</span>
          <span className="mid">{t.stock_count}</span>
          <span className="sub">{snap.jpy_usd_rate.toFixed(2)}円</span>
        </div>
        {(t.total_stock_gain !== 0 || t.total_fx_gain !== 0) && (
          <div className="metric">
            <span className="label">米国株 株価/為替損益</span>
            <span className={`mid ${pnlCls(t.total_stock_gain)}`}>{signed(t.total_stock_gain)}</span>
            <span className={`sub ${pnlCls(t.total_fx_gain)}`}>
              (為替 {signed(t.total_fx_gain)})
            </span>
          </div>
        )}
      </div>

      {snap.warnings.map((w, i) => (
        <div key={i} className="alert warn">⚠ {w}</div>
      ))}

      {movers.map((r) => (
        <div key={`${r["銘柄コード"]}|${r["銘柄名"]}`} className={`alert ${r["前日比"] > 0 ? "up" : "down"}`}>
          {r["前日比"] > 0 ? "▲" : "▼"} <b>{r["銘柄名"]}</b>（{r["銘柄コード"]}）が前日比{" "}
          {r["前日比"] > 0 ? "+" : ""}
          {r["前日比"].toFixed(2)}% の大幅変動
        </div>
      ))}

      {conc && conc.kind === "single" && (
        <div className="alert down">
          ⚠ 集中リスク: <b>{conc.name}</b> が総資産の {conc.pct.toFixed(1)}% を占めています（推奨上限 30%）。
          HHI={Math.round(conc.hhi).toLocaleString("ja-JP")}（2500超で高集中）
        </div>
      )}
      {conc && conc.kind === "hhi" && (
        <div className="alert down">
          ⚠ ポートフォリオ集中度が高め（HHI={Math.round(conc.hhi).toLocaleString("ja-JP")}・2500超）。分散を検討してください。
        </div>
      )}

      <div className="tablewrap">
        <table>
          <thead>
            <tr>
              {COLUMNS.map((c) => (
                <th
                  key={c.key}
                  className={c.left ? "l" : ""}
                  onClick={() =>
                    setSort((s) => ({ key: c.key, dir: s.key === c.key ? -s.dir : -1 }))
                  }
                >
                  {c.label}
                  {sort.key === c.key ? (sort.dir === -1 ? " ▼" : " ▲") : ""}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {groups.flatMap((g) => {
              const open = expanded.has(g.key);
              const renderCells = (r, acctPrefix) =>
                COLUMNS.map((c) => {
                  const v = cellVal(r, c.key);
                  if (c.key === "口座区分") {
                    return (
                      <td key={c.key} className="l">
                        {acctPrefix}
                        {fmtNum(v)}
                      </td>
                    );
                  }
                  if (c.key === "前日比") {
                    return (
                      <td key={c.key} className={typeof v === "number" ? pnlCls(v) : ""}>
                        {typeof v === "number" ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "-"}
                      </td>
                    );
                  }
                  if (c.key.includes("損益")) {
                    return (
                      <td key={c.key} className={typeof v === "number" ? pnlCls(v) : ""}>
                        {typeof v === "number" ? signed(v) : "-"}
                      </td>
                    );
                  }
                  if (c.key.includes("(円)")) {
                    return <td key={c.key}>{typeof v === "number" ? fmtYen(v) : "-"}</td>;
                  }
                  return (
                    <td key={c.key} className={c.left ? "l" : ""}>
                      {fmtNum(v)}
                    </td>
                  );
                });
              const out = [
                <tr
                  key={g.key}
                  className={`clickable ${!g.grouped && selRow === g.head ? "selrow" : ""}`}
                  onClick={() =>
                    g.grouped ? toggleGroup(g.key) : setSelRow(selRow === g.head ? null : g.head)
                  }
                >
                  {renderCells(g.head, g.grouped ? (open ? "▾ " : "▸ ") : "")}
                </tr>,
              ];
              if (g.grouped && open) {
                g.rows.forEach((r, i) =>
                  out.push(
                    <tr
                      key={`${g.key}#${i}`}
                      className={`clickable subrow ${selRow === r ? "selrow" : ""}`}
                      onClick={() => setSelRow(selRow === r ? null : r)}
                    >
                      {renderCells(r, "└ ")}
                    </tr>
                  )
                );
              }
              return out;
            })}
          </tbody>
        </table>
      </div>

      <StockDetail row={selRow} />

      <p className="caption">
        {snap.gas_last_updated && `📡 GAS株価データ 最終更新: ${snap.gas_last_updated} ／ `}
        価格は yfinance / J-Quants 等から取得しており正確性・即時性を保証しません。本アプリは投資助言を行うものではありません。
      </p>
    </main>
  );
}
