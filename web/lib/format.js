// 表示書式ヘルパー(Streamlit版の f"{x:,.0f}円" 等と揃える)
export const fmtYen = (n) => `¥${Math.round(Math.abs(n)).toLocaleString("ja-JP")}`;
export const signed = (n) => `${n >= 0 ? "+" : "-"}${fmtYen(n)}`;
export const pnlCls = (n) => (n >= 0 ? "pos" : "neg");
export const fmtNum = (n) =>
  typeof n === "number" ? n.toLocaleString("ja-JP", { maximumFractionDigits: 4 }) : n ?? "-";
export const fmtInt = (n) => Math.round(n).toLocaleString("ja-JP");
// Streamlitのテーブル表示 int(x) と揃えるための切り捨て版(tab_analysis.py:61,75)
export const fmtIntTrunc = (n) => Math.trunc(n).toLocaleString("ja-JP");
export const fmtPct1 = (n) => `${n.toFixed(1)}%`;
// Python "{:+,.0f}円" 相当
export const signedYenInt = (n) =>
  `${n >= 0 ? "+" : "-"}${Math.round(Math.abs(n)).toLocaleString("ja-JP")}円`;
