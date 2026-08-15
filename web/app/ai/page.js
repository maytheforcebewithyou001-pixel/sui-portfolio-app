"use client";

import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiFetch, apiPost, apiPut } from "../../lib/api";

// tab_ai.py の時刻表示("x.x時間前"/"x日前")と同一
function relTime(dtStr) {
  try {
    const m = dtStr.match(/^(\d{4})\/(\d{2})\/(\d{2}) (\d{2}):(\d{2})$/);
    if (!m) return "";
    const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
    const ha = (Date.now() - d.getTime()) / 3600000;
    return ha < 48 ? `${ha.toFixed(1)}時間前` : `${Math.round(ha / 24)}日前`;
  } catch {
    return "";
  }
}

function withinHours(dtStr, hours) {
  const m = dtStr?.match(/^(\d{4})\/(\d{2})\/(\d{2}) (\d{2}):(\d{2})$/);
  if (!m) return false;
  const d = new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  return (Date.now() - d.getTime()) / 3600000 < hours;
}

function ReviewTab() {
  const [state, setState] = useState(null);
  const [error, setError] = useState("");
  const [memo, setMemo] = useState("");
  const [memoSaved, setMemoSaved] = useState(false);
  const [confirmRegen, setConfirmRegen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [genResult, setGenResult] = useState(null); // {dt,text,truncated}

  useEffect(() => {
    apiFetch("/api/ai/review")
      .then((s) => {
        setState(s);
        setMemo(s.policy_memo ?? "");
      })
      .catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="status">エラー: {error}</p>;
  if (!state) return <p className="status">読み込み中...</p>;

  const dt = genResult?.dt ?? state.review_dt;
  const text = genResult?.text ?? state.review_text;
  const truncated = genResult?.truncated ?? false;
  const needConfirm = dt && withinHours(dt, 24) && !confirmRegen;

  const generate = async () => {
    setGenerating(true);
    setError("");
    try {
      const res = await apiPost("/api/ai/review/generate");
      setGenResult(res);
      setConfirmRegen(false);
      const s = await apiFetch("/api/ai/review");
      setState(s);
    } catch (e) {
      setError(`生成に失敗しました: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  };

  const saveMemo = async () => {
    try {
      await apiPut("/api/ai/policy-memo", { memo });
      setMemoSaved(true);
      setTimeout(() => setMemoSaved(false), 4000);
    } catch (e) {
      setError(`メモ保存に失敗: ${e.message}`);
    }
  };

  // 履歴(最新は上に表示済みなので除外・新しい順)
  const past = (state.history ?? []).slice(0, -1).reverse();

  return (
    <>
      <h3>🤖 Claudeによるポートフォリオ総評</h3>

      {text && dt && (
        <div className="aireport">
          <div className="ttl">🤖 Claude分析レポート</div>
          <div className="ts">{dt}時点（{relTime(dt)}）</div>
          <div className="md">
            <ReactMarkdown>{text}</ReactMarkdown>
          </div>
          {truncated && (
            <div className="alert warn">⚠ 出力が上限に達し、レポートが途中で打ち切られた可能性があります。再生成してください。</div>
          )}
          <p className="caption">⚠ AIによる参考情報。投資助言ではありません。</p>
        </div>
      )}

      <details className="expander">
        <summary>📝 運用方針メモ（総評の前提として毎回AIに渡す既決事項）</summary>
        <p className="caption">売却計画・例外保有・戦略方針など決着済みの事項を書いておくと、AIが同じ論点を新規の問題として蒸し返さなくなります。</p>
        <textarea
          className="memoarea"
          value={memo}
          onChange={(e) => setMemo(e.target.value)}
          rows={10}
          placeholder={"例:\n- 2498は8月の規制解禁後に1,800株売却を確定済み（閾値3,050円）\n- 4755楽天は通信費還元目的の例外保有。損切り提案は不要"}
        />
        <button className="ghost" onClick={saveMemo}>💾 メモを保存</button>
        {memoSaved && <span className="savedmark">保存しました。次回の総評生成から反映されます。</span>}
      </details>

      {generating ? (
        <div className="alert warn">⏳ Claudeが分析中...（20〜30秒）</div>
      ) : needConfirm ? (
        <>
          <div className="alert warn">⏱ {relTime(dt)}に生成済み。再生成でAPIクレジット消費。</div>
          <button className="ghost wide" onClick={() => setConfirmRegen(true)}>🔄 それでも再生成する</button>
        </>
      ) : (
        <button className="ghost wide" onClick={generate}>
          {text ? "🔄 再生成" : "📝 AI総評を生成"}
        </button>
      )}

      {state.summary_text && (
        <details className="expander" style={{ marginTop: "0.8rem" }}>
          <summary>📄 送信データプレビュー</summary>
          <pre className="pre">{state.summary_text}</pre>
        </details>
      )}

      {past.length > 0 && (
        <>
          <h3>📚 過去の分析履歴</h3>
          {past.map((h) => (
            <details key={h.dt} className="expander">
              <summary>📋 {h.dt}</summary>
              <div className="md"><ReactMarkdown>{h.text}</ReactMarkdown></div>
            </details>
          ))}
        </>
      )}
    </>
  );
}

// ライフプランのフォーム既定値(tab_ai._render_lifeplan と同一)
function lifeplanDefaults(taAll) {
  return {
    age: 40, hasSpouse: true, spouseAge: 36, incomeType: "手取り", income: 800, retireAge: 65,
    nChildren: 2, childrenAges: "3, 0", eduPolicy: "未定（標準）",
    curAsset: taAll > 0 ? Math.round(taAll / 10000) : 3000,
    monthlyExp: 35, housing: "持ち家（ローン完済）", housingDetail: 0,
    pension: "AIに推定させる", monthlyInvest: 7, annualLump: 0, expReturn: 4.0, note: "",
  };
}

function LifeplanTab({ taAll }) {
  const [f, setF] = useState(null);
  const [history, setHistory] = useState(null);
  const [error, setError] = useState("");
  const [generating, setGenerating] = useState(false);
  const [genResult, setGenResult] = useState(null);

  useEffect(() => {
    if (f === null && taAll !== null) setF(lifeplanDefaults(taAll));
  }, [taAll, f]);

  useEffect(() => {
    apiFetch("/api/ai/lifeplan")
      .then((s) => setHistory(s.history ?? []))
      .catch((e) => setError(e.message));
  }, []);

  const latest = useMemo(() => {
    if (genResult) return { dt: genResult.dt, text: genResult.text, truncated: genResult.truncated };
    if (history?.length) {
      const h = history[history.length - 1];
      return { dt: h.dt, text: h.text, truncated: false };
    }
    return null;
  }, [genResult, history]);

  if (error) return <p className="status">エラー: {error}</p>;
  if (!f || history === null) return <p className="status">読み込み中...</p>;

  const set = (k) => (v) => setF({ ...f, [k]: v });
  const submit = async () => {
    // tab_ai.py:283-300 と同一の整形
    const inputs = {
      本人年齢: `${f.age}歳`,
      配偶者: f.hasSpouse ? `${f.spouseAge}歳` : "なし",
      世帯年収: `${f.income}万円（${f.incomeType}）`,
      退職予定年齢: `${f.retireAge}歳`,
      子どもの数: `${f.nChildren}人`,
      子の年齢: f.nChildren > 0 ? f.childrenAges : "なし",
      想定進路: f.eduPolicy,
      現在の金融資産: `${f.curAsset}万円`,
      "毎月の生活費(教育費除く)": `${f.monthlyExp}万円`,
      住居: f.housing,
      "住宅ローン残/月額家賃": `${f.housingDetail}万円`,
      年金見込み: f.pension,
      今後の月次積立額: `${f.monthlyInvest}万円/月`,
      年初の一括投資額: `${f.annualLump}万円/年`,
      想定運用利回り: `年${f.expReturn}%`,
      補足: f.note.trim() || "なし",
    };
    setGenerating(true);
    setError("");
    try {
      const res = await apiPost("/api/ai/lifeplan/generate", { inputs });
      setGenResult(res);
      const s = await apiFetch("/api/ai/lifeplan");
      setHistory(s.history ?? []);
    } catch (e) {
      setError(`試算に失敗しました: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  };

  const Num = ({ label, k, step = 1, min = 0, max = 1000000 }) => (
    <label className="inlineinput" style={{ margin: 0 }}>
      {label}
      <input type="number" value={f[k]} step={step} min={min} max={max}
        onChange={(e) => set(k)(Number(e.target.value))} />
    </label>
  );
  const Sel = ({ label, k, options }) => (
    <label className="inlineinput" style={{ margin: 0 }}>
      {label}
      <select value={f[k]} onChange={(e) => set(k)(e.target.value)}>
        {options.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </label>
  );

  return (
    <>
      <h3>👨‍👩‍👧‍👦 ライフプラン試算</h3>
      <p className="caption">家族構成・年収・進路などから、教育費・老後資金を含む将来必要資産をAIが試算し、解決案を提案します。</p>

      <div className="paramrow">
        <Num label="本人の年齢" k="age" min={18} max={95} />
        <label className="inlineinput" style={{ margin: 0 }}>
          配偶者あり
          <input type="checkbox" className="chk" checked={f.hasSpouse} onChange={(e) => set("hasSpouse")(e.target.checked)} />
        </label>
        {f.hasSpouse && <Num label="配偶者の年齢" k="spouseAge" min={18} max={95} />}
        <Sel label="世帯年収の種別" k="incomeType" options={["手取り", "額面"]} />
        <Num label="世帯年収（万円）" k="income" step={50} />
        <Num label="退職予定年齢" k="retireAge" min={40} max={95} />
      </div>
      <div className="paramrow">
        <Num label="子どもの数" k="nChildren" min={0} max={10} />
        <label className="inlineinput" style={{ margin: 0 }}>
          子の年齢（カンマ区切り）
          <input type="text" value={f.childrenAges} onChange={(e) => set("childrenAges")(e.target.value)} />
        </label>
        <Sel label="想定進路" k="eduPolicy" options={["未定（標準）", "オール公立", "公立中心", "私立中心", "オール私立（含む医歯薬）"]} />
        <Num label="現在の金融資産（万円）" k="curAsset" step={100} />
        <Num label="毎月の生活費（万円・教育費除く）" k="monthlyExp" />
        <Sel label="住居" k="housing" options={["持ち家（ローン完済）", "持ち家（ローン返済中）", "賃貸"]} />
      </div>
      <div className="paramrow">
        <Num label="住宅ローン残高 or 月額家賃（万円）" k="housingDetail" />
        <label className="inlineinput" style={{ margin: 0 }}>
          年金見込み（世帯・月額万円）
          <input type="text" value={f.pension} onChange={(e) => set("pension")(e.target.value)} />
        </label>
        <Num label="今後の月次積立額（万円/月）" k="monthlyInvest" />
        <Num label="年初の一括投資額（万円/年）" k="annualLump" />
        <Num label="想定運用利回り（年%）" k="expReturn" step={0.5} max={15} />
      </div>
      <div className="paramrow">
        <label className="inlineinput" style={{ margin: 0, flex: 1 }}>
          補足・特記事項（任意）
          <textarea className="memoarea" rows={3} value={f.note}
            placeholder="介護予定、相続・贈与予定、転職・独立予定、車・住宅の買い替え予定 など"
            onChange={(e) => set("note")(e.target.value)} />
        </label>
      </div>

      {generating ? (
        <div className="alert warn">⏳ Claudeがライフプランを試算中...（40〜60秒）</div>
      ) : (
        <button className="ghost wide" onClick={submit}>🧮 将来必要資産を試算する</button>
      )}

      {latest?.text && (
        <div className="aireport" style={{ marginTop: "1rem" }}>
          <div className="ttl">🧮 試算レポート（{latest.dt}）</div>
          <div className="md"><ReactMarkdown>{latest.text}</ReactMarkdown></div>
          {latest.truncated && (
            <div className="alert warn">⚠ 出力が上限に達し、レポートが途中で打ち切られた可能性があります。補足欄を短くする・進路前提を絞るなど条件をシンプルにして再試行してください。</div>
          )}
          <p className="caption">⚠ AIによる概算の参考情報です。投資助言・税務助言ではありません。前提条件により結果は大きく変動します。</p>
        </div>
      )}

      {history.length > 1 && (
        <>
          <h3>📚 過去の試算履歴</h3>
          {history.slice(0, -1).reverse().map((h) => {
            let cond = null;
            try { cond = JSON.parse(h.inputs); } catch { /* 表示のみ */ }
            return (
              <details key={h.dt} className="expander">
                <summary>📋 {h.dt}</summary>
                {cond && (
                  <p className="caption">
                    入力条件: {Object.entries(cond).map(([k, v]) => `${k}=${v}`).join(" / ")}
                  </p>
                )}
                <div className="md"><ReactMarkdown>{h.text}</ReactMarkdown></div>
              </details>
            );
          })}
        </>
      )}
    </>
  );
}

export default function AI() {
  const { snap, error, loading, reload } = useSnapshot();
  const [sub, setSub] = useState("review");

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const taAll = snap.totals.total_asset_all ?? snap.totals.total_asset ?? 0;

  return (
    <main>
      <TopBar loadedAt={snap.loadedAt} marketFetchedAt={snap.market_fetched_at} loading={loading} onReload={reload} />
      <div className="subtabs" style={{ marginTop: "0.4rem" }}>
        <button className={sub === "review" ? "active" : ""} onClick={() => setSub("review")}>🤖 ポートフォリオ総評</button>
        <button className={sub === "life" ? "active" : ""} onClick={() => setSub("life")}>👨‍👩‍👧‍👦 ライフプラン試算</button>
      </div>
      {sub === "review" ? <ReviewTab /> : <LifeplanTab taAll={taAll} />}
    </main>
  );
}
