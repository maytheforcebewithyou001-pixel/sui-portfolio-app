"""api/ (Phase 3 P3-1) のユニットテスト — 全てオフライン(外部通信なし)
実行: python -m pytest test_api.py -v
エンドポイントテストは httpx 必須(requirements-api.txt)。未導入時はskip。
"""
import importlib.util

import bcrypt
import pandas as pd
import pytest

HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None
requires_client = pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx未導入(requirements-api.txt参照)")

# テスト用bcryptハッシュ(rounds=4で高速化。本番はデフォルト12)
TEST_PASSWORD = "testpass"
TEST_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("FC_TOKEN_SECRET", "test-secret-key")
    monkeypatch.setenv("FC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("FC_AUTH_PASSWORD_HASH", TEST_HASH)


class TestAuth:
    def test_password_ok(self, auth_env):
        from api import auth
        assert auth.verify_password("admin", TEST_PASSWORD) is True

    def test_password_wrong(self, auth_env):
        from api import auth
        assert auth.verify_password("admin", "wrong") is False

    def test_username_wrong(self, auth_env):
        from api import auth
        assert auth.verify_password("someone", TEST_PASSWORD) is False

    def test_no_hash_env(self, auth_env, monkeypatch):
        from api import auth
        monkeypatch.delenv("FC_AUTH_PASSWORD_HASH")
        assert auth.verify_password("admin", TEST_PASSWORD) is False

    def test_token_roundtrip(self, auth_env):
        from api import auth
        token = auth.issue_token("admin")
        assert auth.verify_token(token) == "admin"

    def test_token_tampered(self, auth_env):
        from api import auth
        token = auth.issue_token("admin")
        assert auth.verify_token(token[:-1] + ("0" if token[-1] != "0" else "1")) is None

    def test_token_expired(self, auth_env, monkeypatch):
        from api import auth
        token = auth.issue_token("admin")
        monkeypatch.setattr(auth.time, "time", lambda: 9999999999)
        assert auth.verify_token(token) is None

    def test_token_garbage(self, auth_env):
        from api import auth
        assert auth.verify_token("not-a-token") is None
        assert auth.verify_token("") is None


class TestBuildSnapshot:
    """service.build_snapshot の配線テスト — data層をモックし calc.py は実物を通す"""

    def _patch_loaders(self, monkeypatch, df, closes, info, settings=None):
        import api.service as svc
        monkeypatch.setattr(svc, "load_data", lambda: df)
        monkeypatch.setattr(svc, "load_fund_prices", lambda: {})
        monkeypatch.setattr(svc, "load_gas_prices", lambda: {})
        monkeypatch.setattr(svc, "get_gas_last_updated", lambda: "2026/08/13 12:00")
        monkeypatch.setattr(svc, "load_prev_fund_prices", lambda: {})
        monkeypatch.setattr(svc, "load_settings", lambda: settings or {})
        monkeypatch.setattr(svc, "load_last_prices_full", lambda: {})
        monkeypatch.setattr(svc, "get_cached_market_data", lambda t, period="1y": closes)
        monkeypatch.setattr(svc, "get_cached_ticker_info", lambda t: info)
        return svc

    def _jp_stock_df(self):
        return pd.DataFrame([{
            "銘柄コード": "7203", "銘柄名": "トヨタ", "市場": "日本株",
            "保有株数": 100, "取得単価": 2000, "口座区分": "特定口座",
            "手動配当利回り(%)": 0.0, "年間配当金(円/株)": 0.0, "取得時為替": 0.0,
        }])

    def _closes(self):
        idx = pd.date_range("2026-08-01", periods=3)
        return pd.DataFrame({"7203.T": [1900, 2000, 2500], "JPY=X": [150.0, 151.0, 152.0]}, index=idx)

    def test_snapshot_totals_match_calc(self, monkeypatch):
        svc = self._patch_loaders(
            monkeypatch, self._jp_stock_df(), self._closes(),
            {"7203.T": {"sector": "テクノロジー", "div_rate": 0, "div_yield": 0}},
            settings={"cash_balance_jpy": "2000000"},
        )
        snap = svc.build_snapshot()
        assert snap["jpy_usd_rate"] == 152.0
        assert snap["totals"]["total_asset"] == 2500 * 100
        assert snap["totals"]["cash_jpy"] == 2000000
        assert snap["totals"]["total_asset_all"] == 250000 + 2000000
        assert snap["warnings"] == []
        assert snap["gas_last_updated"] == "2026/08/13 12:00"
        assert len(snap["rows"]) == 1
        assert snap["rows"][0]["評価額(円)"] == 250000

    def test_snapshot_fx_fallback_to_last_price(self, monkeypatch):
        """JPY=Xが1点以下 → LastPricesの前回値へフォールバックし警告が付く"""
        idx = pd.date_range("2026-08-01", periods=3)
        closes = pd.DataFrame({"7203.T": [1900, 2000, 2500], "JPY=X": [float("nan"), float("nan"), 151.5]}, index=idx)
        svc = self._patch_loaders(monkeypatch, self._jp_stock_df(), closes, {"7203.T": {"sector": "", "div_rate": 0, "div_yield": 0}})
        import api.service as svc_mod
        monkeypatch.setattr(svc_mod, "load_last_prices_full", lambda: {"JPY=X": (149.5, "2026/08/12 23:00")})
        snap = svc.build_snapshot()
        assert snap["jpy_usd_rate"] == 149.5
        assert len(snap["warnings"]) == 1
        assert "前回取得値" in snap["warnings"][0]

    def test_snapshot_empty_portfolio(self, monkeypatch):
        svc = self._patch_loaders(monkeypatch, pd.DataFrame(), pd.DataFrame(), {})
        snap = svc.build_snapshot()
        assert snap["rows"] == []
        assert snap["totals"]["total_asset"] == 0
        assert snap["totals"]["total_asset_all"] == 0
        assert snap["totals"]["stock_count"] == 0


@requires_client
class TestEndpoints:
    @pytest.fixture
    def client(self, auth_env):
        from fastapi.testclient import TestClient
        import api.main as m
        m._fail_count = 0
        m._lock_until = 0.0
        return TestClient(m.app)

    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_login_ok(self, client):
        r = client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
        assert r.status_code == 200
        assert "token" in r.json()

    def test_login_wrong_then_backoff(self, client):
        r1 = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
        assert r1.status_code == 401
        r2 = client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
        assert r2.status_code == 429  # バックオフ中は正しいパスワードでも拒否

    def test_portfolio_requires_auth(self, client):
        assert client.get("/api/portfolio").status_code == 401
        assert client.get("/api/portfolio", headers={"Authorization": "Bearer bad-token"}).status_code == 401

    def test_portfolio_with_token(self, client, monkeypatch):
        import api.main as m
        fake = {"rows": [], "totals": dict(total_asset=0), "jpy_usd_rate": 150.0, "gas_last_updated": None, "warnings": []}
        monkeypatch.setattr(m, "build_snapshot", lambda: fake)
        token = client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).json()["token"]
        r = client.get("/api/portfolio", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == fake

    def _token(self, client):
        return client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).json()["token"]

    def test_simulate_future(self, client):
        """calc.get_future_simulation を実物で通す配線テスト(年利0なら評価額=元本)"""
        token = self._token(client)
        r = client.post("/api/simulate/future",
                        json={"initial": 1000000, "annual_rate": 0.0, "years": 2, "yearly_addition": 120000},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert rows[0]["経過年数"] == "現在"
        last = rows[-1]
        assert last["予測評価額(円)"] == pytest.approx(last["積立元本(円)"])
        assert last["運用益(円)"] == pytest.approx(0)

    def test_simulate_future_validation(self, client):
        token = self._token(client)
        r = client.post("/api/simulate/future",
                        json={"initial": 1, "annual_rate": 0.05, "years": 0, "yearly_addition": 0},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_simulate_withdrawal_fixed_depletes(self, client):
        """固定額500万/年×資産1000万・年利0 → 2年で枯渇"""
        token = self._token(client)
        r = client.post("/api/simulate/withdrawal",
                        json={"initial": 10000000, "annual_rate": 0.0, "mode": "fixed",
                              "annual_withdrawal": 5000000, "max_years": 40},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        rows = r.json()["rows"]
        assert rows[-1]["年"] == 2
        assert rows[-1]["残高(円)"] == 0
        assert rows[-1]["累計取崩(円)"] == 10000000

    def test_simulate_withdrawal_bad_mode(self, client):
        token = self._token(client)
        r = client.post("/api/simulate/withdrawal",
                        json={"initial": 1, "annual_rate": 0.0, "mode": "oops"},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422

    def test_ai_review_generate_wiring(self, client, monkeypatch):
        import api.main as m
        fake = {"dt": "2026/08/13 23:00", "text": "テスト総評", "truncated": False}
        monkeypatch.setattr(m.svc, "generate_ai_review", lambda: fake)
        token = self._token(client)
        r = client.post("/api/ai/review/generate", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == fake

    def test_ai_review_no_key_503(self, client, monkeypatch):
        import api.main as m

        def boom():
            raise m.svc.AIKeyMissing("no key")
        monkeypatch.setattr(m.svc, "generate_ai_review", boom)
        token = self._token(client)
        r = client.post("/api/ai/review/generate", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 503

    def test_ai_policy_memo_saved(self, client, monkeypatch):
        import api.main as m
        saved = {}
        monkeypatch.setattr(m.svc, "save_policy_memo", lambda memo: saved.update(memo=memo))
        token = self._token(client)
        r = client.put("/api/ai/policy-memo", json={"memo": "  2498は売却確定  "},
                       headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert saved["memo"] == "  2498は売却確定  "  # strip は service 側の責務

    def test_market_and_rank_validation(self, client, monkeypatch):
        import api.main as m
        monkeypatch.setattr(m.svc, "get_world_indices", lambda p: {"period": p, "indices": []})
        monkeypatch.setattr(m.svc, "get_investor_flow", lambda w: {"available": True, "weeks": w})
        monkeypatch.setattr(m.svc, "get_rank_state", lambda: {"total_asset": 0, "rank": None, "tiers": []})
        token = self._token(client)
        h = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/market/indices?period=謎", headers=h).status_code == 422
        assert client.get("/api/market/indices?period=1年", headers=h).json()["period"] == "1年"
        assert client.get("/api/market/investor-flow?weeks=13", headers=h).status_code == 422
        assert client.get("/api/market/investor-flow?weeks=52", headers=h).json()["weeks"] == 52
        assert client.get("/api/rank", headers=h).status_code == 200
        assert client.get("/api/rank").status_code == 401

    def test_transactions_record_wiring_and_validation(self, client, monkeypatch):
        import api.main as m
        monkeypatch.setattr(m.svc, "record_manual_transaction",
                            lambda *a: 12345.0)
        token = self._token(client)
        h = {"Authorization": f"Bearer {token}"}
        ok = {"index": 0, "code": "7203", "tx_type": "売却", "date": "2026/08/13",
              "qty": 10, "price": 2500, "fee": 0, "broker": "SBI証券", "tax": "特定口座"}
        r = client.post("/api/transactions", json=ok, headers=h)
        assert r.status_code == 200 and r.json()["pnl_realized"] == 12345.0
        assert client.post("/api/transactions", json={**ok, "tx_type": "謎"}, headers=h).status_code == 422
        assert client.post("/api/transactions", json={**ok, "date": "2026-08-13"}, headers=h).status_code == 422
        assert client.post("/api/transactions", json={**ok, "qty": 0}, headers=h).status_code == 422

    def test_transactions_conflict_409(self, client, monkeypatch):
        import api.main as m

        def boom(*a):
            raise m.svc.TxError("mismatch")
        monkeypatch.setattr(m.svc, "record_manual_transaction", boom)
        token = self._token(client)
        ok = {"index": 0, "code": "7203", "tx_type": "売却", "date": "2026/08/13",
              "qty": 10, "price": 2500, "fee": 0, "broker": "SBI証券", "tax": "特定口座"}
        r = client.post("/api/transactions", json=ok, headers={"Authorization": f"Bearer {self._token(client)}"})
        assert r.status_code == 409

    def test_transactions_import_validation(self, client, monkeypatch):
        import api.main as m
        monkeypatch.setattr(m.svc, "execute_broker_csv", lambda raw, mode: {"tx_count": 1, "upd_count": 0, "skip_count": 0, "broker": "SBI証券"})
        token = self._token(client)
        h = {"Authorization": f"Bearer {token}"}
        import base64
        b64 = base64.b64encode(b"dummy").decode()
        assert client.post("/api/transactions/import/execute", json={"content_b64": b64, "mode": "謎"}, headers=h).status_code == 422
        assert client.post("/api/transactions/import/execute", json={"content_b64": "!!!", "mode": "取引履歴に登録"}, headers=h).status_code == 422
        r = client.post("/api/transactions/import/execute", json={"content_b64": b64, "mode": "取引履歴に登録"}, headers=h)
        assert r.status_code == 200 and r.json()["tx_count"] == 1

    def test_ai_lifeplan_generate_validation(self, client, monkeypatch):
        import api.main as m
        monkeypatch.setattr(m.svc, "generate_lifeplan", lambda inputs: {"dt": "d", "text": "t", "truncated": False})
        token = self._token(client)
        h = {"Authorization": f"Bearer {token}"}
        assert client.post("/api/ai/lifeplan/generate", json={"inputs": {}}, headers=h).status_code == 422
        assert client.post("/api/ai/lifeplan/generate", json={"inputs": {"年齢": 40}}, headers=h).status_code == 422
        r = client.post("/api/ai/lifeplan/generate", json={"inputs": {"本人年齢": "40歳"}}, headers=h)
        assert r.status_code == 200


class TestRankAndMarket:
    def test_rank_boundaries(self):
        from config import RANK_TIERS, get_rank
        assert get_rank(999_999) is None
        assert get_rank(1_000_000)[0] == "CADET"
        assert get_rank(1_000_000)[2] == 1
        top = RANK_TIERS[-1]
        assert get_rank(top[0])[0] == top[1]
        assert get_rank(top[0])[2] == len(RANK_TIERS)
        # 現資産帯(3,300万) = GENERAL(3000万〜4000万)
        assert get_rank(33_000_000)[0] == "GENERAL"

    def test_investor_flow_transform(self, monkeypatch):
        """get_investor_flow の変換(億円換算・要約・TOPIX切り出し・シグナル)をモックで検証。
        ローカルにJ-Quantsキーが無く実データで確認できないため、ここで担保する"""
        import api.service as svc
        dates = pd.date_range("2026-05-01", periods=10, freq="W-FRI")
        # 海外: 直近2週が買越(前週マイナス→転換シグナル)、個人: 全週一定
        frgn = [1e10] * 7 + [-2e10, 3e10, 5e10]
        ind = [-1e9] * 10
        df = pd.DataFrame({"EnDate": dates, "FrgnBal": frgn, "IndBal": ind, "TrstBnkBal": [0.0] * 10})
        topix = pd.DataFrame({"Date": dates, "Close": [2700.0 + i for i in range(10)]})
        monkeypatch.setattr(svc.jquants, "get_investor_types", lambda weeks: df)
        monkeypatch.setattr(svc.jquants, "get_topix_ohlc", lambda period_days: topix)

        r = svc.get_investor_flow(12)
        assert r["available"] is True
        assert [c["key"] for c in r["columns"]] == ["FrgnBal", "IndBal", "TrstBnkBal"]
        # 億円換算(1e10円 = 100億)
        assert r["rows"][-1]["FrgnBal"] == 500.0
        assert r["rows"][-1]["IndBal"] == -10.0
        assert r["rows"][-1]["date"] == "2026-07-03"
        # 要約: 海外は直近2週連続買越(累計 300+500=800億)
        frgn_sum = next(s for s in r["summary"] if s["col"] == "FrgnBal")
        assert frgn_sum["sign"] == 1 and frgn_sum["weeks"] == 2
        assert frgn_sum["cum_oku"] == 800.0 and frgn_sum["latest_oku"] == 500.0
        # 個人は10週連続売越
        ind_sum = next(s for s in r["summary"] if s["col"] == "IndBal")
        assert ind_sum["sign"] == -1 and ind_sum["weeks"] == 10
        assert len(r["topix"]) == 10 and r["topix"][0]["close"] == 2700.0
        # シグナル: 海外の売越→買越転換は出ない(前週=300億で既に買越)
        assert all("売越転換" not in s for s in r["signals"])

    def test_investor_flow_unavailable(self, monkeypatch):
        import api.service as svc
        monkeypatch.setattr(svc.jquants, "get_investor_types", lambda weeks: pd.DataFrame())
        r = svc.get_investor_flow(12)
        assert r["available"] is False and "取得できなかった" in r["reason"]

    def test_investor_flow_signal_turn(self, monkeypatch):
        """前週売越→今週買越 で買越転換シグナルが出る"""
        import api.service as svc
        dates = pd.date_range("2026-05-01", periods=3, freq="W-FRI")
        df = pd.DataFrame({"EnDate": dates, "FrgnBal": [1e10, -2e10, 3e10]})
        monkeypatch.setattr(svc.jquants, "get_investor_types", lambda weeks: df)
        monkeypatch.setattr(svc.jquants, "get_topix_ohlc", lambda period_days: None)
        r = svc.get_investor_flow(12)
        assert any("買越転換" in s for s in r["signals"])
        assert r["topix"] == []

    def test_flow_streak(self):
        from tabs.tab_market import _flow_streak
        s = pd.Series([100.0, -50.0, 200.0, 300.0])
        r = _flow_streak(s)
        assert r["sign"] == 1 and r["weeks"] == 2 and r["cum"] == 500.0 and r["latest"] == 300.0
        s2 = pd.Series([100.0, -50.0, -30.0])
        r2 = _flow_streak(s2)
        assert r2["sign"] == -1 and r2["weeks"] == 2 and r2["cum"] == -80.0
        assert _flow_streak(pd.Series([0.0])) is None
        assert _flow_streak(pd.Series(dtype=float)) is None


class TestTransactionLogic:
    """tab_transaction.py から抽出した共有実行ロジック(保存系はモック)"""

    def _df(self):
        return pd.DataFrame([
            {"銘柄コード": "7203", "銘柄名": "トヨタ", "市場": "日本株", "保有株数": 100.0,
             "取得単価": 2000.0, "口座": "SBI証券", "口座区分": "特定口座"},
            {"銘柄コード": "8593", "銘柄名": "三菱HC", "市場": "日本株", "保有株数": 200.0,
             "取得単価": 900.0, "口座": "SBI証券", "口座区分": "特定口座"},
        ])

    def _patch_saves(self, monkeypatch):
        import tabs.tab_transaction as tt
        calls = {"save_data": [], "save_transaction": [], "batch": []}
        monkeypatch.setattr(tt, "save_data", lambda df: calls["save_data"].append(df.copy()))
        monkeypatch.setattr(tt, "save_transaction", lambda tx: calls["save_transaction"].append(tx))
        monkeypatch.setattr(tt, "save_transactions_batch", lambda b: calls["batch"].append(b))
        monkeypatch.setattr(tt, "_clear_sheet_cache", lambda: None)
        return calls

    def test_record_sell(self, monkeypatch):
        from tabs.tab_transaction import record_transaction
        calls = self._patch_saves(monkeypatch)
        df = self._df()
        pnl = record_transaction(df, 0, "売却", "2026/08/13", 40, 2500.0, 0, "SBI証券", "特定口座")
        assert pnl == (2500 - 2000) * 40
        assert df.at[0, "保有株数"] == 60
        assert calls["save_transaction"][0]["取引種別"] == "売却"
        assert calls["save_transaction"][0]["損益確定(円)"] == 20000

    def test_record_buy_merges_position(self, monkeypatch):
        from tabs.tab_transaction import record_transaction
        self._patch_saves(monkeypatch)
        df = self._df()
        pnl = record_transaction(df, 0, "買い増し", "2026/08/13", 100, 3000.0, 0, "SBI証券", "特定口座")
        assert pnl == 0
        assert df.at[0, "保有株数"] == 200
        assert df.at[0, "取得単価"] == 2500  # (100*2000+100*3000)/200

    def test_apply_csv_import_both(self, monkeypatch):
        from tabs.tab_transaction import apply_csv_import
        calls = self._patch_saves(monkeypatch)
        df = self._df()
        csv_df = pd.DataFrame([
            {"約定日": "2026/08/01", "_code": "7203", "_name": "トヨタ", "_market": "東証",
             "_取引種別": "買い増し", "_口座区分": "特定口座", "_qty": 100.0, "_price": 2200.0, "_fee": 0},
            {"約定日": "2026/08/02", "_code": "9999", "_name": "未保有", "_market": "東証",
             "_取引種別": "買い増し", "_口座区分": "特定口座", "_qty": 10.0, "_price": 500.0, "_fee": 0},
        ])
        tx, upd, skip = apply_csv_import(csv_df, "SBI証券", "両方（取引履歴＋保有銘柄更新）", df)
        assert (tx, upd, skip) == (2, 1, 1)
        assert len(calls["batch"][0]) == 2
        assert df.at[0, "保有株数"] == 200
        assert df.at[0, "取得単価"] == 2100  # (100*2000+100*2200)/200


class TestAIPrompts:
    """tab_ai.py から抽出した共有プロンプトビルダーの条件分岐回帰"""

    def test_review_prompt_memo_and_past_conditionals(self):
        from tabs.tab_ai import build_review_system_prompt
        base = build_review_system_prompt("", False)
        with_memo = build_review_system_prompt("2498売却確定", False)
        with_past = build_review_system_prompt("", True)
        assert "【運用方針メモの扱い】" not in base
        assert "【運用方針メモの扱い】" in with_memo
        assert "6. 前回からの変化点" not in base
        assert "6. 前回からの変化点" in with_past
        # 固定ブロックの存在(退行検知)
        for frag in ("牧瀬紅莉栖", "【投資信託の評価ルール（重要）】", "【現金の扱い】", "アクション提案（3〜5つ、優先度付き）"):
            assert frag in base

    def test_review_user_content_composition(self):
        from tabs.tab_ai import build_review_user_content
        uc = build_review_user_content("PTXT", "MEMO", "\nHIST")
        assert "PTXT" in uc and "■ 運用方針メモ（投資家の既決事項）\nMEMO" in uc and "HIST" in uc
        uc2 = build_review_user_content("PTXT", "", "")
        assert "運用方針メモ" not in uc2

    def test_lifeplan_prompt_fixed_blocks(self):
        from tabs.tab_ai import build_lifeplan_system_prompt, build_lifeplan_user_content
        sp = build_lifeplan_system_prompt()
        for frag in ("ライフプランニング", "【出力構成（この順序で、見出し付きで）】", "7. 解決案"):
            assert frag in sp
        uc = build_lifeplan_user_content({"本人年齢": "40歳", "配偶者": "36歳"})
        assert uc.startswith("以下の家族・家計条件から")
        assert "- 本人年齢: 40歳" in uc and "- 配偶者: 36歳" in uc


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
