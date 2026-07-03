import sys
from unittest.mock import MagicMock
sys.modules.setdefault("streamlit", MagicMock())

import io
import pytest
from tabs.tab_transaction import _parse_broker_csv


def _file(text: str, enc="cp932"):
    return io.BytesIO(text.encode(enc))


class TestParseBrokerCsv:
    def test_sbi(self):
        text = (
            "ダミー前置き行\n"
            "約定日,銘柄コード,銘柄,市場,取引,預り,課税,約定数量,約定単価,手数料/諸経費等,受渡金額/決済損益\n"
            "2026/01/15,7203,トヨタ自動車,東証,株式現物買,特定預り,課税,100,3000,275,299725\n"
            "2026/02/10,7203,トヨタ自動車,東証,株式現物売,特定預り,課税,50,3200,275,159725\n"
        )
        df, broker, err = _parse_broker_csv(_file(text))
        assert err is None and broker == "SBI証券"
        assert list(df["_取引種別"]) == ["買い増し", "売却"]
        assert list(df["_口座区分"]) == ["特定口座", "特定口座"]
        assert list(df["_qty"]) == [100.0, 50.0]
        assert list(df["_price"]) == [3000.0, 3200.0]

    def test_rakuten(self):
        text = (
            "約定日,銘柄コード,銘柄名,市場名称,口座区分,売買区分,数量［株］,単価［円］,手数料［円］,受渡金額［円］\n"
            "2026/03/01,7203,トヨタ自動車,東証,NISA,買付,10,3100,0,31000\n"
        )
        df, broker, err = _parse_broker_csv(_file(text))
        assert err is None and broker == "楽天証券"
        assert df["_取引種別"].iloc[0] == "買い増し"
        assert df["_口座区分"].iloc[0] == "NISA(成長投資枠)"
        assert df["_qty"].iloc[0] == 10.0

    def test_mufj_fund(self):
        text = (
            "約定日,ファンド名,売買,課税区分,数量,約定単価,受渡金額,手数料(税込),売買損益\n"
            "2026/04/01,ｅＭＡＸＩＳ Ｓｌｉｍ 全世界株式,買付,つみたてNISA,41234,25000,103085,0,0\n"
        )
        df, broker, err = _parse_broker_csv(_file(text))
        assert err is None and broker == "三菱UFJeスマート証券"
        assert df["_口座区分"].iloc[0] == "NISA(積立投資枠)"
        assert df["_market"].iloc[0] == "投資信託"
        assert df["_code"].iloc[0] == ""
        assert df["_qty"].iloc[0] == 41234.0

    def test_no_header_returns_error(self):
        df, broker, err = _parse_broker_csv(_file("これはCSVではない\nただのテキスト\n"))
        assert df is None and err is not None
