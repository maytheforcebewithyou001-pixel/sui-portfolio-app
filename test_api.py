"""api/ (Phase 3 P3-1) のユニットテスト — 全てオフライン(外部通信なし)
実行: python -m pytest test_api.py -v
エンドポイントテストは httpx 必須(requirements-api.txt)。未導入時はskip。
"""
import importlib.util
import json

import bcrypt
import pandas as pd
import pytest

HTTPX_AVAILABLE = importlib.util.find_spec("httpx") is not None
requires_client = pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx未導入(requirements-api.txt参照)")

# テスト用bcryptハッシュ(rounds=4で高速化。本番はデフォルト12)
TEST_PASSWORD = "testpass"
TEST_HASH = bcrypt.hashpw(TEST_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
FATHER_PASSWORD = "chichi-pass"
FATHER_HASH = bcrypt.hashpw(FATHER_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()


@pytest.fixture
def auth_env(monkeypatch):
    monkeypatch.setenv("FC_TOKEN_SECRET", "test-secret-key")
    monkeypatch.setenv("FC_AUTH_USERNAME", "admin")
    monkeypatch.setenv("FC_AUTH_PASSWORD_HASH", TEST_HASH)
    monkeypatch.delenv("FC_AUTH_USERS_JSON", raising=False)


@pytest.fixture
def multi_auth_env(monkeypatch):
    import json
    monkeypatch.setenv("FC_TOKEN_SECRET", "test-secret-key")
    monkeypatch.setenv("FC_AUTH_USERS_JSON", json.dumps({"admin": TEST_HASH, "father": FATHER_HASH}))
    monkeypatch.delenv("FC_AUTH_PASSWORD_HASH", raising=False)


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


class TestMultiUserAuth:
    def test_both_users_login(self, multi_auth_env):
        from api import auth
        assert auth.verify_password("admin", TEST_PASSWORD) is True
        assert auth.verify_password("father", FATHER_PASSWORD) is True
        # パスワードの取り違えは両方向とも拒否
        assert auth.verify_password("admin", FATHER_PASSWORD) is False
        assert auth.verify_password("father", TEST_PASSWORD) is False
        assert auth.verify_password("unknown", TEST_PASSWORD) is False

    def test_users_json_overrides_legacy(self, multi_auth_env, monkeypatch):
        """FC_AUTH_USERS_JSON がある時は単一ユーザー互換変数を一切見ない"""
        from api import auth
        monkeypatch.setenv("FC_AUTH_USERNAME", "legacy")
        monkeypatch.setenv("FC_AUTH_PASSWORD_HASH", TEST_HASH)
        assert auth.verify_password("legacy", TEST_PASSWORD) is False
        assert auth.verify_password("admin", TEST_PASSWORD) is True

    def test_bad_users_json_rejects_all(self, multi_auth_env, monkeypatch):
        from api import auth
        monkeypatch.setenv("FC_AUTH_USERS_JSON", "{broken json")
        assert auth.user_hashes() == {}
        assert auth.verify_password("admin", TEST_PASSWORD) is False

    def test_token_roundtrip_father(self, multi_auth_env):
        from api import auth
        assert auth.verify_token(auth.issue_token("father")) == "father"


class TestUserContext:
    """data.py のユーザー解決とシートID分離(外部通信なし)"""

    def test_current_user_priority(self, monkeypatch):
        import data
        monkeypatch.setenv("FC_API_USER", "envuser")
        assert data._current_user() == "envuser"
        ctx = data.set_request_user("tokenuser")
        try:
            assert data._current_user() == "tokenuser"
        finally:
            data.reset_request_user(ctx)
        assert data._current_user() == "envuser"  # reset後は env に戻る

    def test_sheet_id_not_leaked_to_other_user(self, monkeypatch):
        """単一ユーザー互換の FC_SHEET_ID は FC_API_USER 本人にしか適用されない"""
        import data
        monkeypatch.setenv("FC_API_USER", "admin")
        monkeypatch.setenv("FC_SHEET_ID", "admin-sheet-id")
        monkeypatch.delenv("FC_SHEET_IDS_JSON", raising=False)
        assert data._get_sheet_id_for("admin") == "admin-sheet-id"
        assert data._get_sheet_id_for("father") is None

    def test_sheet_ids_json_per_user(self, monkeypatch):
        import data
        monkeypatch.setenv("FC_SHEET_IDS_JSON", '{"admin": "a-id", "father": "f-id"}')
        monkeypatch.setenv("FC_SHEET_ID", "legacy-id")
        monkeypatch.setenv("FC_API_USER", "admin")
        assert data._get_sheet_id_for("admin") == "a-id"  # JSON が互換変数より優先
        assert data._get_sheet_id_for("father") == "f-id"
        assert data._get_sheet_id_for("other") is None  # JSONに無い他人は互換IDも貰えない

    def test_sheet_ids_json_broken_falls_through(self, monkeypatch):
        import data
        monkeypatch.setenv("FC_SHEET_IDS_JSON", "{broken")
        monkeypatch.setenv("FC_SHEET_ID", "legacy-id")
        monkeypatch.setenv("FC_API_USER", "admin")
        assert data._get_sheet_id_for("admin") == "legacy-id"

    def test_sheet_name_for(self):
        import data
        assert data._sheet_name_for("default") == "PortfolioData"
        assert data._sheet_name_for("father") == "PortfolioData_father"


class TestBuildSnapshot:
    """service.build_snapshot の配線テスト — data層をモックし calc.py は実物を通す"""

    def _patch_loaders(self, monkeypatch, df, closes, info, settings=None):
        import api.service as svc
        from datetime import datetime
        from marketstore import JST
        monkeypatch.setattr(svc, "load_data", lambda: df)
        monkeypatch.setattr(svc, "load_fund_prices", lambda: {})
        monkeypatch.setattr(svc, "load_gas_prices", lambda: {})
        monkeypatch.setattr(svc, "get_gas_last_updated", lambda: "2026/08/13 12:00")
        monkeypatch.setattr(svc, "load_prev_fund_prices", lambda: {})
        monkeypatch.setattr(svc, "load_settings", lambda: settings or {})
        monkeypatch.setattr(svc, "load_last_prices_full", lambda: {})
        fetched = datetime(2026, 8, 16, 6, 30, tzinfo=JST)
        monkeypatch.setattr(svc.marketstore, "get_market_bundle",
                            lambda t, force=False: (closes, info, fetched, None))
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


class TestHistoryState:
    """service.get_history_state — 日付整形・元本Σ(株数×単価)・円換算ベンチマーク(全てオフライン)"""

    def _patch(self, monkeypatch, hist_df, data_df, bench_df):
        import api.service as svc
        monkeypatch.setattr(svc, "load_history", lambda: hist_df)
        monkeypatch.setattr(svc, "load_data", lambda: data_df)
        monkeypatch.setattr(svc, "get_benchmark_history", lambda t, period="2y": bench_df)
        return svc

    def test_rows_sorted_cost_and_benchmarks(self, monkeypatch):
        hist = pd.DataFrame({"日付": ["2026/08/02", "2026/08/01", "不正な日付"],
                             "総資産額(円)": ["200", "100", "300"]})
        data_df = pd.DataFrame([{"保有株数": 100, "取得単価": 2000},
                                {"保有株数": 10, "取得単価": 30.5}])
        idx = pd.to_datetime(["2026-08-01", "2026-08-02"])
        bench = pd.DataFrame({"ACWI": [100.0, 110.0], "^GSPC": [50.0, 55.0],
                              "JPY=X": [150.0, 152.0]}, index=idx)
        svc = self._patch(monkeypatch, hist, data_df, bench)
        st = svc.get_history_state()
        assert [r["date"] for r in st["history"]] == ["2026-08-01", "2026-08-02"]  # ソート+不正日付drop
        assert st["history"][0]["total"] == 100.0
        assert st["cost_total"] == 100 * 2000 + 10 * 30.5
        assert st["benchmarks"]["ACWI"][0] == {"date": "2026-08-01", "value": 100.0 * 150.0}
        assert st["benchmarks"]["^GSPC"][-1]["value"] == 55.0 * 152.0

    def test_single_point_skips_benchmark_fetch(self, monkeypatch):
        import api.service as svc
        called = []
        monkeypatch.setattr(svc, "load_history",
                            lambda: pd.DataFrame({"日付": ["2026/08/01"], "総資産額(円)": ["100"]}))
        monkeypatch.setattr(svc, "load_data", lambda: pd.DataFrame())
        monkeypatch.setattr(svc, "get_benchmark_history",
                            lambda *a, **k: called.append(1) or pd.DataFrame())
        st = svc.get_history_state()
        assert st["history"][0]["total"] == 100.0
        assert st["cost_total"] == 0.0
        assert st["benchmarks"] == {}
        assert called == []  # 2点未満はyfinanceを呼ばない

    def test_empty_history(self, monkeypatch):
        svc = self._patch(monkeypatch, pd.DataFrame(columns=["日付", "総資産額(円)"]),
                          pd.DataFrame(), pd.DataFrame())
        st = svc.get_history_state()
        assert st == {"history": [], "cost_total": 0.0, "benchmarks": {}}


class TestLifeplanMc:
    """service.run_lifeplan_mc — 乱数エンジン共有のため実物で実行(オフライン・依存なし)"""

    def test_regression_default_score(self):
        # 7/17確定の回帰基準: 既定(save=200)でスコア88.225厳密一致
        import api.service as svc
        r = svc.run_lifeplan_mc({})
        assert abs(r["score"] - 88.225) < 1e-9
        t = r["trajectory"]
        assert t["ages"][0] == 40 and t["ages"][-1] == 95
        assert len(t["p50"]) == len(t["ages"]) == len(t["depletion"]) == 56
        # 95歳の累積枯渇確率 = 100 − 信頼スコア の自己整合
        assert abs((100.0 - t["depletion"][-1]) - r["score"]) < 1e-9

    def test_coercion_matches_direct_engine_call(self):
        # 配列→tuple/dict変換後のスコアがエンジン直呼びと厳密一致(値の丸め・補正ゼロの証明)
        import api.service as svc
        from lifeplan_montecarlo_20260717 import simulate
        via_api = svc.run_lifeplan_mc({
            "save": 220, "shocks": [[60, -281.15]], "guardrail": [0.06, 0.10],
            "edu_plan": {"c1": [40, 150, 250, 0], "c2": [40, 40, 120, 0]}})
        direct = simulate(save=220.0, shocks=((60, -281.15),), guardrail=(0.06, 0.10),
                          edu_plan={"c1": (40.0, 150.0, 250.0, 0.0),
                                    "c2": (40.0, 40.0, 120.0, 0.0)})
        assert via_api["score"] == direct["score"]
        assert via_api["terminal_p50"] == direct["terminal_p50"]

    def test_new_engine_params_equivalence(self):
        # 8/16追加のedu_inflow/spend_change_age: 既定値明示=無指定と厳密一致(回帰保護)
        import api.service as svc
        from lifeplan_montecarlo_20260717 import simulate
        base = simulate()["score"]
        assert svc.run_lifeplan_mc({"edu_inflow": 21})["score"] == base
        a = svc.run_lifeplan_mc({"spend_after70": 320, "spend_change_age": 70})["score"]
        assert a == simulate(spend_after70=320.0)["score"]
        # 方向性: 教育口座流入ゼロは低下、完済年齢の前倒しは改善
        assert svc.run_lifeplan_mc({"edu_inflow": 0})["score"] < base
        assert svc.run_lifeplan_mc({"spend_after70": 320, "spend_change_age": 65})["score"] > a

    def test_validation_rejects(self):
        import api.service as svc
        for bad in [{"nokey": 1},                       # 未対応パラメータ
                    {"n_paths": 20_001},                # 計算量ガード
                    {"age_end": 120},
                    {"edu_inflow": -1},
                    {"spend_change_age": 50},
                    {"mu": "abc"},                      # 数値でない
                    {"mu": float("inf")},               # 有限でない
                    {"shocks": [[60]]},                 # 要素数不正
                    {"guardrail": [0.06]},
                    {"edu_plan": {"c1": [1, 2, 3, 4]}},  # c2欠落
                    {"ret_model": "garch"},
                    {"edu_track": "elite"}]:
            with pytest.raises(ValueError):
                svc.run_lifeplan_mc(bad)

    def test_none_values_fall_back_to_engine_defaults(self):
        # null は「未指定」扱い(フォームの空欄をそのまま送れる)
        import api.service as svc
        r = svc.run_lifeplan_mc({"spend_after70": None, "n_paths": 100, "seed": 1})
        assert 0.0 <= r["score"] <= 100.0

    def test_seq_score_nan_becomes_none(self):
        # 決定論(全パス上昇)では序盤逆風の試行ゼロ → seq_score=NaN → JSON安全なnullへ
        import api.service as svc
        r = svc.run_lifeplan_mc({"deterministic": True, "n_paths": 1})
        assert r["seq_score"] is None
        assert r["score"] == 100.0


class TestLifeplanExtras:
    """開始年リプレイ / 目標逆算ソルバー / Sheets履歴(モック)"""

    def test_replay_matches_engine_and_drops_invalid(self):
        import api.service as svc
        from lifeplan_montecarlo_20260717 import historical_sequences
        r = svc.run_lifeplan_replay({"save": 220, "ret_model": "bootstrap", "seed": 1})
        direct = historical_sequences(save=220.0)
        assert r["success_rate"] == direct["success_rate"]
        assert r["n_starts"] == direct["n_starts"] == len(r["results"])
        assert r["dropped"] == ["ret_model", "seed"]  # リプレイ無効設定は落として通知

    def test_solver_save_reaches_target(self):
        import api.service as svc
        base = svc.run_lifeplan_mc({"n_paths": 800, "seed": 7})["score"]
        # 既に達成している目標
        r = svc.solve_lifeplan_target({"n_paths": 800, "seed": 7}, base - 1, "save")
        assert r["already"] is True and r["achievable"] is True
        # 貯蓄積み増しで届く目標: 二分探索の不変条件 f(needed)>=target
        target = min(base + 3, 99.0)
        r = svc.solve_lifeplan_target({"n_paths": 800, "seed": 7}, target, "save")
        assert r["achievable"] is True
        if not r["already"]:
            assert r["needed_value"] > 200
            assert r["score"] >= target

    def test_solver_validation(self):
        import api.service as svc
        with pytest.raises(ValueError):
            svc.solve_lifeplan_target({}, 40, "save")
        with pytest.raises(ValueError):
            svc.solve_lifeplan_target({}, 90, "rent")

    def test_history_save_and_load(self, monkeypatch):
        import api.service as svc
        saved = []
        monkeypatch.setattr(svc, "save_lifeplan_mc", lambda *a: saved.append(a))
        out = svc.save_lifeplan_mc_run("年次点検", {"save": 220},
                                       {"score": 91.065, "terminal_p50": 32091.0})
        assert out["dt"] and saved
        dt_s, memo, score, mj, pj = saved[0]
        assert memo == "年次点検" and score == 91.065
        assert json.loads(pj) == {"save": 220}
        assert json.loads(mj)["terminal_p50"] == 32091.0
        monkeypatch.setattr(svc, "load_lifeplan_mc_history",
                            lambda n=50: [("2026/08/16 23:00", "a", "88.2",
                                           '{"score": 88.2}', '{"save": 200}'),
                                          ("2026/08/16 23:30", "b", "壊れた行",
                                           "not-json", "not-json")])
        h = svc.get_lifeplan_mc_history()
        assert h["history"][0]["dt"] == "2026/08/16 23:30"  # 新しい順
        assert h["history"][0]["score"] is None and h["history"][0]["params"] == {}
        assert h["history"][1]["score"] == 88.2 and h["history"][1]["params"] == {"save": 200}

    def test_history_save_rejects_bad_params(self, monkeypatch):
        import api.service as svc
        monkeypatch.setattr(svc, "save_lifeplan_mc",
                            lambda *a: (_ for _ in ()).throw(AssertionError("呼ばれてはいけない")))
        with pytest.raises(ValueError):
            svc.save_lifeplan_mc_run("x", {"bad_key": 1}, {"score": 1.0})
        with pytest.raises(ValueError):
            svc.save_lifeplan_mc_run("x", {"save": 220}, {})  # score欠落


@requires_client
class TestEndpoints:
    @pytest.fixture
    def client(self, auth_env):
        from fastapi.testclient import TestClient
        import api.main as m
        m._login_backoff.clear()
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
        monkeypatch.setattr(m, "build_snapshot", lambda **kw: fake)
        token = client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).json()["token"]
        r = client.get("/api/portfolio", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == fake

    def _token(self, client):
        return client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).json()["token"]

    def test_history_endpoint_wiring(self, client, monkeypatch):
        import api.main as m
        fake = {"history": [{"date": "2026-08-01", "total": 1.0}], "cost_total": 0.5, "benchmarks": {}}
        monkeypatch.setattr(m.svc, "get_history_state", lambda: fake)
        assert client.get("/api/history").status_code == 401
        token = self._token(client)
        r = client.get("/api/history", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert r.json() == fake

    def test_lifeplan_mc_endpoint_wiring(self, client, monkeypatch):
        import api.main as m
        monkeypatch.setattr(m.svc, "run_lifeplan_mc", lambda p: {"score": 88.2, "echo": p})
        assert client.post("/api/lifeplan/mc", json={"params": {}}).status_code == 401
        token = self._token(client)
        hdr = {"Authorization": f"Bearer {token}"}
        r = client.post("/api/lifeplan/mc", json={"params": {"save": 220}}, headers=hdr)
        assert r.status_code == 200
        assert r.json()["echo"] == {"save": 220}
        r = client.post("/api/lifeplan/mc", json={}, headers=hdr)  # params省略=既定{}
        assert r.status_code == 200
        assert r.json()["echo"] == {}

    def test_lifeplan_mc_endpoint_validation_422(self, client):
        token = self._token(client)
        r = client.post("/api/lifeplan/mc", json={"params": {"nokey": 1}},
                        headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 422
        assert "未対応パラメータ" in r.json()["detail"]

    def test_lifeplan_extras_endpoint_wiring(self, client, monkeypatch):
        import api.main as m
        monkeypatch.setattr(m.svc, "run_lifeplan_replay", lambda p: {"n_starts": 97, "echo": p})
        monkeypatch.setattr(m.svc, "solve_lifeplan_target",
                            lambda p, t, lv: {"target": t, "lever": lv})
        monkeypatch.setattr(m.svc, "get_lifeplan_mc_history", lambda: {"history": []})
        monkeypatch.setattr(m.svc, "save_lifeplan_mc_run",
                            lambda memo, p, mx: {"dt": "2026/08/16", "memo": memo})
        token = self._token(client)
        hdr = {"Authorization": f"Bearer {token}"}
        assert client.post("/api/lifeplan/replay", json={"params": {}}).status_code == 401
        assert client.post("/api/lifeplan/replay", json={"params": {"save": 220}},
                           headers=hdr).json()["echo"] == {"save": 220}
        assert client.post("/api/lifeplan/solve",
                           json={"params": {}, "target": 92, "lever": "spend"},
                           headers=hdr).json() == {"target": 92, "lever": "spend"}
        assert client.get("/api/lifeplan/mc/history", headers=hdr).json() == {"history": []}
        assert client.post("/api/lifeplan/mc/history",
                           json={"memo": "m", "params": {}, "metrics": {"score": 1}},
                           headers=hdr).json()["memo"] == "m"
        r = client.post("/api/lifeplan/mc/history",
                        json={"memo": "x" * 101, "params": {}, "metrics": {}}, headers=hdr)
        assert r.status_code == 422

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

    def test_settings_endpoints(self, client, monkeypatch):
        import api.main as m
        monkeypatch.setattr(m.svc, "get_app_settings",
                            lambda: {"target_jpy_pct": 30.0, "target_usd_pct": 70.0, "cash_balance_jpy": 2000000.0})

        def fake_save(j, u, c):
            if j is not None and (j + (u or 0)) != 100:
                raise m.svc.SettingsError("合計を100%にしてね")
            return {"target_jpy_pct": j, "target_usd_pct": u, "cash_balance_jpy": c}
        monkeypatch.setattr(m.svc, "save_app_settings", fake_save)
        token = self._token(client)
        h = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/settings", headers=h).json()["target_jpy_pct"] == 30.0
        assert client.get("/api/settings").status_code == 401
        assert client.put("/api/settings", json={"target_jpy_pct": 30, "target_usd_pct": 70}, headers=h).status_code == 200
        r = client.put("/api/settings", json={"target_jpy_pct": 30, "target_usd_pct": 60}, headers=h)
        assert r.status_code == 422 and "100%" in r.json()["detail"]

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


@requires_client
class TestMultiUserEndpoints:
    """クロステナント分離のエンドポイントテスト — トークンのユーザーがデータ層に届き、混線しないこと"""

    @pytest.fixture
    def client(self, multi_auth_env):
        from fastapi.testclient import TestClient
        import api.main as m
        m._login_backoff.clear()
        return TestClient(m.app)

    def _token(self, client, username, password):
        r = client.post("/api/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200
        return r.json()["token"]

    def test_request_user_follows_token(self, client, monkeypatch):
        import api.main as m
        import data
        monkeypatch.setattr(m, "build_snapshot", lambda **kw: {"seen_user": data._current_user()})
        t_admin = self._token(client, "admin", TEST_PASSWORD)
        t_father = self._token(client, "father", FATHER_PASSWORD)
        assert client.get("/api/portfolio", headers={"Authorization": f"Bearer {t_admin}"}).json()["seen_user"] == "admin"
        assert client.get("/api/portfolio", headers={"Authorization": f"Bearer {t_father}"}).json()["seen_user"] == "father"
        # 交互アクセスでも直前のユーザーが残留しない
        assert client.get("/api/portfolio", headers={"Authorization": f"Bearer {t_admin}"}).json()["seen_user"] == "admin"
        assert data._request_user.get() is None  # 応答後はreset済み

    def test_token_of_removed_user_rejected(self, client, monkeypatch):
        """認証辞書から消えたユーザーの既発行トークンは期限内でも401"""
        import json as _json
        from api import auth
        token = self._token(client, "father", FATHER_PASSWORD)
        monkeypatch.setenv("FC_AUTH_USERS_JSON", _json.dumps({"admin": TEST_HASH}))
        assert auth.verify_token(token) == "father"  # 署名自体は有効のまま
        r = client.get("/api/portfolio", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401

    def test_backoff_is_per_user(self, client):
        r1 = client.post("/api/auth/login", json={"username": "father", "password": "wrong"})
        assert r1.status_code == 401
        # father がバックオフ中でも admin は即ログインできる
        r2 = client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD})
        assert r2.status_code == 200
        r3 = client.post("/api/auth/login", json={"username": "father", "password": FATHER_PASSWORD})
        assert r3.status_code == 429

    def test_unknown_users_share_one_backoff_slot(self, client):
        import api.main as m
        for name in ("ghost1", "ghost2", "ghost3"):
            client.post("/api/auth/login", json={"username": name, "password": "x"})
        assert set(m._login_backoff) == {"__unknown__"}


class TestStockDetailBundle:
    """get_stock_detail_bundle — tab_portfolio._render_stock_detail と同一手順の配線テスト"""

    def _patch(self, monkeypatch, closes, topix=None, fin=None, detail=None):
        import api.service as svc
        monkeypatch.setattr(svc, "_get_stock_detail", lambda c, m: detail or {})
        monkeypatch.setattr(svc, "get_cached_market_data", lambda t, period="1y": closes)
        monkeypatch.setattr(svc.jquants, "get_topix_ohlc", lambda period_days: topix)
        monkeypatch.setattr(svc.jquants, "get_fin_statements_history", lambda c, limit=8: fin)
        return svc

    def test_chart_math_jp(self, monkeypatch):
        idx = pd.date_range("2026-08-01", periods=3)
        closes = pd.DataFrame({"7203.T": [1900.0, 2000.0, 2500.0], "JPY=X": [150.0] * 3}, index=idx)
        svc = self._patch(monkeypatch, closes)
        b = svc.get_stock_detail_bundle("7203", "日本株", 100, 2000.0, "2026/08/02")
        ch = b["chart"]
        assert [p["v"] for p in ch["points"]] == [200000.0, 250000.0]  # 取得日でフィルタ済み
        assert ch["cost_total"] == 200000.0
        assert ch["pnl_val"] == 50000.0 and ch["pnl_pct"] == 25.0

    def test_chart_us_uses_fx(self, monkeypatch):
        idx = pd.date_range("2026-08-01", periods=2)
        closes = pd.DataFrame({"VT": [100.0, 110.0], "JPY=X": [150.0, 160.0]}, index=idx)
        svc = self._patch(monkeypatch, closes)
        b = svc.get_stock_detail_bundle("VT", "米国株", 10, 15000.0, "")
        vals = [p["v"] for p in b["chart"]["points"]]
        assert vals == [100.0 * 10 * 150.0, 110.0 * 10 * 160.0]

    def test_risk_metrics_wired(self, monkeypatch):
        idx = pd.date_range("2026-01-01", periods=80, freq="B")
        prices = pd.Series([1000 + i * 2 for i in range(80)], index=idx)
        closes = pd.DataFrame({"7203.T": prices, "JPY=X": [150.0] * 80}, index=idx)
        topix = pd.DataFrame({"Date": idx, "Close": [2700 + i for i in range(80)]})
        svc = self._patch(monkeypatch, closes, topix=topix)
        b = svc.get_stock_detail_bundle("7203", "日本株", 100, 1000.0, "")
        assert b["risk"]["HV20"] is not None and b["risk"]["beta"] is not None

    def test_fin_rows_and_revisions(self, monkeypatch):
        idx = pd.date_range("2026-08-01", periods=2)
        closes = pd.DataFrame({"7203.T": [100.0, 101.0]}, index=idx)
        fin = pd.DataFrame({
            "DiscDate": pd.to_datetime(["2026-02-10", "2026-08-10"]),
            "TypeOfCurrentPeriod": ["2Q", "FY"],
            "NetSales": [5e9, 1.05e10],
            "OperatingProfit": [5e8, 1.1e9],
            "Profit": [3e8, 8e8],
            "EarningsPerShare": [25.0, 66.7],
            "ForecastNetSales": [1e10, 1e10],
            "ForecastProfit": [1e9, 1.2e9],
        })
        svc = self._patch(monkeypatch, closes, fin=fin)
        b = svc.get_stock_detail_bundle("7203", "日本株", 100, 100.0, "")
        rows = b["fin"]["rows"]
        assert rows[1]["売上"] == 105.0 and rows[1]["EPS"] == 66.7  # 億円換算/EPSは円のまま
        assert "2026/08 (FY)" == rows[1]["label"]
        assert any("上振れ" in m for m in b["revisions"])       # 実績105億 vs 予想100億 = +5%
        assert any("上方修正" in m for m in b["revisions"])     # 純利益予想 10億→12億 = +20%

    def test_fin_v2_short_columns(self, monkeypatch):
        """J-Quants V2短縮カラム名(Sales/OP/NP/EPS/CurPerType)でも業績が出る"""
        idx = pd.date_range("2026-08-01", periods=2)
        closes = pd.DataFrame({"2498.T": [3000.0, 3300.0]}, index=idx)
        fin = pd.DataFrame({
            "DiscDate": pd.to_datetime(["2026-05-15", "2026-08-14"]),
            "CurPerType": ["2Q", "3Q"],
            "Sales": [4.8e10, 7.37e10],
            "OP": [3.5e9, 5.69e9],
            "NP": [2.7e9, 4.32e9],
            "EPS": [290.62, 359.8],
            "FSales": [1.0e11, 1.0e11],
            "FNP": [3.85e9, 3.85e9],
        })
        svc = self._patch(monkeypatch, closes, fin=fin)
        b = svc.get_stock_detail_bundle("2498", "日本株", 100, 1127.0, "")
        assert b["fin"]["metrics"] == ["売上", "営業利益", "純利益", "EPS"]
        assert b["fin"]["rows"][1]["売上"] == 737.0 and b["fin"]["rows"][1]["EPS"] == 359.8
        assert b["fin"]["rows"][1]["label"] == "2026/08 (3Q)"
        # 四半期行(3Q累計 737億) vs 通期予想(1,000億)で偽の「下振れ」を出さない
        assert not any("下振れ" in m for m in b["revisions"])

    def test_mutual_fund_returns_empty(self, monkeypatch):
        svc = self._patch(monkeypatch, pd.DataFrame())
        b = svc.get_stock_detail_bundle("eMAXIS", "投資信託", 10, 30000.0, "")
        assert b["chart"] is None and b["risk"] is None and b["fin"] is None


@requires_client
class TestStockDetailEndpoint:
    @pytest.fixture
    def client(self, auth_env):
        from fastapi.testclient import TestClient
        import api.main as m
        m._login_backoff.clear()
        return TestClient(m.app)

    def test_validation_and_wiring(self, client, monkeypatch):
        import api.main as m
        captured = {}
        monkeypatch.setattr(m.svc, "get_stock_detail_bundle",
                            lambda code, market, shares, price, date: (captured.update(
                                code=code, market=market, shares=shares, price=price, date=date) or {"detail": None}))
        token = client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).json()["token"]
        h = {"Authorization": f"Bearer {token}"}
        assert client.get("/api/stock/detail?code=7203&market=投資信託", headers=h).status_code == 422
        assert client.get("/api/stock/detail?code=&market=日本株", headers=h).status_code == 422
        assert client.get("/api/stock/detail?code=7203&market=日本株").status_code == 401
        r = client.get("/api/stock/detail?code=7203&market=日本株&shares=100&buy_price=2000&buy_date=2026/08/02", headers=h)
        assert r.status_code == 200
        assert captured == {"code": "7203", "market": "日本株", "shares": 100.0, "price": 2000.0, "date": "2026/08/02"}


class TestMarketStorePolicy:
    """marketstore の更新ポリシー(市場別境界: 日本18:00/米国6:00 JST + 手動30分制限) — 全てオフライン"""

    def _dt(self, y, mo, d, h, mi):
        from datetime import datetime
        from marketstore import JST
        return datetime(y, mo, d, h, mi, tzinfo=JST)

    def test_segment_of(self):
        import marketstore as ms
        assert ms.segment_of("7203.T") == "jp"
        assert ms.segment_of("^N225") == "jp"
        for t in ("VT", "JMIA", "JPY=X", "^GSPC", "^VIX"):
            assert ms.segment_of(t) == "us"

    def test_latest_boundary(self):
        import marketstore as ms
        # 日本(18:00): 10:00 → 前日18:00 / 19:00 → 当日18:00
        assert ms.latest_boundary(self._dt(2026, 9, 1, 10, 0), "jp") == self._dt(2026, 8, 31, 18, 0)
        assert ms.latest_boundary(self._dt(2026, 9, 1, 19, 0), "jp") == self._dt(2026, 9, 1, 18, 0)
        # 米国(6:00): 5:59 → 前日6:00 / 10:00 → 当日6:00
        assert ms.latest_boundary(self._dt(2026, 9, 1, 5, 59), "us") == self._dt(2026, 8, 31, 6, 0)
        assert ms.latest_boundary(self._dt(2026, 9, 1, 10, 0), "us") == self._dt(2026, 9, 1, 6, 0)

    def test_is_fresh(self):
        import marketstore as ms
        now = self._dt(2026, 9, 1, 19, 0)
        assert ms.is_fresh(self._dt(2026, 9, 1, 18, 30), now, "jp") is True   # 当日18:00境界後
        assert ms.is_fresh(self._dt(2026, 9, 1, 17, 0), now, "jp") is False   # 境界前の取得は陳腐
        assert ms.is_fresh(self._dt(2026, 9, 1, 17, 0), now, "us") is True    # 米国境界(6:00)では新鮮
        assert ms.is_fresh(None, now) is False

    def test_parse_fetched_backward_compat(self):
        import marketstore as ms
        # 旧形式(単一fetched_at)は両セグメントの取得時刻として扱う
        f = ms._parse_fetched({"fetched_at": "2026-09-01T10:00:00+09:00"})
        assert set(f) == {"jp", "us"} and f["jp"] == f["us"]
        f2 = ms._parse_fetched({"fetched_at_jp": "2026-09-01T18:05:00+09:00"})
        assert set(f2) == {"jp"}

    def _setup(self, monkeypatch, p_closes, p_info, p_fetched, live_called):
        import marketstore as ms
        import pandas as pd
        monkeypatch.setattr(ms, "load_persistent", lambda: (p_closes, p_info, p_fetched))
        monkeypatch.setattr(ms, "save_persistent", lambda c, i, f: None)
        import market
        monkeypatch.setattr(
            market, "get_cached_market_data",
            lambda t, period="1y": (live_called.append(("data", t)),
                                    pd.DataFrame({k: [100.0] for k in t},
                                                 index=pd.to_datetime(["2026-08-15"])))[1])
        monkeypatch.setattr(
            market, "get_cached_ticker_info",
            lambda t: (live_called.append(("info", t)), {k: {} for k in t})[1])
        ms._mem.update(closes=None, info=None, fetched={})  # プロセス内キャッシュをリセット
        return ms

    def _cache(self):
        import pandas as pd
        closes = pd.DataFrame({"7203.T": [99.0], "VT": [88.0]}, index=pd.to_datetime(["2026-08-15"]))
        return closes, {"7203.T": {"sector": "x"}, "VT": {"sector": "y"}}

    def _fresh(self, minutes=1):
        from datetime import datetime, timedelta
        from marketstore import JST
        return datetime.now(JST) - timedelta(minutes=minutes)  # 直近取得=両境界に対しfresh

    def test_fresh_cache_serves_without_live_fetch(self, monkeypatch):
        live = []
        closes, info = self._cache()
        fetched = {"jp": self._fresh(), "us": self._fresh()}
        ms = self._setup(monkeypatch, closes, info, fetched, live)
        c, i, f, notice = ms.get_market_bundle(("7203.T", "VT"))
        assert live == [] and f == max(fetched.values()) and notice is None
        assert c["7203.T"].iloc[0] == 99.0 and c["VT"].iloc[0] == 88.0

    def test_force_within_30min_returns_cache_with_notice(self, monkeypatch):
        live = []
        closes, info = self._cache()
        fetched = {"jp": self._fresh(10), "us": self._fresh(10)}
        ms = self._setup(monkeypatch, closes, info, fetched, live)
        c, i, f, notice = ms.get_market_bundle(("7203.T", "VT"), force=True)
        assert live == [] and "30分" in notice

    def test_force_after_30min_fetches_both_segments(self, monkeypatch):
        live = []
        closes, info = self._cache()
        fetched = {"jp": self._fresh(31), "us": self._fresh(31)}
        ms = self._setup(monkeypatch, closes, info, fetched, live)
        c, i, f, notice = ms.get_market_bundle(("7203.T", "VT"), force=True)
        fetched_segs = {t for kind, t in live if kind == "data"}
        assert fetched_segs == {("7203.T",), ("VT",)} and notice is None
        assert c["7203.T"].iloc[0] == 100.0 and c["VT"].iloc[0] == 100.0  # 両方ライブ値

    def test_stale_jp_refetches_only_jp_segment(self, monkeypatch):
        import marketstore as ms_mod
        from datetime import datetime, timedelta
        now = datetime.now(ms_mod.JST)
        live = []
        closes, info = self._cache()
        stale_jp = ms_mod.latest_boundary(now, "jp") - timedelta(minutes=5)
        fetched = {"jp": stale_jp, "us": self._fresh()}
        ms = self._setup(monkeypatch, closes, info, fetched, live)
        c, i, f, notice = ms.get_market_bundle(("7203.T", "VT"))
        assert [t for kind, t in live if kind == "data"] == [("7203.T",)]  # 日本株のみ再取得
        assert c["7203.T"].iloc[0] == 100.0  # ライブ値
        assert c["VT"].iloc[0] == 88.0       # 米国はキャッシュ供給

    def test_uncovered_ticker_fetches_its_segment(self, monkeypatch):
        live = []
        closes, info = self._cache()
        fetched = {"jp": self._fresh(), "us": self._fresh()}
        ms = self._setup(monkeypatch, closes, info, fetched, live)
        ms.get_market_bundle(("7203.T", "9999.T", "VT"))  # 9999.T はキャッシュ未収録
        assert [t for kind, t in live if kind == "data"] == [("7203.T", "9999.T")]


class TestAppSettings:
    """サイドバー相当の設定保存(app.py:198-227 のバリデーションと同一)"""

    def _patch(self, monkeypatch, current=None):
        import api.service as svc
        saved = {}
        store = dict(current or {})
        monkeypatch.setattr(svc, "load_settings", lambda: store)
        monkeypatch.setattr(svc, "save_settings", lambda u: (saved.update(u), store.update({k: str(v) for k, v in u.items()})))
        return svc, saved

    def test_get_defaults(self, monkeypatch):
        svc, _ = self._patch(monkeypatch, {})
        assert svc.get_app_settings() == {"target_jpy_pct": 50.0, "target_usd_pct": 50.0, "cash_balance_jpy": 0.0}

    def test_get_parses_strings(self, monkeypatch):
        svc, _ = self._patch(monkeypatch, {"target_jpy_pct": "30", "target_usd_pct": "70", "cash_balance_jpy": "2000000"})
        assert svc.get_app_settings() == {"target_jpy_pct": 30.0, "target_usd_pct": 70.0, "cash_balance_jpy": 2000000.0}

    def test_save_targets_ok(self, monkeypatch):
        svc, saved = self._patch(monkeypatch, {})
        svc.save_app_settings(target_jpy_pct=30, target_usd_pct=70)
        assert saved == {"target_jpy_pct": 30, "target_usd_pct": 70}

    def test_save_targets_rejects_non_100(self, monkeypatch):
        svc, saved = self._patch(monkeypatch, {})
        with pytest.raises(svc.SettingsError, match="100%"):
            svc.save_app_settings(target_jpy_pct=30, target_usd_pct=60)
        assert saved == {}  # 保存されない

    def test_save_targets_requires_both(self, monkeypatch):
        svc, saved = self._patch(monkeypatch, {})
        with pytest.raises(svc.SettingsError):
            svc.save_app_settings(target_jpy_pct=100)
        assert saved == {}

    def test_save_cash_range(self, monkeypatch):
        svc, saved = self._patch(monkeypatch, {})
        svc.save_app_settings(cash_balance_jpy=2_000_000)
        assert saved == {"cash_balance_jpy": 2_000_000}
        with pytest.raises(svc.SettingsError):
            svc.save_app_settings(cash_balance_jpy=-1)

    def test_save_nothing_raises(self, monkeypatch):
        svc, _ = self._patch(monkeypatch, {})
        with pytest.raises(svc.SettingsError):
            svc.save_app_settings()


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
        assert r["available"] is False and "取得できませんでした" in r["reason"]

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
        from investor_flow import flow_streak
        s = pd.Series([100.0, -50.0, 200.0, 300.0])
        r = flow_streak(s)
        assert r["sign"] == 1 and r["weeks"] == 2 and r["cum"] == 500.0 and r["latest"] == 300.0
        s2 = pd.Series([100.0, -50.0, -30.0])
        r2 = flow_streak(s2)
        assert r2["sign"] == -1 and r2["weeks"] == 2 and r2["cum"] == -80.0
        assert flow_streak(pd.Series([0.0])) is None
        assert flow_streak(pd.Series(dtype=float)) is None


class TestTransactionLogic:
    """transactions.py の共有実行ロジック(保存系はモック)"""

    def _df(self):
        return pd.DataFrame([
            {"銘柄コード": "7203", "銘柄名": "トヨタ", "市場": "日本株", "保有株数": 100.0,
             "取得単価": 2000.0, "口座": "SBI証券", "口座区分": "特定口座"},
            {"銘柄コード": "8593", "銘柄名": "三菱HC", "市場": "日本株", "保有株数": 200.0,
             "取得単価": 900.0, "口座": "SBI証券", "口座区分": "特定口座"},
        ])

    def _patch_saves(self, monkeypatch):
        import transactions as tt
        calls = {"save_data": [], "save_transaction": [], "batch": []}
        monkeypatch.setattr(tt, "save_data", lambda df: calls["save_data"].append(df.copy()))
        monkeypatch.setattr(tt, "save_transaction", lambda tx: calls["save_transaction"].append(tx))
        monkeypatch.setattr(tt, "save_transactions_batch", lambda b: calls["batch"].append(b))
        monkeypatch.setattr(tt, "_clear_sheet_cache", lambda: None)
        return calls

    def test_record_sell(self, monkeypatch):
        from transactions import record_transaction
        calls = self._patch_saves(monkeypatch)
        df = self._df()
        pnl = record_transaction(df, 0, "売却", "2026/08/13", 40, 2500.0, 0, "SBI証券", "特定口座")
        assert pnl == (2500 - 2000) * 40
        assert df.at[0, "保有株数"] == 60
        assert calls["save_transaction"][0]["取引種別"] == "売却"
        assert calls["save_transaction"][0]["損益確定(円)"] == 20000

    def test_record_buy_merges_position(self, monkeypatch):
        from transactions import record_transaction
        self._patch_saves(monkeypatch)
        df = self._df()
        pnl = record_transaction(df, 0, "買い増し", "2026/08/13", 100, 3000.0, 0, "SBI証券", "特定口座")
        assert pnl == 0
        assert df.at[0, "保有株数"] == 200
        assert df.at[0, "取得単価"] == 2500  # (100*2000+100*3000)/200

    def test_apply_csv_import_both(self, monkeypatch):
        from transactions import apply_csv_import
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
    """ai_review.py の共有プロンプトビルダーの条件分岐回帰"""

    def test_review_prompt_memo_and_past_conditionals(self):
        from ai_review import build_review_system_prompt
        base = build_review_system_prompt("", False)
        with_memo = build_review_system_prompt("2498売却確定", False)
        with_past = build_review_system_prompt("", True)
        assert "【運用方針メモの扱い】" not in base
        assert "【運用方針メモの扱い】" in with_memo
        assert "6. 前回からの変化点" not in base
        assert "6. 前回からの変化点" in with_past
        # 固定ブロックの存在(退行検知)
        for frag in ("である調", "【投資信託の評価ルール（重要）】", "【現金の扱い】", "アクション提案（3〜5つ、優先度付き）"):
            assert frag in base
        # 人格プロンプトの残骸が無いこと(である調への移行退行検知)
        for gone in ("牧瀬紅莉栖", "アマデウス", "岡部"):
            assert gone not in base

    def test_review_user_content_composition(self):
        from ai_review import build_review_user_content
        uc = build_review_user_content("PTXT", "MEMO", "\nHIST")
        assert "PTXT" in uc and "■ 運用方針メモ（投資家の既決事項）\nMEMO" in uc and "HIST" in uc
        uc2 = build_review_user_content("PTXT", "", "")
        assert "運用方針メモ" not in uc2

    def test_lifeplan_prompt_fixed_blocks(self):
        from ai_review import build_lifeplan_system_prompt, build_lifeplan_user_content
        sp = build_lifeplan_system_prompt()
        for frag in ("ライフプランニング", "【出力構成（この順序で、見出し付きで）】", "7. 解決案"):
            assert frag in sp
        uc = build_lifeplan_user_content({"本人年齢": "40歳", "配偶者": "36歳"})
        assert uc.startswith("以下の家族・家計条件から")
        assert "- 本人年齢: 40歳" in uc and "- 配偶者: 36歳" in uc


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestMarketCacheSheetId:
    """marketstore._cache_sheet_id の解決順(Cloud Run Job には FC_SHEET_ID が無いため3段目が要)"""

    def test_precedence(self, monkeypatch):
        import marketstore as ms
        monkeypatch.setenv("FC_MARKET_CACHE_SHEET_ID", "cache-id")
        monkeypatch.setenv("FC_SHEET_ID", "single-id")
        monkeypatch.setenv("FC_SHEET_IDS_JSON", json.dumps({"admin": "admin-id", "father": "father-id"}))
        monkeypatch.setenv("FC_API_USER", "admin")
        assert ms._cache_sheet_id() == "cache-id"
        monkeypatch.delenv("FC_MARKET_CACHE_SHEET_ID")
        assert ms._cache_sheet_id() == "single-id"
        monkeypatch.delenv("FC_SHEET_ID")
        assert ms._cache_sheet_id() == "admin-id"  # Job 構成: FC_SHEET_IDS_JSON[FC_API_USER]

    def test_fallback_requires_matching_user(self, monkeypatch):
        import marketstore as ms
        monkeypatch.delenv("FC_MARKET_CACHE_SHEET_ID", raising=False)
        monkeypatch.delenv("FC_SHEET_ID", raising=False)
        monkeypatch.setenv("FC_SHEET_IDS_JSON", json.dumps({"father": "father-id"}))
        monkeypatch.setenv("FC_API_USER", "admin")
        assert ms._cache_sheet_id() == ""  # 他ユーザーのIDへは倒れない
        monkeypatch.setenv("FC_SHEET_IDS_JSON", "{broken")
        assert ms._cache_sheet_id() == ""


class TestWarmJob:
    """api/warm_job.py — 18:10 JST の MarketCache 温め(全てオフライン)"""

    def test_target_users_from_sheet_ids(self, monkeypatch):
        from api import warm_job
        monkeypatch.setenv("FC_SHEET_IDS_JSON", json.dumps({"father": "b", "admin": "a", "empty": ""}))
        assert warm_job.target_users() == ["admin", "father"]  # 昇順・ID未登録は除外

    def test_target_users_fallback(self, monkeypatch):
        from api import warm_job
        monkeypatch.delenv("FC_SHEET_IDS_JSON", raising=False)
        monkeypatch.setenv("FC_API_USER", "admin")
        assert warm_job.target_users() == ["admin"]
        monkeypatch.setenv("FC_SHEET_IDS_JSON", "{broken")
        assert warm_job.target_users() == ["admin"]

    def _patch(self, monkeypatch, compute):
        import api.service as svc
        import marketstore as ms
        monkeypatch.setattr(svc, "_compute_state", compute)
        monkeypatch.setattr(ms, "load_persistent", lambda: (None, None, {}))
        monkeypatch.setattr(ms, "_cache_sheet_id", lambda: "cache-id")

    def test_main_warms_each_user_in_context(self, monkeypatch, capsys):
        from api import warm_job
        import data
        seen = []

        def fake_compute(force_refresh=False):
            seen.append(data._current_user())
            return {"display_df": pd.DataFrame({"a": [1, 2]}), "market_fetched_at": "2026-09-04T18:10:00+09:00"}

        self._patch(monkeypatch, fake_compute)
        monkeypatch.setenv("FC_SHEET_IDS_JSON", json.dumps({"admin": "a", "father": "b"}))
        assert warm_job.main() == 0
        assert seen == ["admin", "father"]           # ユーザー別コンテキストで本番と同一経路を実行
        assert data._request_user.get() is None     # 実行後はコンテキストを残さない
        out = capsys.readouterr().out
        assert "OK: admin: 2銘柄" in out and "OK: father: 2銘柄" in out

    def test_main_continues_after_failure_and_exits_nonzero(self, monkeypatch, capsys):
        from api import warm_job
        import data
        seen = []

        def fake_compute(force_refresh=False):
            u = data._current_user()
            seen.append(u)
            if u == "admin":
                raise RuntimeError("sheet unavailable")
            return {"display_df": pd.DataFrame(), "market_fetched_at": None}

        self._patch(monkeypatch, fake_compute)
        monkeypatch.setenv("FC_SHEET_IDS_JSON", json.dumps({"admin": "a", "father": "b"}))
        assert warm_job.main() == 1
        assert seen == ["admin", "father"]  # admin の失敗後も father を処理
        out = capsys.readouterr().out
        assert "NG: admin: RuntimeError" in out and "FAILED: admin" in out
        assert data._request_user.get() is None

    def test_main_warns_when_cache_sheet_unresolved(self, monkeypatch, capsys):
        from api import warm_job
        import marketstore as ms
        self._patch(monkeypatch, lambda force_refresh=False: {"display_df": pd.DataFrame(), "market_fetched_at": None})
        monkeypatch.setattr(ms, "_cache_sheet_id", lambda: "")
        monkeypatch.setenv("FC_SHEET_IDS_JSON", json.dumps({"admin": "a"}))
        assert warm_job.main() == 0
        assert "WARN: MarketCache のシートIDを解決できません" in capsys.readouterr().out


class TestHoldingsService:
    """保有銘柄の追加・修正・削除(旧 tab_portfolio の add_form / data_editor と同一手順)。Sheets はインメモリ模擬"""

    def _base_fields(self, **over):
        f = {"銘柄コード": "7203", "銘柄名": "トヨタ", "市場": "日本株", "通貨": "JPY", "保有株数": 100,
             "取得単価": 2000, "口座": "SBI証券", "口座区分": "特定口座", "手動配当利回り(%)": 0,
             "配当月": [3, 9], "年間配当金(円/株)": 0, "取得時為替": 0, "手動現在値": 0, "取得日": ""}
        f.update(over)
        return f

    def _store(self, monkeypatch, rows, save_ok=True):
        """load_data/save_data をインメモリ化。save_ok=False は save_data が握りつぶした失敗を模擬"""
        import api.service as svc
        from config import EXPECTED_COLS
        state = {"df": pd.DataFrame(rows, columns=EXPECTED_COLS) if rows else pd.DataFrame(columns=EXPECTED_COLS)}
        for col in ("保有株数", "取得単価", "手動配当利回り(%)", "年間配当金(円/株)", "取得時為替", "手動現在値"):
            state["df"][col] = pd.to_numeric(state["df"][col], errors="coerce").fillna(0.0)
        saved = []

        def fake_save(df):
            saved.append(df.copy())
            if save_ok:
                state["df"] = df.copy()

        monkeypatch.setattr(svc, "load_data", lambda: state["df"].copy())
        monkeypatch.setattr(svc, "save_data", fake_save)
        monkeypatch.setattr(svc, "_clear_sheet_cache", lambda: None)
        monkeypatch.setattr(svc, "get_ticker_name", lambda code, market: {"7203": "トヨタ自動車"}.get(code, "取得失敗"))
        return state, saved

    def _row(self, code="7203", name="トヨタ", broker="SBI証券", tax="特定口座", shares=100.0, price=2000.0):
        return {"銘柄コード": code, "銘柄名": name, "市場": "日本株", "通貨": "JPY", "保有株数": shares,
                "取得単価": price, "口座": broker, "口座区分": tax, "手動配当利回り(%)": 0.0, "配当月": "",
                "年間配当金(円/株)": 0.0, "取得時為替": 0.0, "手動現在値": 0.0, "取得日": "", "最新更新日": ""}

    def test_normalize_months_and_validation(self):
        import api.service as svc
        assert svc._normalize_months([9, 3, 3]) == "3,9"
        assert svc._normalize_months("3月, 9月") == "3,9"
        assert svc._normalize_months("") == ""
        with pytest.raises(svc.HoldingError):
            svc._normalize_months("13")
        with pytest.raises(svc.HoldingError, match="市場"):
            svc.normalize_holding_fields(self._base_fields(市場="仮想通貨"), True)
        with pytest.raises(svc.HoldingError, match="保有数"):
            svc.normalize_holding_fields(self._base_fields(保有株数=0), True)
        assert svc.normalize_holding_fields(self._base_fields(保有株数=0), False)["保有株数"] == 0.0  # 編集は0可
        with pytest.raises(svc.HoldingError, match="取得日"):
            svc.normalize_holding_fields(self._base_fields(取得日="2026-09-04"), True)
        with pytest.raises(svc.HoldingError, match="取得時為替"):
            svc.normalize_holding_fields(self._base_fields(取得時為替=5000), True)
        with pytest.raises(svc.HoldingError, match="数値"):
            svc.normalize_holding_fields(self._base_fields(取得単価="abc"), True)
        f = svc.normalize_holding_fields(self._base_fields(取得日="2026/09/04", 保有株数="150.5"), True)
        assert f["保有株数"] == 150.5 and f["配当月"] == "3,9" and f["取得日"] == "2026/09/04"

    def test_get_holdings_state(self, monkeypatch):
        import api.service as svc
        self._store(monkeypatch, [self._row(), self._row("VT", "VT", tax="NISA(成長投資枠)")])
        st = svc.get_holdings_state()
        assert [h["index"] for h in st["holdings"]] == [0, 1]
        assert st["holdings"][1]["口座区分"] == "NISA(成長投資枠)"
        assert "SBI証券" in st["options"]["口座"] and "投資信託" in st["options"]["市場"]

    def test_add_new_row_with_auto_name(self, monkeypatch):
        import api.service as svc
        state, saved = self._store(monkeypatch, [self._row("8593", "三菱HC")])
        r = svc.add_holding(self._base_fields(銘柄名=""))
        assert r["merged"] is False and r["index"] == 1 and r["name"] == "トヨタ自動車"  # J-Quants 名を自動採用
        df = state["df"]
        assert len(df) == 2 and df.at[1, "銘柄コード"] == "7203" and df.at[1, "配当月"] == "3,9"
        assert df.at[1, "保有株数"] == 100.0 and df.at[1, "最新更新日"] != ""

    def test_add_name_falls_back_to_code(self, monkeypatch):
        import api.service as svc
        state, _ = self._store(monkeypatch, [])
        r = svc.add_holding(self._base_fields(銘柄コード="9999", 銘柄名=""))
        assert r["name"] == "9999"  # 取得失敗は「取得失敗」文字列を名前にしない

    def test_add_merges_same_code_broker_tax(self, monkeypatch):
        import api.service as svc
        state, _ = self._store(monkeypatch, [self._row(shares=100.0, price=2000.0)])
        r = svc.add_holding(self._base_fields(保有株数=100, 取得単価=3000, 配当月=[6], **{"年間配当金(円/株)": 0}))
        assert r["merged"] is True and r["shares_after"] == 200.0 and r["avg_price"] == 2500.0  # merge_position と同一
        df = state["df"]
        assert len(df) == 1 and df.at[0, "保有株数"] == 200.0 and df.at[0, "取得単価"] == 2500.0
        assert df.at[0, "配当月"] == "6"

    def test_add_same_code_other_account_is_separate_row(self, monkeypatch):
        import api.service as svc
        state, _ = self._store(monkeypatch, [self._row()])
        r = svc.add_holding(self._base_fields(口座区分="NISA(成長投資枠)"))
        assert r["merged"] is False and len(state["df"]) == 2

    def test_update_replaces_fields_and_checks_code(self, monkeypatch):
        import api.service as svc
        state, _ = self._store(monkeypatch, [self._row(), self._row("8593", "三菱HC")])
        r = svc.update_holding(1, "8593", self._base_fields(銘柄コード="8593", 銘柄名="", 保有株数=300, 取得単価=950.5,
                                                            配当月="6,12", **{"年間配当金(円/株)": 40}))
        assert r["name"] == "三菱HC"  # 空欄は既存名を維持
        df = state["df"]
        assert df.at[1, "保有株数"] == 300.0 and df.at[1, "取得単価"] == 950.5 and df.at[1, "配当月"] == "6,12"
        assert df.at[0, "保有株数"] == 100.0  # 他行は無変更
        with pytest.raises(svc.HoldingError) as ei:
            svc.update_holding(1, "7203", self._base_fields(銘柄コード="8593"))
        assert ei.value.status == 409
        with pytest.raises(svc.HoldingError) as ei:
            svc.update_holding(5, "8593", self._base_fields(銘柄コード="8593"))
        assert ei.value.status == 409

    def test_delete_row(self, monkeypatch):
        import api.service as svc
        state, _ = self._store(monkeypatch, [self._row(), self._row("8593", "三菱HC")])
        r = svc.delete_holding(0, "7203")
        assert r["name"] == "トヨタ"
        df = state["df"]
        assert len(df) == 1 and df.at[0, "銘柄コード"] == "8593"  # 残行は 0 始まりに詰め直す
        with pytest.raises(svc.HoldingError) as ei:
            svc.delete_holding(0, "7203")
        assert ei.value.status == 409

    def test_silent_save_failure_is_detected(self, monkeypatch):
        """save_data が例外を握りつぶして何も書けなかった場合、再読込検証で 500 にする"""
        import api.service as svc
        self._store(monkeypatch, [self._row()], save_ok=False)
        with pytest.raises(svc.HoldingError) as ei:
            svc.add_holding(self._base_fields(銘柄コード="8593"))
        assert ei.value.status == 500 and "行数" in str(ei.value)
        with pytest.raises(svc.HoldingError) as ei:
            svc.update_holding(0, "7203", self._base_fields(保有株数=999))
        assert ei.value.status == 500 and "内容" in str(ei.value)

    def test_lookup_ticker_name(self, monkeypatch):
        import api.service as svc
        monkeypatch.setattr(svc, "get_ticker_name", lambda code, market: {"7203": "トヨタ自動車"}.get(code, "名称不明"))
        assert svc.lookup_ticker_name("7203", "日本株") == {"name": "トヨタ自動車"}
        assert svc.lookup_ticker_name("0000", "日本株") == {"name": ""}
        assert svc.lookup_ticker_name("7203", "投資信託") == {"name": ""}


@requires_client
class TestHoldingsEndpoints:
    """/api/holdings の配線・検証・エラーコード変換"""

    @pytest.fixture
    def client(self, auth_env):
        from fastapi.testclient import TestClient
        import api.main as m
        m._login_backoff.clear()
        return TestClient(m.app)

    def _hdr(self, client):
        token = client.post("/api/auth/login", json={"username": "admin", "password": TEST_PASSWORD}).json()["token"]
        return {"Authorization": f"Bearer {token}"}

    def test_requires_auth(self, client):
        assert client.get("/api/holdings").status_code == 401
        assert client.post("/api/holdings", json={"fields": {"銘柄コード": "7203"}}).status_code == 401
        assert client.put("/api/holdings/0", json={"code": "7203", "fields": {"a": 1}}).status_code == 401
        assert client.delete("/api/holdings/0?code=7203").status_code == 401

    def test_wiring(self, client, monkeypatch):
        import api.main as m
        calls = {}
        monkeypatch.setattr(m.svc, "get_holdings_state", lambda: {"holdings": [], "columns": [], "options": {}})
        monkeypatch.setattr(m.svc, "add_holding", lambda f: calls.setdefault("add", f) or {"merged": False})
        monkeypatch.setattr(m.svc, "update_holding", lambda i, c, f: calls.setdefault("upd", (i, c, f)) or {"index": i})
        monkeypatch.setattr(m.svc, "delete_holding", lambda i, c: calls.setdefault("del", (i, c)) or {"index": i})
        monkeypatch.setattr(m.svc, "lookup_ticker_name", lambda c, mk: {"name": f"{c}@{mk}"})
        hdr = self._hdr(client)
        assert client.get("/api/holdings", headers=hdr).json() == {"holdings": [], "columns": [], "options": {}}
        f = {"銘柄コード": "7203", "市場": "日本株"}
        assert client.post("/api/holdings", json={"fields": f}, headers=hdr).status_code == 200
        assert calls["add"] == f
        assert client.put("/api/holdings/3", json={"code": "7203", "fields": f}, headers=hdr).status_code == 200
        assert calls["upd"] == (3, "7203", f)
        assert client.delete("/api/holdings/2?code=8593", headers=hdr).status_code == 200
        assert calls["del"] == (2, "8593")
        r = client.get("/api/holdings/lookup?code=7203&market=日本株", headers=hdr)
        assert r.status_code == 200 and r.json() == {"name": "7203@日本株"}

    def test_validation_422(self, client, monkeypatch):
        hdr = self._hdr(client)
        assert client.post("/api/holdings", json={"fields": {}}, headers=hdr).status_code == 422
        assert client.post("/api/holdings", json={"fields": {"銘柄名": "x" * 201}}, headers=hdr).status_code == 422
        assert client.put("/api/holdings/-1", json={"code": "7203", "fields": {"a": 1}}, headers=hdr).status_code == 422
        assert client.delete("/api/holdings/0", headers=hdr).status_code == 422  # code 必須
        assert client.get("/api/holdings/lookup?code=7203&market=投資信託", headers=hdr).status_code == 422

    def test_holding_error_status_mapping(self, client, monkeypatch):
        import api.main as m

        def boom(status):
            def _f(*a, **k):
                raise m.svc.HoldingError("だめ", status)
            return _f

        hdr = self._hdr(client)
        monkeypatch.setattr(m.svc, "add_holding", boom(422))
        r = client.post("/api/holdings", json={"fields": {"銘柄コード": "x"}}, headers=hdr)
        assert r.status_code == 422 and r.json()["detail"] == "だめ"
        monkeypatch.setattr(m.svc, "update_holding", boom(409))
        assert client.put("/api/holdings/0", json={"code": "x", "fields": {"銘柄コード": "x"}}, headers=hdr).status_code == 409
        monkeypatch.setattr(m.svc, "delete_holding", boom(500))
        assert client.delete("/api/holdings/0?code=x", headers=hdr).status_code == 500
