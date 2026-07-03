"""特性テスト: リファクタ前の calc.py / config.py 純ロジックの挙動を凍結する。
実行: PYTHONUTF8=1 python -m pytest test_characterization.py -v
"""
import sys
from unittest.mock import MagicMock
sys.modules.setdefault("streamlit", MagicMock())  # streamlit 依存の回避（test_calc.py と同じ手法）

import math
import pandas as pd
import pytest

from calc import (calculate_holding, calculate_portfolio, get_portfolio_totals,
                  classify_sector, get_future_simulation, simulate_withdrawal,
                  calc_risk_metrics, safe_csv_df, round_up_3,
                  build_portfolio_summary_text)
from config import (get_tax_rate, is_nisa, normalize_broker, normalize_tax,
                    get_rank, RANK_TIERS, TAX_RATE)


# ══════════ config.py ══════════

class TestConfigFuncs:
    def test_get_tax_rate(self):
        assert get_tax_rate("特定口座") == 0.20315
        assert get_tax_rate("NISA(成長投資枠)") == 0.0
        assert get_tax_rate("NISA(積立投資枠)") == 0.0

    def test_is_nisa(self):
        assert is_nisa("NISA(成長投資枠)") is True
        assert is_nisa("特定口座") is False

    def test_normalize_broker(self):
        assert normalize_broker("楽天") == "楽天証券"
        assert normalize_broker("SBIネット") == "SBI証券"
        assert normalize_broker("三菱UFJ") == "三菱UFJeスマート証券"
        assert normalize_broker("auカブコム") == "auカブコム証券"
        assert normalize_broker("") == "SBI証券"          # 空はデフォルト
        assert normalize_broker("X證券") == "X證券"        # 未知はそのまま

    def test_normalize_tax(self):
        assert normalize_tax("NISA 積立") == "NISA(積立投資枠)"
        assert normalize_tax("NISA") == "NISA(成長投資枠)"
        assert normalize_tax("一般") == "特定口座"

    def test_get_rank_none_below_1m(self):
        assert get_rank(999_999) is None
        assert get_rank(0) is None

    def test_get_rank_boundaries(self):
        assert get_rank(1_000_000) == ("CADET", "#6B7D8D", 1, len(RANK_TIERS))
        assert get_rank(9_999_999) == ("COLONEL", "#00D2FF", 9, len(RANK_TIERS))
        assert get_rank(35_000_000) == ("GENERAL", "#FFD54F", 14, len(RANK_TIERS))
        assert get_rank(100_000_000) == ("LEGEND", "#FF6EC7", 21, len(RANK_TIERS))


# ══════════ calc.py: シミュレーション ══════════

class TestFutureSimulation:
    def test_length_and_principal(self):
        df = get_future_simulation(1_000_000, 0.06, 1, 120_000)
        assert len(df) == 13                                   # 0..12ヶ月
        assert df["予測評価額(円)"].iloc[0] == 1_000_000
        assert df["積立元本(円)"].iloc[0] == 1_000_000
        assert df["積立元本(円)"].iloc[-1] == pytest.approx(1_120_000)

    def test_compound_value(self):
        # 月利 q-1 = 1.06**(1/12)-1、12ヶ月後 = 元本*1.06 + 月1万の等比和
        df = get_future_simulation(1_000_000, 0.06, 1, 120_000)
        q = 1.06 ** (1 / 12)
        expected = 1_000_000 * 1.06 + 10_000 * (1.06 - 1) / (q - 1)
        assert df["予測評価額(円)"].iloc[-1] == pytest.approx(expected)
        assert df["運用益(円)"].iloc[-1] == pytest.approx(expected - 1_120_000)


class TestSimulateWithdrawal:
    def test_fixed_depletes(self):
        df = simulate_withdrawal(1_000_000, 0.0, "fixed", annual_withdrawal=300_000)
        assert list(df["残高(円)"]) == [1_000_000, 700_000, 400_000, 100_000, 0]
        assert df["取り崩し額(円)"].iloc[-1] == 100_000       # 最終年は残高分のみ
        assert df["累計取崩(円)"].iloc[-1] == 1_000_000
        assert len(df) == 5                                    # 枯渇でbreak

    def test_rate_mode(self):
        df = simulate_withdrawal(1_000_000, 0.0, "rate", withdrawal_rate=0.10, max_years=2)
        assert df["残高(円)"].iloc[1] == pytest.approx(900_000)
        assert df["残高(円)"].iloc[2] == pytest.approx(810_000)
        assert len(df) == 3                                    # rateモードはbreakしない

    def test_inflation_mode(self):
        df = simulate_withdrawal(1_000_000, 0.0, "inflation",
                                 annual_withdrawal=100_000, inflation_rate=0.10, max_years=2)
        assert df["取り崩し額(円)"].iloc[1] == pytest.approx(100_000)
        assert df["取り崩し額(円)"].iloc[2] == pytest.approx(110_000)
        assert df["残高(円)"].iloc[2] == pytest.approx(790_000)

    def test_fixed_with_growth(self):
        # 取り崩し後に利回りが乗る順序: (1,000,000-100,000)*1.1 = 990,000
        df = simulate_withdrawal(1_000_000, 0.10, "fixed",
                                 annual_withdrawal=100_000, max_years=1)
        assert df["残高(円)"].iloc[1] == pytest.approx(990_000)


