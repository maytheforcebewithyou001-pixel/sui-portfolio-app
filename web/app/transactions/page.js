"use client";

import { useEffect, useMemo, useState } from "react";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiFetch, apiPost, clearSnapshot } from "../../lib/api";
import { fmtInt, fmtG4, signedYenInt, pnlCls } from "../../lib/format";

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, "0")}/${String(d.getDate()).padStart(2, "0")}`;
}

// tab_transaction.py の一覧表示と同じ整形
const fmtPnl = (x) => (x !== 0 ? signedYenInt(x) : "-");
const fmtPrice = (x) => (x > 0 ? fmtInt(x) : "-");

function TxForm({ state, onDone }) {
  const [sel, setSel] = useState(0);
  const [txType, setTxType] = useState("買い増し");
  const [date, setDate] = useState(todayStr());
  const [qty, setQty] = useState(1);
  const [price, setPrice] = useState(0);
  const [fee, setFee] = useState(0);
  const [broker, setBroker] = useState(state.broker_options[0] ?? "");
  const [tax, setTax] = useState(state.tax_options[0] ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null); // {ok, text, pnl}

  const holdings = state.holdings;
  if (!holdings.length) return null;
  const h = holdings[Math.min(sel, holdings.length - 1)];

  const submit = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const res = await apiPost("/api/transactions", {
        index: h.index, code: h.code, tx_type: txType, date,
        qty: Number(qty), price: Number(price), fee: Number(fee), broker, tax,
      });
      setMsg({ ok: true, text: `✓ ${txType} 記録完了。保有数を更新しました。`, pnl: txType === "売却" ? res.pnl_realized : 0 });
      clearSnapshot();
      onDone();
    } catch (e) {
      setMsg({ ok: false, text: `記録に失敗: ${e.message}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <details className="expander" open>
      <summary>➕ 取引を記録</summary>
      <div className="paramrow" style={{ marginTop: "0.6rem" }}>
        <label className="inlineinput" style={{ margin: 0 }}>
          取引種別
          <select value={txType} onChange={(e) => setTxType(e.target.value)}>
            {["買い増し", "売却", "新規購入"].map((o) => <option key={o}>{o}</option>)}
          </select>
        </label>
        <label className="inlineinput" style={{ margin: 0, flex: 1 }}>
          銘柄
          <select value={sel} onChange={(e) => setSel(Number(e.target.value))} style={{ width: "100%" }}>
            {holdings.map((r, i) => (
              <option key={r.index} value={i}>
                {r.code} {r.name} [{r.broker} / {r.tax}]
              </option>
            ))}
          </select>
        </label>
        <label className="inlineinput" style={{ margin: 0 }}>
          取引日
          <input type="text" value={date} onChange={(e) => setDate(e.target.value)} placeholder="YYYY/MM/DD" />
        </label>
      </div>
      <div className="paramrow">
        <label className="inlineinput" style={{ margin: 0 }}>
          数量
          <input type="number" min="0.0001" step="1" value={qty} onChange={(e) => setQty(e.target.value)} />
        </label>
        <label className="inlineinput" style={{ margin: 0 }}>
          単価(円)
          <input type="number" min="0" value={price} onChange={(e) => setPrice(e.target.value)} />
        </label>
        <label className="inlineinput" style={{ margin: 0 }}>
          手数料(円)
          <input type="number" min="0" value={fee} onChange={(e) => setFee(e.target.value)} />
        </label>
        <label className="inlineinput" style={{ margin: 0 }}>
          口座
          <select value={broker} onChange={(e) => setBroker(e.target.value)}>
            {state.broker_options.map((o) => <option key={o}>{o}</option>)}
          </select>
        </label>
        <label className="inlineinput" style={{ margin: 0 }}>
          口座区分
          <select value={tax} onChange={(e) => setTax(e.target.value)}>
            {state.tax_options.map((o) => <option key={o}>{o}</option>)}
          </select>
        </label>
      </div>
      <button className="ghost wide" onClick={submit} disabled={busy}>
        {busy ? "記録中..." : "記録する"}
      </button>
      {msg && <div className={`alert ${msg.ok ? "up" : "down"}`}>{msg.text}</div>}
      {msg?.ok && msg.pnl !== 0 && (
        <div className={`alert ${msg.pnl >= 0 ? "up" : "down"}`}>
          確定損益: <b className={pnlCls(msg.pnl)}>{signedYenInt(msg.pnl)}</b>
        </div>
      )}
    </details>
  );
}

