"use client";

import { useEffect, useState } from "react";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiDelete, apiGet, apiPost, apiPut, clearSnapshot } from "../../lib/api";
import { fmtNum } from "../../lib/format";

// 通貨の既定(data._fill_missing_columns の市場→通貨と同一)。手動で上書き可
const USD_MARKETS = ["米国株", "暗号資産", "コモディティ"];
const MONTHS = Array.from({ length: 12 }, (_, i) => i + 1);

// フォーム状態の初期値(旧 tab_portfolio 追加フォームの既定値と同一: 保有数100・他0)
const EMPTY = {
  銘柄コード: "",
  銘柄名: "",
  市場: "日本株",
  通貨: "JPY",
  保有株数: 100,
  取得単価: 0,
  口座: "SBI証券",
  口座区分: "特定口座",
  "手動配当利回り(%)": 0,
  配当月: [],
  "年間配当金(円/株)": 0,
  取得時為替: 0,
  手動現在値: 0,
  取得日: "",
};

// API の生行 → フォーム状態(配当月 "3,9" → [3, 9])
function toForm(row) {
  const f = { ...EMPTY };
  for (const k of Object.keys(EMPTY)) if (row[k] != null && row[k] !== "") f[k] = row[k];
  f.配当月 = String(row["配当月"] ?? "")
    .split(",")
    .map((x) => x.trim())
    .filter((x) => /^\d+$/.test(x))
    .map(Number);
  return f;
}

// フォーム状態 → API の fields(数値は Number 化、配当月は配列のまま送る)
function toFields(f) {
  const out = { ...f };
  for (const k of ["保有株数", "取得単価", "手動配当利回り(%)", "年間配当金(円/株)", "取得時為替", "手動現在値"]) {
    out[k] = Number(f[k] || 0);
  }
  return out;
}

function HoldingForm({ options, initial, mode, busy, onSubmit, onCancel }) {
  const [f, setF] = useState(initial);
  const [lookupMsg, setLookupMsg] = useState("");
  const [looking, setLooking] = useState(false);
  useEffect(() => {
    setF(initial);
    setLookupMsg("");
  }, [initial]);

  const set = (k, v) => setF((s) => ({ ...s, [k]: v }));
  const setMarket = (m) => setF((s) => ({ ...s, 市場: m, 通貨: USD_MARKETS.includes(m) ? "USD" : "JPY" }));
  const toggleMonth = (m) =>
    set("配当月", f.配当月.includes(m) ? f.配当月.filter((x) => x !== m) : [...f.配当月, m].sort((a, b) => a - b));

  const canLookup = ["日本株", "米国株"].includes(f.市場) && f.銘柄コード.trim() !== "";
  const lookup = async () => {
    setLooking(true);
    setLookupMsg("");
    try {
      const r = await apiGet(
        `/api/holdings/lookup?code=${encodeURIComponent(f.銘柄コード.trim())}&market=${encodeURIComponent(f.市場)}`
      );
      if (r.name) {
        set("銘柄名", r.name);
        setLookupMsg(`✓ ${r.name}`);
      } else {
        setLookupMsg("銘柄名を取得できなかったわ。手入力してね");
      }
    } catch (e) {
      setLookupMsg(`取得失敗: ${e.message}`);
    } finally {
      setLooking(false);
    }
  };

  const num = (k, extra = {}) => (
    <label className="inlineinput" style={{ margin: 0 }}>
      {k}
      <input
        type="number"
        min="0"
        step="any"
        value={f[k]}
        onChange={(e) => set(k, e.target.value)}
        {...extra}
      />
    </label>
  );
  const sel = (k, opts, onChange) => (
    <label className="inlineinput" style={{ margin: 0 }}>
      {k}
      <select value={f[k]} onChange={(e) => (onChange ? onChange(e.target.value) : set(k, e.target.value))}>
        {opts.map((o) => (
          <option key={o}>{o}</option>
        ))}
      </select>
    </label>
  );

  return (
    <>
      <div className="paramrow" style={{ marginTop: "0.6rem" }}>
        {sel("市場", options.市場, setMarket)}
        {sel("通貨", options.通貨)}
        <label className="inlineinput" style={{ margin: 0 }}>
          証券コード
          <input
            type="text"
            value={f.銘柄コード}
            onChange={(e) => set("銘柄コード", e.target.value)}
            placeholder="例: 7203 / VT / オルカン"
          />
        </label>
        {/* ボタンを含むため label ではなく div(label だとボタン文言が入力欄の読み上げ名に混ざる) */}
        <div className="inlineinput" style={{ margin: 0, flex: 1 }}>
          銘柄名
          <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.25rem" }}>
            <input
              type="text"
              aria-label="銘柄名"
              value={f.銘柄名}
              onChange={(e) => set("銘柄名", e.target.value)}
              placeholder="空欄なら追加時に自動取得(日本株/米国株)"
              style={{ marginTop: 0, width: "100%", minWidth: 220 }}
            />
            <button className="ghost" type="button" onClick={lookup} disabled={!canLookup || looking || busy}>
              {looking ? "取得中..." : "🔍 名称取得"}
            </button>
          </div>
          {lookupMsg && <span className="sv">{lookupMsg}</span>}
        </div>
      </div>
      <div className="paramrow">
        {num("保有株数", { min: mode === "add" ? "0.0001" : "0" })}
        {num("取得単価")}
        {num("年間配当金(円/株)")}
        {sel("口座", options.口座)}
        {sel("口座区分", options.口座区分)}
      </div>
      <div className="paramrow">
        <div className="inlineinput" style={{ margin: 0, flexBasis: "100%" }}>
          配当月
          <div role="group" aria-label="配当月" style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap", marginTop: "0.3rem" }}>
            {MONTHS.map((m) => (
              <button
                key={m}
                type="button"
                className={`pick ${f.配当月.includes(m) ? "on" : ""}`}
                aria-pressed={f.配当月.includes(m)}
                onClick={() => toggleMonth(m)}
              >
                {m}月
              </button>
            ))}
          </div>
        </div>
        {num("取得時為替", { max: "1000", step: "0.1" })}
        <label className="inlineinput" style={{ margin: 0 }}>
          取得日
          <input type="text" value={f.取得日} onChange={(e) => set("取得日", e.target.value)} placeholder="YYYY/MM/DD(任意)" />
        </label>
        {num("手動現在値")}
        {num("手動配当利回り(%)", { max: "100", step: "0.01" })}
      </div>
      <div style={{ display: "flex", gap: "0.6rem" }}>
        <button className="ghost wide" onClick={() => onSubmit(toFields(f))} disabled={busy || !f.銘柄コード.trim()}>
          {busy ? "保存中..." : mode === "add" ? "＋ 追加" : "💾 変更を保存"}
        </button>
        {mode === "edit" && (
          <button className="ghost" onClick={onCancel} disabled={busy}>
            取消
          </button>
        )}
      </div>
    </>
  );
}

