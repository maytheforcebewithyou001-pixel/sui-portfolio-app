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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
