"use client";

import { useMemo, useState } from "react";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { fmtInt, fmtIntTrunc } from "../../lib/format";

// tab_dividend.py:15-26 と同一: 配当月(カンマ区切り)で予想配当を等分配
function buildCalendar(rows) {
  const mdv = {}, mda = {}, mdt = {};
  for (let m = 1; m <= 12; m++) { mdv[m] = 0; mda[m] = 0; mdt[m] = []; }
  rows.forEach((row) => {
    const da = row["予想配当(円)"] || 0;
    const daa = row["税引後配当(円)"] || 0;
    const dms = String(row["配当月"] ?? "");
    if (da > 0 && dms) {
      const ml = dms.split(",").map((x) => x.trim()).filter((x) => /^\d+$/.test(x)).map(Number);
      if (!ml.length) return;
      const p = da / ml.length;
      const pa = daa / ml.length;
      const tl = String(row["口座区分"] ?? "").includes("NISA") ? "非課税" : "課税";
      ml.forEach((m) => {
        if (m >= 1 && m <= 12) {
          mdv[m] += p;
          mda[m] += pa;
          mdt[m].push({ name: `${row["銘柄コード"]} ${row["銘柄名"]}`, pre: p, post: pa, tax: tl });
        }
      });
    }
  });
  return { mdv, mda, mdt };
}

export default function Dividend() {
  const { snap, error, loading, reload } = useSnapshot();
  const [openMonth, setOpenMonth] = useState(null);

  const d = useMemo(() => {
    if (!snap) return null;
    const rows = snap.rows;
    if (!rows.length || snap.totals.total_asset <= 0) return { empty: true };
    const { mdv, mda, mdt } = buildCalendar(rows);
    const tcd = Object.values(mdv).reduce((s, x) => s + x, 0);
    const tcda = Object.values(mda).reduce((s, x) => s + x, 0);
    const activeMonths = Object.values(mdv).filter((v) => v > 0).length;
    const rank = rows
      .filter((r) => (r["予想配当(円)"] || 0) > 0)
      .sort((a, b) => (b["予想配当(円)"] || 0) - (a["予想配当(円)"] || 0))
      .slice(0, 10);
    return { mdv, mda, mdt, tcd, tcda, activeMonths, rank };
  }, [snap]);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap || !d) return null;

  const header = <TopBar loadedAt={snap.loadedAt} loading={loading} onReload={reload} />;
  if (d.empty) {
    return (
      <main>
        {header}
        <p className="status">銘柄を追加すると配当カレンダーが表示されます。</p>
      </main>
    );
  }

  const { mdv, mda, mdt, tcd, tcda, activeMonths, rank } = d;

  return (
    <main>
      {header}

      <h3>💰 月別配当カレンダー</h3>
      <div className="monthgrid">
        {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => (
          <button
            key={m}
            className={`monthcell ${mdv[m] > 0 ? "has" : "empty"} ${openMonth === m ? "active" : ""}`}
            onClick={() => mdv[m] > 0 && setOpenMonth(openMonth === m ? null : m)}
          >
            <span className="mlabel">{m}月</span>
            {mdv[m] > 0 ? (
              <>
                <span className="mamount">¥{fmtInt(mda[m])}</span>
                <span className="msub">手取り·{mdt[m].length}銘柄</span>
              </>
            ) : (
              <span className="mamount dim">—</span>
            )}
          </button>
        ))}
      </div>

      {openMonth && mdv[openMonth] > 0 && (
        <div className="scard" style={{ marginTop: "0.8rem" }}>
          <h4>
            📅 {openMonth}月 — 税引前:¥{fmtInt(mdv[openMonth])} → 手取り:¥{fmtInt(mda[openMonth])}
          </h4>
          {mdt[openMonth]
            .slice()
            .sort((a, b) => b.pre - a.pre)
            .map((x, i) => (
              <div key={i} className="divrow">
                <span className="name">
                  {x.tax === "非課税" ? "🟢" : "🟡"} {x.name}
                </span>
                <span className="amt">¥{fmtInt(x.post)}</span>
              </div>
            ))}
        </div>
      )}

      {tcd > 0 && (
        <div className="grid4" style={{ marginTop: "1rem" }}>
          <div className="scard" style={{ borderLeft: "3px solid #FFD54F" }}>
            <h4>年間配当（税引前）</h4>
            <p className="mv" style={{ color: "#FFD54F" }}>¥{fmtInt(tcd)}</p>
          </div>
          <div className="scard" style={{ borderLeft: "3px solid #69F0AE" }}>
            <h4>年間手取り（税引後）</h4>
            <p className="mv" style={{ color: "#69F0AE" }}>¥{fmtInt(tcda)}</p>
          </div>
          <div className="scard" style={{ borderLeft: "3px solid #00D2FF" }}>
            <h4>月平均手取り</h4>
            <p className="mv" style={{ color: "#00D2FF" }}>¥{fmtInt(tcda / 12)}</p>
          </div>
          <div className="scard" style={{ borderLeft: "3px solid #BD93F9" }}>
            <h4>配当発生月</h4>
            <p className="mv" style={{ color: "#BD93F9" }}>
              {activeMonths}<span>/12ヶ月</span>
            </p>
          </div>
        </div>
      )}

      <h3>🏆 配当金ランキング</h3>
      {rank.length > 0 && (
        <div className="tablewrap tight">
          <table>
            <thead>
              <tr>
                <th className="l">銘柄コード</th>
                <th className="l">銘柄名</th>
                <th>予想配当(円)</th>
                <th>実質利回り(%)</th>
              </tr>
            </thead>
            <tbody>
              {rank.map((r, i) => (
                <tr key={i}>
                  <td className="l">{r["銘柄コード"]}</td>
                  <td className="l">{r["銘柄名"]}</td>
                  <td>¥{fmtIntTrunc(r["予想配当(円)"])}</td>
                  <td>{typeof r["実質利回り(%)"] === "number" ? `${r["実質利回り(%)"].toFixed(2)}%` : "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  );
}