# ══════════ calc.py: リスク指標 ══════════

class TestRiskMetrics:
    def test_empty_returns_all_none(self):
        out = calc_risk_metrics(pd.Series(dtype=float))
        assert all(v is None for v in out.values())

    def test_short_series_mdd_only(self):
        prices = pd.Series([100.0, 120.0, 90.0, 100.0])
        out = calc_risk_metrics(prices)
        assert out["MDD"] == pytest.approx(-25.0)              # 90/120-1
        assert out["HV20"] is None and out["Sharpe"] is None and out["beta"] is None

    def test_beta_of_scaled_series_is_one(self):
        idx = pd.date_range("2025-01-01", periods=40)
        market = pd.Series([100.0 + (i % 7) * 3 for i in range(40)], index=idx)
        asset = market * 2                                     # リターン系列が完全一致
        out = calc_risk_metrics(asset, market)
        assert out["beta"] == pytest.approx(1.0, abs=1e-9)
        assert out["alpha"] == pytest.approx(0.0, abs=1e-9)
        assert out["relative_perf"] == pytest.approx(0.0, abs=1e-9)


# ══════════ calc.py: 表示補助 ══════════

class TestRoundUp3More:
    def test_rounds_up_at_4th_decimal(self):
        assert round_up_3(1.0001) == "1.001"                   # 切り上げ
        assert round_up_3(0.0001) == "0.001"

    def test_thousand_separator(self):
        assert round_up_3(1_000_000) == "1,000,000"


class TestSafeCsvDf:
    def test_escapes_formula_prefixes(self):
        df = pd.DataFrame({"a": ["=1+1", "+x", "-y", "@z", "ok"], "b": [1, 2, 3, 4, 5]})
        out = safe_csv_df(df)
        assert list(out["a"]) == ["'=1+1", "'+x", "'-y", "'@z", "ok"]
        assert list(out["b"]) == [1, 2, 3, 4, 5]               # 数値列は非対象


# ══════════ calc.py: セクター分類（既存テストの補完） ══════════

class TestClassifySectorMore:
    def _row(self, market, name):
        return pd.Series({"市場": market, "銘柄名": name})

    def test_fund_branches(self):
        assert classify_sector(self._row("投資信託", "グローバル高配当株式"), "") == "投信/高配当"
        assert classify_sector(self._row("投資信託", "先進国債券インデックス"), "") == "投信/債券"
        assert classify_sector(self._row("投資信託", "新興国株式ファンド"), "") == "投信/新興国株式"
        assert classify_sector(self._row("投資信託", "テーマ型あれこれ"), "") == "投信/その他"

    def test_market_branches(self):
        assert classify_sector(self._row("暗号資産", "BTC"), "") == "暗号資産"
        assert classify_sector(self._row("債券/国債", "何か"), "") == "債券/国債"
        assert classify_sector(self._row("コモディティ", "何か"), "") == "コモディティ"

    def test_info_sector_etc_is_ignored(self):
        # info_sector が "ETF/その他" のときは無視して市場/名前から分類
        assert classify_sector(self._row("投資信託", "全世界株式"), "ETF/その他") == "投信/全世界株式"


# ══════════ calc.py: calculate_holding フォールバック経路 ══════════

def _row(**kw):
    base = {"銘柄コード": "7203", "銘柄名": "トヨタ", "市場": "日本株",
            "保有株数": 100, "取得単価": 2000, "口座区分": "特定口座",
            "手動配当利回り(%)": 0.0, "年間配当金(円/株)": 0.0,
            "取得時為替": 0.0, "手動現在値": 0.0}
    base.update(kw)
    return pd.Series(base)


