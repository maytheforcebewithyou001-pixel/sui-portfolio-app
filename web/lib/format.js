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
// Python format(v, ",.4g") の忠実再現。有効4桁を超える整数は指数表記になる(例 13973 → 1.397e+04)
export function fmtG4(n) {
  if (typeof n !== "number" || !isFinite(n)) return n ?? "-";
  if (n === 0) return "0";
  const P = 4;
  const exp = Math.floor(Math.log10(Math.abs(n)));
  if (exp < -4 || exp >= P) {
    // 指数表記: 仮数は有効P桁(末尾ゼロ除去)、指数は符号+2桁
    const mant = (n / Math.pow(10, exp)).toFixed(P - 1).replace(/\.?0+$/, "");
    const sign = exp < 0 ? "-" : "+";
    return `${mant}e${sign}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  const fixed = n.toFixed(Math.max(P - 1 - exp, 0)).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
  const [i, d] = fixed.split(".");
  return Number(i).toLocaleString("ja-JP") + (d ? `.${d}` : "");
}