function CsvImport({ onDone }) {
  const [fileB64, setFileB64] = useState(null);
  const [fileName, setFileName] = useState("");
  const [preview, setPreview] = useState(null); // {broker, count, rows}
  const [mode, setMode] = useState("両方（取引履歴＋保有銘柄更新）");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);

  const onFile = (e) => {
    const f = e.target.files?.[0];
    setPreview(null);
    setMsg(null);
    if (!f) return;
    setFileName(f.name);
    const reader = new FileReader();
    reader.onload = async () => {
      const b64 = String(reader.result).split(",")[1];
      setFileB64(b64);
      setBusy(true);
      try {
        const p = await apiPost("/api/transactions/import/preview", { content_b64: b64 });
        setPreview(p);
      } catch (err) {
        setMsg({ ok: false, text: `解析に失敗: ${err.message}` });
      } finally {
        setBusy(false);
      }
    };
    reader.readAsDataURL(f);
  };

  const execute = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await apiPost("/api/transactions/import/execute", { content_b64: fileB64, mode });
      const msgs = [];
      if (r.tx_count > 0) msgs.push(`取引履歴: ${r.tx_count}件登録`);
      if (r.upd_count > 0) msgs.push(`保有銘柄: ${r.upd_count}件更新`);
      if (r.skip_count > 0) msgs.push(`${r.skip_count}件スキップ（未登録銘柄/投信）`);
      setMsg({ ok: true, text: `✓ ${msgs.join(" / ")}` });
      setPreview(null);
      setFileB64(null);
      clearSnapshot();
      onDone();
    } catch (e) {
      setMsg({ ok: false, text: `インポートに失敗: ${e.message}` });
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h3>📂 証券会社 約定履歴CSVから取込</h3>
      <p className="caption">SBI証券・楽天証券・三菱UFJeスマート証券の約定履歴CSVを自動判別して取り込みます。</p>
      <input type="file" accept=".csv" onChange={onFile} className="fileinput" />
      {busy && <p className="caption">処理中...</p>}
      {preview && (
        <>
          <div className="alert up">🏦 <b>{preview.broker}</b> のCSVを検出 — {preview.count}件の約定データ（{fileName}）</div>
          <div className="tablewrap tight">
            <table>
              <thead>
                <tr>
                  <th className="l">約定日</th><th className="l">銘柄名</th><th className="l">銘柄コード</th>
                  <th className="l">取引種別</th><th className="l">口座区分</th><th>数量</th><th>単価</th>
                </tr>
              </thead>
              <tbody>
                {preview.rows.map((r, i) => (
                  <tr key={i}>
                    <td className="l">{r["約定日"]}</td>
                    <td className="l">{r["_name"]}</td>
                    <td className="l">{r["_code"] || "-"}</td>
                    <td className="l">{r["_取引種別"]}</td>
                    <td className="l">{r["_口座区分"]}</td>
                    <td>{fmtG4(r["_qty"])}</td>
                    <td>{fmtPrice(r["_price"] ?? 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="subtabs" style={{ marginTop: "0.6rem" }}>
            {["取引履歴に登録", "保有銘柄の数量を更新", "両方（取引履歴＋保有銘柄更新）"].map((m) => (
              <button key={m} className={mode === m ? "active" : ""} onClick={() => setMode(m)}>{m}</button>
            ))}
          </div>
          <button className="ghost wide" onClick={execute} disabled={busy}>✅ インポート実行</button>
        </>
      )}
      {msg && <div className={`alert ${msg.ok ? "up" : "down"}`}>{msg.text}</div>}
    </>
  );
}

function TxList({ transactions }) {
  const stats = useMemo(() => {
    const buys = transactions.filter((t) => ["買い増し", "新規購入"].includes(t["取引種別"]));
    const sells = transactions.filter((t) => t["取引種別"] === "売却");
    const totalPnl = transactions.reduce((s, t) => s + (t["損益確定(円)"] || 0), 0);
    return { buys: buys.length, sells: sells.length, totalPnl };
  }, [transactions]);

  const sorted = useMemo(
    () => [...transactions].sort((a, b) => String(b["日付"]).localeCompare(String(a["日付"]))),
    [transactions]
  );

  const download = () => {
    if (!transactions.length) return;
    const cols = Object.keys(transactions[0]);
    const esc = (v) => {
      const s = String(v ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const csv = [cols.join(","), ...transactions.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
    const blob = new Blob(["﻿" + csv], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    const d = new Date();
    a.download = `transactions_${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}.csv`;
    a.click();
    URL.revokeObjectURL(a.href);
  };

  if (!transactions.length) return <p className="status">取引を記録すると履歴が表示されます。</p>;

  const cols = Object.keys(transactions[0]);

  return (
    <>
      <div className="grid3" style={{ marginBottom: "0.8rem" }}>
        <div className="scard"><h4>買い付け回数</h4><p className="mv">{stats.buys}<span>回</span></p></div>
        <div className="scard"><h4>売却回数</h4><p className="mv">{stats.sells}<span>回</span></p></div>
        <div className="scard">
          <h4>確定損益合計</h4>
          <p className={`mv ${pnlCls(stats.totalPnl)}`}>{signedYenInt(stats.totalPnl).replace("円", "")}<span>円</span></p>
        </div>
      </div>
      <div className="tablewrap tight" style={{ maxHeight: 500 }}>
        <table>
          <thead>
            <tr>{cols.map((c) => <th key={c} className={["日付", "銘柄コード", "銘柄名", "市場", "取引種別", "口座", "口座区分"].includes(c) ? "l" : ""}>{c}</th>)}</tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => (
              <tr key={i}>
                {cols.map((c) => {
                  let v = r[c];
                  if (c === "損益確定(円)") v = fmtPnl(v || 0);
                  else if (c === "単価(円)") v = fmtPrice(v || 0);
                  else if (c === "数量") v = fmtG4(v);
                  return <td key={c} className={["日付", "銘柄コード", "銘柄名", "市場", "取引種別", "口座", "口座区分"].includes(c) ? "l" : ""}>{v ?? "-"}</td>;
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <button className="ghost wide" style={{ marginTop: "0.6rem" }} onClick={download}>
        📥 取引履歴をCSVでダウンロード
      </button>
    </>
  );
}

export default function Transactions() {
  const { snap, error, loading, reload } = useSnapshot();
  const [state, setState] = useState(null);
  const [txError, setTxError] = useState("");

  const loadTx = () => {
    apiFetch("/api/transactions")
      .then(setState)
      .catch((e) => setTxError(e.message));
  };

  useEffect(loadTx, []);

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  return (
    <main>
      <TopBar loadedAt={snap.loadedAt} loading={loading} onReload={reload} />
      <h3 style={{ borderTop: "none", paddingTop: 0 }}>📒 取引履歴</h3>
      {txError && <div className="alert down">エラー: {txError}</div>}
      {!state ? (
        <p className="status">読み込み中...</p>
      ) : (
        <>
          <TxForm state={state} onDone={loadTx} />
          <CsvImport onDone={loadTx} />
          <h3>📋 取引履歴一覧</h3>
          <TxList transactions={state.transactions} />
        </>
      )}
    </main>
  );
}
