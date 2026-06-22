"""定数・設定の一元管理"""
import logging

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("portfolio")

EXPECTED_COLS = [
    "銘柄コード", "銘柄名", "市場", "通貨", "保有株数", "取得単価",
    "口座", "口座区分", "手動配当利回り(%)", "配当月",
    "年間配当金(円/株)", "取得時為替", "手動現在値", "取得日", "最新更新日",
]
CURRENCY_OPTIONS = ["JPY", "USD"]
BROKER_OPTIONS = ["SBI証券", "楽天証券", "三菱UFJeスマート証券", "持ち株会(野村證券)",
                  "マネックス証券", "松井証券", "auカブコム証券", "野村證券",
                  "大和証券", "SMBC日興証券", "PayPay証券"]
TAX_OPTIONS = ["特定口座", "NISA(成長投資枠)", "NISA(積立投資枠)"]
MARKET_OPTIONS = ["日本株", "米国株", "投資信託", "暗号資産", "債券/国債", "コモディティ", "その他資産"]
MONTH_OPTIONS = [f"{m}月" for m in range(1, 13)]
TAX_RATE = 0.20315

# セッション有効期限（秒）— ログイン後この時間で自動ログアウト
SESSION_TTL_SEC = 8 * 3600  # 8時間

# AI モデル（変更時はここだけ修正）
AI_MODEL = "claude-sonnet-4-6"

# NISA 年間・生涯枠（2024年新NISA）
NISA_GROWTH_ANNUAL = 2_400_000      # 成長投資枠 年間上限
NISA_GROWTH_LIFETIME = 12_000_000   # 成長投資枠 生涯上限
NISA_TSUMITATE_ANNUAL = 1_200_000   # 積立投資枠 年間上限
NISA_TSUMITATE_LIFETIME = 6_000_000 # 積立投資枠 生涯上限
NISA_TOTAL_LIFETIME = 18_000_000    # 合計生涯上限

ACCT_BADGE_MAP = {
    "SBI証券": "acct-sbi", "楽天証券": "acct-rakuten",
    "三菱UFJeスマート証券": "acct-mufj", "持ち株会(野村證券)": "acct-nomura",
    "マネックス証券": "acct-monex", "松井証券": "acct-matsui",
    "auカブコム証券": "acct-au", "野村證券": "acct-nomura",
    "大和証券": "acct-daiwa", "SMBC日興証券": "acct-smbc",
    "PayPay証券": "acct-paypay",
}

SECTOR_MAP = {
    "Technology": "テクノロジー", "Financial Services": "金融", "Healthcare": "ヘルスケア",
    "Consumer Cyclical": "一般消費財", "Industrials": "資本財", "Communication Services": "通信",
    "Consumer Defensive": "生活必需品", "Energy": "エネルギー", "Basic Materials": "素材",
    "Real Estate": "不動産", "Utilities": "公益事業",
}
WORLD_INDICES = {
    "日経平均": "^N225", "TOPIX": "1306.T", "S&P 500": "^GSPC", "オルカン(ACWI)": "ACWI",
    "NASDAQ": "^IXIC", "ドル円": "JPY=X", "米国10年債利回り": "^TNX", "VIX": "^VIX", "金(GOLD)": "GC=F",
}

# ランクティア（資産額トロフィー）
RANK_TIERS = [
    # 〜1000万: 100万単位
    (1_000_000,   "CADET",      "#6B7D8D"),
    (2_000_000,   "PRIVATE",    "#7B8D9D"),
    (3_000_000,   "CORPORAL",   "#8B9DAD"),
    (4_000_000,   "SERGEANT",   "#5AAFC8"),
    (5_000_000,   "OFFICER",    "#3CBDD8"),
    (6_000_000,   "LIEUTENANT", "#20C8E0"),
    (7_000_000,   "CAPTAIN",    "#10CCE8"),
    (8_000_000,   "MAJOR",      "#00D0F0"),
    (9_000_000,   "COLONEL",    "#00D2FF"),
    (10_000_000,  "COMMANDER",  "#00E676"),
    # 1000万〜3000万: 500万単位
    (15_000_000,  "STRATEGIST", "#55DD55"),
    (20_000_000,  "EXECUTOR",   "#99DD33"),
    (25_000_000,  "DIRECTOR",   "#CCDD22"),
    (30_000_000,  "GENERAL",    "#FFD54F"),
    # 3000万〜1億: 1000万単位
    (40_000_000,  "ADMIRAL",    "#FFB830"),
    (50_000_000,  "MARSHAL",    "#FF9020"),
    (60_000_000,  "TITAN",      "#E070B0"),
    (70_000_000,  "MOGUL",      "#CC55CC"),
    (80_000_000,  "SOVEREIGN",  "#BB44DD"),
    (90_000_000,  "EMPEROR",    "#CC33EE"),
    (100_000_000, "LEGEND",     "#FF6EC7"),
]

def get_rank(total_asset: float):
    """資産額に応じたランク情報を返す。100万未満はNone。"""
    level = 0
    for threshold, _, _ in RANK_TIERS:
        if total_asset >= threshold:
            level += 1
        else:
            break
    if level == 0:
        return None
    _, name, color = RANK_TIERS[level - 1]
    return name, color, level, len(RANK_TIERS)


def is_nisa(tax_category: str) -> bool:
    return "NISA" in str(tax_category)

def get_tax_rate(tax_category: str) -> float:
    return 0.0 if is_nisa(tax_category) else TAX_RATE

def normalize_broker(val: str) -> str:
    val = str(val)
    if "楽天" in val: return "楽天証券"
    if "三菱" in val or "UFJ" in val or "eスマート" in val: return "三菱UFJeスマート証券"
    if "持ち株" in val: return "持ち株会(野村證券)"
    if "SBI" in val: return "SBI証券"
    if "マネックス" in val: return "マネックス証券"
    if "松井" in val: return "松井証券"
    if "カブコム" in val or val.lower().startswith("au"): return "auカブコム証券"
    if "野村" in val: return "野村證券"
    if "大和" in val: return "大和証券"
    if "SMBC" in val or "日興" in val: return "SMBC日興証券"
    if "paypay" in val.lower() or "ペイペイ" in val: return "PayPay証券"
    return val.strip() if val.strip() else "SBI証券"

def normalize_tax(val: str) -> str:
    val = str(val)
    if "NISA" in val:
        return "NISA(積立投資枠)" if "積立" in val else "NISA(成長投資枠)"
    return "特定口座"
