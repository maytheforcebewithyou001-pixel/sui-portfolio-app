import pytest
from calc import merge_position


class TestMergePosition:
    def test_weighted_average(self):
        total, price = merge_position(100, 2000, 50, 3000)
        assert total == 150
        assert price == pytest.approx((100 * 2000 + 50 * 3000) / 150)   # 2333.333...

    def test_new_position(self):
        assert merge_position(0, 0, 10, 500) == (10, 500.0)

    def test_zero_total_falls_back_to_add_price(self):
        total, price = merge_position(0, 0, 0, 1234)
        assert total == 0
        assert price == 1234