class TestCalculateHoldingFallbacks:
    def test_gas_fallback(self):
        r = calculate_holding(_row(), pd.DataFrame(), {}, {}, 150.0,
                              gas_prices={"7203": {"price": 2500.0, "change_pct": 1.5}})
        assert r["現在値(円)"] == 2500.0
        assert r["前日比"] == 1.5
        assert r["評価額(円)"] == 250_000.0

    def test_manual_price_fallback(self):
        r = calculate_holding(_row(手動現在値=3000.0), pd.DataFrame(), {}, {}, 150.0)
        assert r["現在値(円)"] == 3000.0
        assert r["前日比"] is None

    def test_ultimate_fallback_is_buy_price(self):
        r = calculate_holding(_row(), pd.DataFrame(), {}, {}, 150.0)
        assert r["現在値(円)"] == 2000.0
        assert r["含み損益(円)"] == 0.0

    def test_fund_prev_nav_gives_dod(self):
        r = calculate_holding(_row(銘柄コード="FUND001", 市場="投資信託", 取得単価=15000),
                              pd.DataFrame(), {}, {"FUND001": 20000.0}, 150.0,
                              prev_fund_prices={"FUND001": 19000.0})
        assert r["前日比"] == pytest.approx((20000 / 19000 - 1) * 100)

    def test_us_stock_without_buy_fx_no_split(self):
        closes = pd.DataFrame({"AAPL": [148.0, 150.0, 170.0]},
                              index=pd.date_range("2025-01-01", periods=3))
        r = calculate_holding(_row(銘柄コード="AAPL", 市場="米国株",
                                   取得単価=150, 保有株数=10, 取得時為替=0.0),
                              closes, {}, {}, 155.0)
        assert r["株価損益(円)"] == 0.0 and r["為替損益(円)"] == 0.0
        assert r["含み損益(円)"] == pytest.approx((170 - 150) * 155.0 * 10)   # 31,000


class TestDividendPriority:
    def _closes(self):
        return pd.DataFrame({"7203.T": [2000.0, 2000.0, 2500.0]},
                            index=pd.date_range("2025-01-01", periods=3))

    def test_div_rate_path(self):
        info = {"7203.T": {"sector": "", "div_rate": 50.0, "div_yield": 0.0}}
        r = calculate_holding(_row(), self._closes(), info, {}, 150.0)
        assert r["予想配当(円)"] == pytest.approx(5000.0)
        assert r["税引後配当(円)"] == pytest.approx(5000.0 * (1 - TAX_RATE))
        assert r["実質利回り(%)"] == pytest.approx(2.0)         # 5000/250000

    def test_manual_yield_path(self):
        info = {"7203.T": {"sector": "", "div_rate": 0.0, "div_yield": 0.0}}
        r = calculate_holding(_row(**{"手動配当利回り(%)": 4.0}), self._closes(), info, {}, 150.0)
        assert r["予想配当(円)"] == pytest.approx(10_000.0)     # 250000*4%
        assert r["実質利回り(%)"] == pytest.approx(4.0)

    def test_div_yield_path(self):
        info = {"7203.T": {"sector": "", "div_rate": 0.0, "div_yield": 0.03}}
        r = calculate_holding(_row(), self._closes(), info, {}, 150.0)
        assert r["予想配当(円)"] == pytest.approx(7500.0)
        assert r["実質利回り(%)"] == pytest.approx(3.0)

    def test_fund_has_no_dividend(self):
        r = calculate_holding(_row(市場="投資信託", **{"手動配当利回り(%)": 5.0}),
                              pd.DataFrame(), {}, {}, 150.0)
        assert r["予想配当(円)"] == 0.0 and r["実質利回り(%)"] == 0.0


class TestCalculatePortfolioOrder:
    def test_market_sort_stable(self):
        df = pd.DataFrame([
            {"銘柄コード": "F1", "銘柄名": "投信A", "市場": "投資信託", "保有株数": 1, "取得単価": 100},
            {"銘柄コード": "AAPL", "銘柄名": "米株A", "市場": "米国株", "保有株数": 1, "取得単価": 100},
            {"銘柄コード": "7203", "銘柄名": "日株A", "市場": "日本株", "保有株数": 1, "取得単価": 100},
            {"銘柄コード": "X", "銘柄名": "その他A", "市場": "その他資産", "保有株数": 1, "取得単価": 100},
        ])
        out = calculate_portfolio(df, pd.DataFrame(), {}, {}, 150.0)
        assert list(out["市場"]) == ["日本株", "米国株", "投資信託", "その他資産"]


class TestSummaryText:
    def test_contains_sections_and_totals(self):
        display_df = pd.DataFrame([{
            "銘柄コード": "7203", "銘柄名": "トヨタ", "市場": "日本株", "セクター": "テクノロジー",
            "評価額(円)": 100_000.0, "税引後損益(円)": 5_000.0, "前日比": 1.0, "予想配当(円)": 2_000.0,
        }])
        totals = {"total_asset": 100_000.0, "total_net_profit": 5_000.0,
                  "total_dividend": 2_000.0, "avg_dividend_yield": 2.0, "stock_count": 1}
        hist = pd.DataFrame({"日付": ["2026/01/01", "2026/02/01"],
                             "総資産額(円)": [90_000.0, 100_000.0]})
        txt = build_portfolio_summary_text(display_df, totals, 150.0, history_df=hist)
        assert "評価額合計: 100,000円" in txt
        assert "■ セクター配分" in txt
        assert "■ 資産推移（直近の記録）" in txt
        assert "記録期間の変化: +11.1%" in txt                  # (100000/90000-1)*100
