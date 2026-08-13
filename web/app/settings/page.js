"use client";

import { useEffect, useState } from "react";
import TopBar from "../../components/TopBar";
import { useSnapshot } from "../../lib/useSnapshot";
import { apiGet, apiPut, clearSnapshot } from "../../lib/api";
import { fmtInt } from "../../lib/format";

export default function Settings() {
  const { snap, error, loading, reload } = useSnapshot();
  const [s, setS] = useState(null);
  const [loadError, setLoadError] = useState("");
  const [jpy, setJpy] = useState(50);
  const [usd, setUsd] = useState(50);
  const [cash, setCash] = useState(0);
  const [msg, setMsg] = useState(null); // {ok, text}
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    apiGet("/api/settings")
      .then((d) => {
        setS(d);
        setJpy(d.target_jpy_pct);
        setUsd(d.target_usd_pct);
        setCash(d.cash_balance_jpy);
      })
      .catch((e) => setLoadError(e.message));
  }, []);

  const total = Number(jpy) + Number(usd);
  const totalOk = Math.abs(total - 100) < 1e-9;

  const save = async (payload, label) => {
    setBusy(true);
    setMsg(null);
    try {
      const d = await apiPut("/api/settings", payload);
      setS(d);
      clearSnapshot(); // 保存値はスナップショット(targets/cash)に効くため再取得させる
      setMsg({ ok: true, text: `${label}を保存したわ。` });
    } catch (e) {
      setMsg({ ok: false, text: `保存に失敗: ${e.message}` });
    } finally {
      setBusy(false);
    }
  };

  if (loading && !snap) return <main><p className="status">市場データを取得中...</p></main>;
  if (error && !snap) return <main><p className="status">エラー: {error}</p></main>;
  if (!snap) return null;

  const header = <TopBar loadedAt={snap.loadedAt} loading={loading} onReload={reload} />;
  if (loadError) return <main>{header}<div className="alert down">エラー: {loadError}</div></main>;
  if (!s) return <main>{header}<p className="status">読み込み中...</p></main>;

  return (
    <main>
      {header}
      <h3 style={{ borderTop: "none", paddingTop: 0 }}>⚙️ 設定</h3>
      <p className="caption">
        Google Sheets の Settings シートに保存され、Streamlit版とも共有されるわ。
      </p>

      {msg && <div className={`alert ${msg.ok ? "up" : "down"}`}>{msg.text}</div>}

      <h4 className="subhead">🎯 目標通貨配分</h4>
      <div className="paramrow">
        <label className="inlineinput" style={{ margin: 0 }}>
          JPY 目標 (%)
          <input type="number" min="0" max="100" step="5" value={jpy}
            onChange={(e) => setJpy(Number(e.target.value))} />
        </label>
        <label className="inlineinput" style={{ margin: 0 }}>
          USD 目標 (%)
          <input type="number" min="0" max="100" step="5" value={usd}
            onChange={(e) => setUsd(Number(e.target.value))} />
        </label>
        <div style={{ alignSelf: "center" }}>
          <p className="sv">
            合計: {total.toFixed(1)}%
            {!totalOk && `（目標差 ${total - 100 >= 0 ? "+" : ""}${(total - 100).toFixed(1)}%）`}
          </p>
          {!totalOk && <p className="sv" style={{ color: "var(--gold)" }}>⚠️ 合計を100%にしてね</p>}
        </div>
      </div>
      <button
        className="ghost wide"
        disabled={!totalOk || busy}
        onClick={() => save({ target_jpy_pct: Number(jpy), target_usd_pct: Number(usd) }, "目標通貨配分")}
      >
        💾 保存
      </button>
      <p className="caption">現在の保存値: JPY {s.target_jpy_pct}% / USD {s.target_usd_pct}%</p>

      <h4 className="subhead">💰 現金残高</h4>
      <div className="paramrow">
        <label className="inlineinput" style={{ margin: 0 }}>
          現金残高 (円)
          <input type="number" min="0" max="10000000000" step="10000" value={cash}
            onChange={(e) => setCash(Number(e.target.value))} />
        </label>
        <p className="sv" style={{ alignSelf: "center" }}>
          通貨配分タブの実質JPY比率に合算される。保有シートには載らないわ
        </p>
      </div>
      <button
        className="ghost wide"
        disabled={busy}
        onClick={() => save({ cash_balance_jpy: Number(cash) }, "現金残高")}
      >
        💾 現金を保存
      </button>
      <p className="caption">現在の保存値: ¥{fmtInt(s.cash_balance_jpy)}</p>

      <h3>📜 利用規約・プライバシーポリシー</h3>
      <details className="expander">
        <summary>内容を表示</summary>
        <div className="md">
          <p><b>利用規約（β版）</b></p>
          <ul className="readme">
            <li>本アプリ（FORCE CAPITAL）は個人投資家向けのポートフォリオ管理ツールの<b>β版</b>です</li>
            <li>本アプリは<b>投資助言・勧誘を行うものではありません</b>。投資判断は自己責任でお願いします</li>
            <li>表示される価格情報は yfinance / J-Quants 等の外部サービスから取得しており、<b>正確性・即時性を保証しません</b></li>
            <li>本アプリの利用により発生した損害について、運営者は一切の責任を負いません</li>
            <li>運営者は予告なくサービスを変更・停止する場合があります</li>
          </ul>
          <p><b>プライバシーポリシー（β版）</b></p>
          <ul className="readme">
            <li>収集する情報: ユーザー名、ログイン時刻、ポートフォリオデータ（銘柄・数量・単価等）、メールアドレス（Google OAuth利用時）</li>
            <li>利用目的: 本アプリの機能提供およびサービス改善</li>
            <li>データ保管: ユーザーデータは Google Sheets に暗号化通信で保存されます</li>
            <li>第三者提供: 価格情報取得のため yfinance / J-Quants / Google Sheets / Anthropic API に銘柄コード等を送信します</li>
            <li>削除要求: 退会・データ削除の希望は運営者にご連絡ください</li>
          </ul>
          <p className="caption">最終更新: 2026-04-06</p>
        </div>
      </details>
    </main>
  );
}
