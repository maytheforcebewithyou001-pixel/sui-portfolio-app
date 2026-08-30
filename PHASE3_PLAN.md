# FORCE CAPITAL Phase 3 実行計画 — 技術刷新版

作成: 2026-08-13 / 前提: HANDOFF.md(4/9)・PHASE2_PLAN.md(7/2)

---

## 0. 位置づけ — 原Phase 3構想との差分

HANDOFF.md の Phase 3 構想は「商用化」前提だった。本計画は目的を**技術刷新**に再定義する。

| 項目 | 原構想(HANDOFF §Phase 3) | 本計画 |
|---|---|---|
| 目的 | 商用化(月額サブスク) | **Streamlitの限界からの脱却**(速度/UI/Cloud依存) |
| 決済(Stripe) | あり | **落とす** |
| 認証 | Supabase Auth / Clerk | 単一ユーザー簡易認証(既存bcrypt流用) |
| DB | Supabase Postgres | **Google Sheets継続**(§2参照) |
| 法務(投資助言業) | 要専門家確認 | 個人用のため**対象外** |
| PHASE2_PLAN §2 ゲート判定 | Go判定が前提 | **適用外**(商用化しないため。β運用・計測は本計画と独立に判断) |

将来商用化する場合は、この刷新後スタックの上で改めて原構想の落とした要素を積む。

## 1. 移行先アーキテクチャ

| 層 | 現状 | 移行先 | 根拠 |
|---|---|---|---|
| フロント | Streamlit | **Next.js** (Vercel 無料枠) | 全画面再実行の廃止=速度問題の根本解決。UI自由度 |
| バック | Streamlit内蔵 | **FastAPI** (Cloud Run) | calc.py / data.py / market.py / jquants.py をほぼ無改修で再利用。scale-to-zero で常時無料圏。keep-alive ハック廃止 |
| データ | Google Sheets | Google Sheets 継続 | §2 |
| 認証 | bcrypt + TOTP + Google OAuth | 単一ユーザー bcrypt(+必要ならTOTP) | 個人用に重装備不要。検証ロジックは既存流用 |
| ホスティング | Streamlit Community Cloud | Vercel + Cloud Run(既存GCPプロジェクト `wide-maxim-491005-q9` 流用) | 依存脱却。スリープなし |

## 2. Google Sheets を継続する理由（Supabase移行の見送り）

1. **エコシステムの正**: 保有シートは資産管理全体の source of truth。株価ウィジェット(tools/sheet_portfolio.py)・portfolio_live.py・GAS株価が直接ぶら下がっており、DB移行はこれら周辺ツール全部の連鎖改修を強いる。
2. **計算資産の温存**: calc.py + test_calc.py(NISA口数÷10,000換算・実質USD集計等)が Python のまま生きる。TSへの計算エンジン書き直しは検証コスト大でバグ導入リスクだけがある。
3. **可逆性**: 商用化判断が立った時点で data.py の裏を Postgres に差し替えれば良い。抽象化境界(data.py)は既にある。

## 3. タブ棚卸し（現10タブの移植方針）

P3-2 の移植順は利用頻度順。着手時に本表を確定する。

| タブ | 移植 | 備考 |
|---|---|---|
| tab_portfolio (ポートフォリオ) | ◎ 最優先 | メイン画面(評価額ヘッダー+保有一覧+アラート)と一体で最初に |
| tab_analysis (分析) | ○ | ベンチマーク比較・α可視化含む |
| tab_currency (通貨配分) | ○ | 実質JPY計算・現金合算 |
| tab_dividend (配当) | ○ | |
| tab_simulation (シミュレーション) | ○ | |
| tab_ai (AI総評) | ○ | 免責表示・運用方針メモ注入を維持 |
| tab_transaction (取引履歴) | ○ | CSVインポート(SBI/楽天/三菱UFJ)含む |
| tab_market (世界指標) | △ | 利用頻度次第で後回し/縮小可 |
| tab_rank (ランク) | △ | 同上 |
| tab_admin (管理者) | × 廃止 | マルチユーザー運用機能のため単一ユーザー化で不要。CSVバックアップ機能のみAPI側に残す |

## 4. 段階移行（各段階完了時に報告→承認）

### P3-1: FastAPI化
- data.py / calc.py / market.py / jquants.py を FastAPI エンドポイントに載せる(ロジック無改修)
- 認証: 単一ユーザー bcrypt トークン方式
- pytest(test_calc.py)維持 + APIレイヤのテスト追加
- ローカルで Streamlit 版と同一数値を返すことを突合確認

### P3-2: Next.js UI
- まずメイン画面: 評価額ヘッダー+保有一覧+大幅変動/集中リスクアラート
- 以降 §3 の優先順でタブを移植。1タブ移植ごとに Streamlit 版と表示数値を突合

### P3-3: デプロイ
- Cloud Run(FastAPI、scale-to-zero) + Vercel(Next.js)
- Secrets: Streamlit Cloud Secrets → Cloud Run 環境変数/Secret Manager へ移設
- GCPサービスアカウントは既存を流用(90日キーローテ運用継続)

### P3-4: 並行運用→切替 ✅ 完了(2026-08-30 退役実施)
- 新旧を並行運用し、日次で評価額・損益・配当の3点一致を確認(最低2週間) — 実施済み
- 2026-08-30: Streamlit版(app.py/style.py/tabs/)削除・keep-alive ワークフロー(GHA)削除・
  共有関数を ai_review.py/investor_flow.py/fin_view.py/transactions.py へ切り出し・
  streamlit依存を requirements から除去。FundHistory記録は日次Job、減配/決算アラートは
  日次3点チェックへ移植。残: Streamlit Community Cloud 側のアプリ削除(手動)
- HANDOFF.md はヘッダーで退役を明記(歴史的記録として温存)

## 5. リスク登録簿

| リスク | 影響 | 対策 |
|---|---|---|
| 新旧で計算結果が食い違う | 資産判断を誤る | ロジック無改修方針+P3-1/P3-2/P3-4 の三重突合。calc.py に触れない |
| Cloud Run コールドスタート | 初回表示が遅い | min-instances=0 でまず運用、体感不満なら =1(月数百円)へ |
| Sheets APIクォータ | 表示失敗 | 単一ユーザーのため現行TTLキャッシュ移植で十分 |
| 移行中の二重メンテ | 開発負荷 | 並行運用期間中の機能追加は凍結。バグ修正のみ両系に適用 |
| Secrets移設ミス | 起動不能/漏洩 | 移設前に一覧表を作り、キー単位でチェック。値はチャットに貼らない |

## 6. 非スコープ（明示）

- Stripe決済・マルチテナント化・投資助言業の法務確認(商用化時に別計画)
- Supabase等へのDB移行(data.py 境界の裏差し替えとして将来対応可)
- β運用・PHASE2_PLAN のゲート判定(本計画と独立。やるなら Streamlit 版でなく刷新後に)
