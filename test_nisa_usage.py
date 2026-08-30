"""calc_nisa_usage の特性テスト（NISA枠の投信÷10,000換算を凍結）"""
import pandas as pd
import pytest
from calc import calc_nisa_usage

YEAR = 2026

def _tx(rows):
    cols = ["日付", "銘柄コード", "銘柄名", "市場", "取引種別", "数量", "単価(円)", "手数料", "損益確定(円)", "口座", "口座区分"]
    return pd.DataFrame(rows, columns=cols)


class TestCalcNisaUsage:
    def test_growth_stock_full_amount(self):
        tx = _tx([[f"{YEAR}/03/01", "7203", "トヨタ", "日本株", "新規購入", 100, 3000, 0, 0, "SBI証券", "NISA(成長投資枠)"]])
        g, t = calc_nisa_usage(tx, YEAR)
        assert g == pytest.approx(300_000)
        assert t == pytest.approx(0)

    def test_tsumitate_fund_divided_by_10000(self):
        # つみたて枠(条件②)。41,234口 × 25,000円(1万口あたり) ÷ 10,000 = 103,085円
        tx = _tx([[f"{YEAR}/04/01", "", "ｅＭＡＸＩＳ Ｓｌｉｍ 全世界株式", "-", "買い増し", 41234, 25000, 0, 0, "SBI証券", "NISA(積立投資枠)"]])
        g, t = calc_nisa_usage(tx, YEAR)
        assert t == pytest.approx(103_085.0)

    def test_growth_fund_by_market_column(self):
        # 成長枠でも市場=投資信託(条件①)なら÷10,000
        tx = _tx([[f"{YEAR}/01/10", "", "何かの株式コース", "投資信託", "新規購入", 10000, 15000, 0, 0, "SBI証券", "NISA(成長投資枠)"]])
        g, t = calc_nisa_usage(tx, YEAR)
        assert g == pytest.approx(15_000.0)

    def test_growth_fund_by_name_nfkc(self):
        # 市場が"-"でも銘柄コード非数字＋銘柄名(全角→NFKC)に「ファンド」(条件③)
        tx = _tx([[f"{YEAR}/02/01", "", "グローバル株式ファンド", "-", "買い増し", 20000, 12000, 0, 0, "SBI証券", "NISA(成長投資枠)"]])
        g, t = calc_nisa_usage(tx, YEAR)
        assert g == pytest.approx(24_000.0)      # 20000*12000/10000

    def test_excludes_sell_taxable_and_other_year(self):
        tx = _tx([
            [f"{YEAR}/03/01", "7203", "トヨタ", "日本株", "売却", 100, 3000, 0, 0, "SBI証券", "NISA(成長投資枠)"],
            [f"{YEAR}/03/01", "7203", "トヨタ", "日本株", "新規購入", 100, 3000, 0, 0, "SBI証券", "特定口座"],
            [f"{YEAR-1}/03/01", "7203", "トヨタ", "日本株", "新規購入", 100, 3000, 0, 0, "SBI証券", "NISA(成長投資枠)"],
        ])
        assert calc_nisa_usage(tx, YEAR) is None   # NISA買いの当年行が0件

    def test_empty_returns_none(self):
        assert calc_nisa_usage(pd.DataFrame(), YEAR) is None
        assert calc_nisa_usage(None, YEAR) is None
