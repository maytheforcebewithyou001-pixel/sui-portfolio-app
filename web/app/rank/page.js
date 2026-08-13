"use client";

import { useEffect, useState } from "react";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiGet } from "../../lib/api";
import { fmtInt } from "../../lib/format";

const rgb = (hex) => [
  parseInt(hex.slice(1, 3), 16),
  parseInt(hex.slice(3, 5), 16),
  parseInt(hex.slice(5, 7), 16),
];

export default function Rank() {
  const { snap, error, loading, reload } = useSnapshot();
  const [state, setState] = useState(null);
  const [rankError, setRankError] = useState("");

  useEffect(() => {
    apiGet("/api/rank").then(setState).catch((e) => setRankError(e.message));
  }, []);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const header = <TopBar loadedAt={snap.loadedAt} loading={loading} onReload={reload} />;
  if (rankError) return <main>{header}<div className="alert down">エラー: {rankError}</div></main>;
  if (!state) return <main>{header}<p className="status">読み込み中...</p></main>;

  const { rank, tiers, total_asset: TA } = state;
  const curLevel = rank?.level ?? 0;

  return (
    <main>
      {header}

      {rank ? (
        (() => {
          const [r, g, b] = rgb(rank.color);
          const fill = Math.round((rank.level / rank.max_level) * 10);
          const nextInfo =
            rank.level < rank.max_level
              ? { name: tiers[rank.level].name, remaining: tiers[rank.level].threshold - TA }
              : null;
          return (
            <div className="rankhero">
              <div className="cap">CURRENT RANK</div>
              <div className="name" style={{ color: rank.color, textShadow: `0 0 20px rgba(${r},${g},${b},0.4)` }}>
                {rank.name}
              </div>
              <div className="bars">
                <span style={{ color: rank.color }}>{"▰".repeat(fill)}</span>
                <span style={{ color: "rgba(255,255,255,0.12)" }}>{"▱".repeat(10 - fill)}</span>
              </div>
              <div className="lv">LV. {rank.level} / {rank.max_level}</div>
              <div className="next">
                {nextInfo ? (
                  <>次のランク <b>{nextInfo.name}</b> まで <b>¥{fmtInt(nextInfo.remaining)}</b></>
                ) : (
                  "全ランク制覇"
                )}
              </div>
            </div>
          );
        })()
      ) : (
        <div className="rankhero">
          <div className="cap">CURRENT RANK</div>
          <div className="name unranked">UNRANKED</div>
          <div className="next">最初のランク <b>CADET</b> まで <b>¥{fmtInt(1000000 - TA)}</b></div>
        </div>
      )}

      <div className="allranks">ALL RANKS</div>
      {tiers.map((t, i) => {
        const level = i + 1;
        const achieved = level <= curLevel;
        const isCurrent = level === curLevel;
        const [r, g, b] = rgb(t.color);
        const style = isCurrent
          ? { border: `1px solid rgba(${r},${g},${b},0.5)`, background: `rgba(${r},${g},${b},0.1)`, boxShadow: `0 0 15px rgba(${r},${g},${b},0.15)` }
          : achieved
          ? { border: `1px solid rgba(${r},${g},${b},0.25)`, background: `rgba(${r},${g},${b},0.05)` }
          : { border: "1px solid rgba(255,255,255,0.06)", background: "rgba(255,255,255,0.02)" };
        const nameStyle = isCurrent
          ? { color: t.color, fontWeight: 700 }
          : achieved
          ? { color: t.color }
          : { color: "rgba(255,255,255,0.25)" };
        const amountStyle = isCurrent
          ? { color: t.color }
          : achieved
          ? { color: "rgba(255,255,255,0.5)" }
          : { color: "rgba(255,255,255,0.2)" };
        return (
          <div key={t.name} className="ranktier" style={style}>
            <div className="left">
              <span className="lvlabel">LV.{level}</span>
              <span className="tname" style={nameStyle}>{t.name}</span>
              {isCurrent && <span className="now" style={{ color: t.color }}>◀ NOW</span>}
              {!isCurrent && achieved && <span className="check" style={{ color: `rgba(${r},${g},${b},0.5)` }}>✓</span>}
            </div>
            <span className="amt" style={amountStyle}>¥{fmtInt(t.threshold)}</span>
          </div>
        );
      })}
    </main>
  );
}
