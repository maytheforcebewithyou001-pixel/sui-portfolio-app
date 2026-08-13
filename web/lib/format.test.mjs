// fmtG4 が Python format(v, ",.4g") と一致することの回帰テスト
// 実行: node web/lib/format.test.mjs  (期待値は python -c 'format(v, ",.4g")' で採取)
import assert from "node:assert";
import { readFileSync } from "node:fs";

const src = readFileSync(new URL("./format.js", import.meta.url), "utf8");
const mod = await import(`data:text/javascript,${encodeURIComponent(src)}`);
const { fmtG4 } = mod;

const CASES = [
  [13973, "1.397e+04"],
  [13880, "1.388e+04"],
  [4871.0, "4,871"],
  [4702, "4,702"],
  [100, "100"],
  [3645, "3,645"],
  [0.4702, "0.4702"],
  [56.8394, "56.84"],
  [1.5, "1.5"],
  [69.5985, "69.6"],
  [0, "0"],
  [1000000, "1e+06"],
  [0.00001234, "1.234e-05"],
  [-13973, "-1.397e+04"],
  [-56.8394, "-56.84"],
];

for (const [input, expected] of CASES) {
  assert.strictEqual(fmtG4(input), expected, `fmtG4(${input}) = ${fmtG4(input)} but expected ${expected}`);
}
console.log(`fmtG4: ${CASES.length} cases OK (Python ",.4g" 準拠)`);