const LIST_COLS = [
  { key: "銘柄コード", label: "コード", left: true },
  { key: "銘柄名", label: "銘柄名", left: true },
  { key: "市場", label: "市場", left: true },
  { key: "通貨", label: "通貨", left: true },
  { key: "保有株数", label: "数量" },
  { key: "取得単価", label: "取得単価" },
  { key: "口座", label: "口座", left: true },
  { key: "口座区分", label: "口座区分", left: true },
  { key: "年間配当金(円/株)", label: "配当(円/株)" },
  { key: "配当月", label: "配当月", left: true },
  { key: "取得時為替", label: "取得時為替" },
  { key: "手動現在値", label: "手動現在値" },
  { key: "取得日", label: "取得日", left: true },
  { key: "最新更新日", label: "最新更新日", left: true },
];

const cellText = (v) => {
  if (v == null || v === "") return "-";
  if (typeof v === "number") return v === 0 ? "-" : fmtNum(v);
  return String(v);
};

export default function Holdings() {
  const { snap, error, loading, reload } = useSnapshot();
  const [state, setState] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [editing, setEditing] = useState(null); // 編集中の行(API生行)
  const [confirmDel, setConfirmDel] = useState(null); // 2回目クリック待ちの index
  const [msg, setMsg] = useState(null); // {ok, text}
  const [busy, setBusy] = useState(false);
  const [addKey, setAddKey] = useState(0); // 追加成功後にフォームを初期化するためのキー

  const load = () =>
    apiGet("/api/holdings")
      .then((d) => {
        setState(d);
        setLoadError("");
      })
      .catch((e) => setLoadError(e.message));
  useEffect(() => {
    load();
  }, []);

  const run = async (fn, okText) => {
    setBusy(true);
    setMsg(null);
    try {
      const r = await fn();
      setMsg({ ok: true, text: okText(r) });
      clearSnapshot(); // 保有の変更は全タブのスナップショットに効くため再取得させる
      await load();
      return true;
    } catch (e) {
      setMsg({ ok: false, text: `失敗: ${e.message}` });
      return false;
    } finally {
      setBusy(false);
    }
  };

  const onAdd = async (fields) => {
    const ok = await run(
      () => apiPost("/api/holdings", { fields }),
      (r) =>
        r.merged
          ? `✓ ${r.name} を既存保有に合算（${fmtNum(r.shares_before)} + ${fmtNum(r.shares_added)} = ${fmtNum(r.shares_after)}、平均取得単価 ${fmtNum(r.avg_price)}）`
          : `✓ ${r.name} を追加したわ`
    );
    if (ok) setAddKey((k) => k + 1);
  };
  const onUpdate = async (fields) => {
    const ok = await run(
      () => apiPut(`/api/holdings/${editing.index}`, { code: String(editing["銘柄コード"]), fields }),
      (r) => `✓ ${r.name} を更新したわ`
    );
    if (ok) setEditing(null);
  };
  const onDelete = async (row) => {
    setConfirmDel(null);
    await run(
      () => apiDelete(`/api/holdings/${row.index}?code=${encodeURIComponent(String(row["銘柄コード"]))}`),
      (r) => `✓ ${r.name} を削除したわ`
    );
    if (editing && editing.index === row.index) setEditing(null);
  };

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const header = <TopBar loadedAt={snap.loadedAt} marketFetchedAt={snap.market_fetched_at} loading={loading} onReload={reload} />;
  if (loadError) return <main>{header}<div className="alert down">エラー: {loadError}</div></main>;
  if (!state) return <main>{header}<p className="status">読み込み中...</p></main>;

  const rows = state.holdings;

  return (
    <main>
      {header}
      <h3 style={{ borderTop: "none", paddingTop: 0 }}>🗂️ 銘柄管理</h3>
      <p className="caption">
        保有シート(PortfolioData)の直接編集。同一銘柄を同じ口座・口座区分で追加すると既存行に合算され、平均取得単価を再計算するわ。
        評価額や損益はポートフォリオタブで確認して。
      </p>

      {msg && <div className={`alert ${msg.ok ? "up" : "down"}`}>{msg.text}</div>}

      {editing ? (
        <details className="expander" open>
          <summary>
            ✏️ 銘柄を修正 — {editing["銘柄コード"]} {editing["銘柄名"]} [{editing["口座"]} / {editing["口座区分"]}]
          </summary>
          <HoldingForm
            options={state.options}
            initial={toForm(editing)}
            mode="edit"
            busy={busy}
            onSubmit={onUpdate}
            onCancel={() => setEditing(null)}
          />
        </details>
      ) : (
        <details className="expander" open>
          <summary>➕ 銘柄を追加</summary>
          <HoldingForm key={addKey} options={state.options} initial={EMPTY} mode="add" busy={busy} onSubmit={onAdd} />
        </details>
      )}

      <h3>📋 保有銘柄一覧（{rows.length}行）</h3>
      {rows.length === 0 ? (
        <p className="status">保有銘柄がありません。上のフォームから追加してね。</p>
      ) : (
        <div className="tablewrap">
          <table>
            <thead>
              <tr>
                {LIST_COLS.map((c) => (
                  <th key={c.key} className={c.left ? "l" : ""}>
                    {c.label}
                  </th>
                ))}
                <th className="l">操作</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.index} className={editing && editing.index === r.index ? "selrow" : ""}>
                  {LIST_COLS.map((c) => (
                    <td key={c.key} className={c.left ? "l" : ""}>
                      {cellText(r[c.key])}
                    </td>
                  ))}
                  <td className="l" style={{ whiteSpace: "nowrap" }}>
                    <button
                      className="pick"
                      onClick={() => {
                        setConfirmDel(null);
                        setEditing(r);
                        window.scrollTo({ top: 0, behavior: "smooth" });
                      }}
                      disabled={busy}
                    >
                      編集
                    </button>{" "}
                    {confirmDel === r.index ? (
                      <>
                        <button
                          className="pick on"
                          style={{ color: "var(--down)", borderColor: "var(--down)" }}
                          onClick={() => onDelete(r)}
                          disabled={busy}
                        >
                          本当に削除
                        </button>{" "}
                        <button className="pick" onClick={() => setConfirmDel(null)} disabled={busy}>
                          取消
                        </button>
                      </>
                    ) : (
                      <button className="pick" onClick={() => setConfirmDel(r.index)} disabled={busy}>
                        削除
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="caption">
        数量は投資信託なら口数(NISA枠の集計は口数÷10,000換算)。日本株の配当は空欄でも J-Quants の予想DPSが自動で入るわ(手入力が常に優先)。
      </p>
    </main>
  );
}
