// fmtNum が Streamlit版の数量書式と一致することの回帰テスト
// (tabs/tab_transaction.py, tab_currency.py: 整数は",.0f"・小数は",.4f"のrstrip)
// 実行: node web/lib/format.test.mjs
// 注: 丸め境界(小数5桁以上)はPython(half-even)とJS(halfExpand)で差が出うるが、
//     シート上の数量・保有株数は小数4桁までのため対象外。
import assert from "node:assert";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./format.js", import.meta.url), "utf8");
const mod = await import(`data:text/javascript,${encodeURIComponent(src)}`);
const { fmtNum } = mod;

const CASES = [
  [872455, "872,455"],
  [435256, "435,256"],
  [13973, "13,973"],
  [4702, "4,702"],
  [600, "600"],
  [100, "100"],
  [1000000, "1,000,000"],
  [0, "0"],
  [154.8484, "154.8484"],
  [32.3625, "32.3625"],
  [69.5985, "69.5985"],
  [0.4702, "0.4702"],
  [1.5, "1.5"],
  [-13973, "-13,973"],
  [-56.8394, "-56.8394"],
  [null, "-"],
];

for (const [input, expected] of CASES) {
  assert.strictEqual(fmtNum(input), expected, `fmtNum(${input}) = ${fmtNum(input)} but expected ${expected}`);
}
console.log(`fmtNum: ${CASES.length} cases OK (Streamlit版の数量書式と一致)`);
