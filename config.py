"""定数・設定の一元管理"""
import logging

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("portfolio")

EXPECTED_COLS = [
    "銘柄コード", "銘柄名", "市場", "保有株数", "取得単価",
    "口座", "口座区分", "手動配当利回り(%)", "配当月",
    "年間配当金(円/株)", "取得時為替", "手動現在値", "最新更新日",
]
BROKER_OPTIONS = ["SBI証券", "楽天証券", "持ち株会(野村證券)"]
TAX_OPTIONS = ["特定口座", "NISA(成長投資枠)", "NISA(積立投資枠)"]
MARKET_OPTIONS = ["日本株", "米国株", "投資信託", "その他資産"]
MONTH_OPTIONS = [f"{m}月" for m in range(1, 13)]
TAX_RATE = 0.20315
US_WITHHOLDING_TAX_RATE = 0.10  # 米国源泉徴収税率（10%）

# AI モデル（Secretsで上書き可能）
AI_MODEL_DEFAULT = "claude-sonnet-4-20250514"

# NISA 年間・生涯枠（2024年新NISA）
NISA_GROWTH_ANNUAL = 2_400_000      # 成長投資枠 年間上限
NISA_GROWTH_LIFETIME = 12_000_000   # 成長投資枠 生涯上限
NISA_TSUMITATE_ANNUAL = 1_200_000   # 積立投資枠 年間上限
NISA_TSUMITATE_LIFETIME = 6_000_000 # 積立投資枠 生涯上限
NISA_TOTAL_LIFETIME = 18_000_000    # 合計生涯上限

SECTOR_MAP = {
    "Technology": "テクノロジー", "Financial Services": "金融", "Healthcare": "ヘルスケア",
    "Consumer Cyclical": "一般消費財", "Industrials": "資本財", "Communication Services": "通信",
    "Consumer Defensive": "生活必需品", "Energy": "エネルギー", "Basic Materials": "素材",
    "Real Estate": "不動産", "Utilities": "公益事業",
}
WORLD_INDICES = {
    "日経平均": "^N225", "TOPIX": "1306.T", "S&P 500": "^GSPC", "NASDAQ": "^IXIC",
    "ドル円": "JPY=X", "米国10年債利回り": "^TNX", "VIX": "^VIX", "金(GOLD)": "GC=F",
}

def is_nisa(tax_category: str) -> bool:
    return "NISA" in str(tax_category)

def get_tax_rate(tax_category: str) -> float:
    return 0.0 if is_nisa(tax_category) else TAX_RATE

def normalize_broker(val: str) -> str:
    val = str(val)
    if "楽天" in val: return "楽天証券"
    if "野村" in val or "持ち株" in val: return "持ち株会(野村證券)"
    if "SBI" in val: return "SBI証券"
    return val.strip() if val.strip() else "SBI証券"

def normalize_tax(val: str) -> str:
    val = str(val)
    if "NISA" in val:
        return "NISA(積立投資枠)" if "積立" in val else "NISA(成長投資枠)"
    return "特定口座"
