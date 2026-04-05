"""
#7 calc.pyのユニットテスト
実行: python -m pytest tests_calc.py -v
"""
import pandas as pd
import pytest
from unittest.mock import patch

# config.pyのstreamlit依存を回避するためモック
import sys
from unittest.mock import MagicMock
sys.modules["streamlit"] = MagicMock()

from calc import calculate_holding, get_portfolio_totals, classify_sector, round_up_3


class TestClassifySector:
    def test_known_sector(self):
        row = pd.Series({"市場": "日本株", "銘柄名": "トヨタ"})
        assert classify_sector(row, "テクノロジー") == "テクノロジー"

    def test_fund_global(self):
        row = pd.Series({"市場": "投資信託", "銘柄名": "eMAXIS Slim 全世界株式"})
        assert classify_sector(row, "") == "投信/全世界株式"

    def test_fund_sp500(self):
        row = pd.Series({"市場": "投資信託", "銘柄名": "SBI・V・S&P500"})
        assert classify_sector(row, "") == "投信/米国株式"

    def test_other_asset_bond(self):
        row = pd.Series({"市場": "その他資産", "銘柄名": "個人向け国債"})
        assert classify_sector(row, "") == "国債"

    def test_other_asset_gold(self):
        row = pd.Series({"市場": "その他資産", "銘柄名": "純金積立（ゴールド）"})
        assert classify_sector(row, "") == "コモディティ"

    def test_unknown_falls_to_etf(self):
        row = pd.Series({"市場": "日本株", "銘柄名": "何か"})
        assert classify_sector(row, "") == "ETF/その他"


class TestCalculateHolding:
    """日本株NISA / 米国株特定口座(為替あり) / 投信 の3パターン"""

    def _make_row(self, **kwargs):
        defaults = {"銘柄コード": "7203", "銘柄名": "トヨタ", "市場": "日本株",
                    "保有株数": 100, "取得単価": 2000, "口座区分": "特定口座",
                    "手動配当利回り(%)": 0.0, "年間配当金(円/株)": 0.0, "取得時為替": 0.0}
        defaults.update(kwargs)
        return pd.Series(defaults)

    def _make_closes(self, ticker, prices):
        return pd.DataFrame({ticker: prices}, index=pd.date_range("2025-01-01", periods=len(prices)))

    def test_japan_stock_nisa_profit(self):
        """日本株NISA: 含み益あり → 税金ゼロ"""
        row = self._make_row(口座区分="NISA(成長投資枠)", 取得単価=2000)
        closes = self._make_closes("7203.T", [1900, 2000, 2500])
        result = calculate_holding(row, closes, {"7203.T": {"sector": "テクノロジー", "div_rate": 0, "div_yield": 0}},
                                    {}, 150.0)
        assert result["評価額(円)"] == 2500 * 100  # 250,000
        assert result["含み損益(円)"] == (2500 - 2000) * 100  # 50,000
        assert result["税引後損益(円)"] == 50000  # NISA → 税ゼロ

    def test_japan_stock_tokutei_profit(self):
        """日本株特定口座: 含み益あり → 20.315%課税"""
        row = self._make_row(口座区分="特定口座", 取得単価=2000)
        closes = self._make_closes("7203.T", [1900, 2000, 2500])
        result = calculate_holding(row, closes, {"7203.T": {"sector": "テクノロジー", "div_rate": 0, "div_yield": 0}},
                                    {}, 150.0)
        profit = 50000
        expected_net = profit - (profit * 0.20315)
        assert abs(result["税引後損益(円)"] - expected_net) < 1

    def test_japan_stock_loss(self):
        """含み損の場合は税金ゼロ"""
        row = self._make_row(口座区分="特定口座", 取得単価=3000)
        closes = self._make_closes("7203.T", [2900, 3000, 2500])
        result = calculate_holding(row, closes, {"7203.T": {"sector": "", "div_rate": 0, "div_yield": 0}},
                                    {}, 150.0)
        assert result["含み損益(円)"] == (2500 - 3000) * 100  # -50,000
        assert result["税引後損益(円)"] == -50000  # 損なので課税なし

    def test_us_stock_with_fx(self):
        """米国株: 為替損益の分離"""
        row = self._make_row(銘柄コード="AAPL", 市場="米国株", 取得単価=150, 取得時為替=140, 保有株数=10, 口座区分="特定口座")
        closes = self._make_closes("AAPL", [148, 150, 170])
        result = calculate_holding(row, closes, {"AAPL": {"sector": "テクノロジー", "div_rate": 0, "div_yield": 0}},
                                    {}, 155.0)
        # 株価損益 = (170 - 150) * 10 * 155 = 31,000
        assert abs(result["株価損益(円)"] - 31000) < 1
        # 為替損益 = 150 * 10 * (155 - 140) = 22,500
        assert abs(result["為替損益(円)"] - 22500) < 1

    def test_fund_with_nav(self):
        """投資信託: 基準価額から計算"""
        row = self._make_row(銘柄コード="FUND001", 市場="投資信託", 取得単価=15000, 保有株数=50)
        fund_prices = {"FUND001": 18000}
        result = calculate_holding(row, pd.DataFrame(), {}, fund_prices, 150.0)
        assert result["評価額(円)"] == 18000 * 50
        assert result["含み損益(円)"] == (18000 - 15000) * 50

    def test_dividend_annual_per_share(self):
        """年間配当金(円/株)が指定されている場合"""
        row = self._make_row(口座区分="特定口座", 年間配当金_円_株=50)
        # pandasの列名にはカッコが使われるため
        row["年間配当金(円/株)"] = 50.0
        closes = self._make_closes("7203.T", [2000, 2000, 2500])
        result = calculate_holding(row, closes, {"7203.T": {"sector": "", "div_rate": 0, "div_yield": 0}},
                                    {}, 150.0)
        assert result["予想配当(円)"] == 50 * 100  # 5000
        expected_after_tax = 5000 * (1 - 0.20315)
        assert abs(result["税引後配当(円)"] - expected_after_tax) < 1


class TestRoundUp3:
    def test_integer(self):
        assert round_up_3(1234) == "1,234"

    def test_decimal(self):
        assert round_up_3(1.5) == "1.5"

    def test_small_decimal(self):
        result = round_up_3(0.001)
        assert result == "0.001"

    def test_invalid(self):
        assert round_up_3("abc") == "abc"


class TestGetPortfolioTotals:
    def test_basic(self):
        df = pd.DataFrame({
            "評価額(円)": [100000, 200000],
            "税引後損益(円)": [10000, -5000],
            "予想配当(円)": [3000, 6000],
            "税引後配当(円)": [2400, 4800],
            "為替損益(円)": [0, 1000],
            "株価損益(円)": [0, 5000],
        })
        t = get_portfolio_totals(df)
        assert t["total_asset"] == 300000
        assert t["total_net_profit"] == 5000
        assert t["total_dividend"] == 9000
        assert t["stock_count"] == 2
        assert abs(t["avg_dividend_yield"] - 3.0) < 0.01


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
