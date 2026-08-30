"""投資部門別売買フローの共有定義 (旧 tabs/tab_market.py から切り出し)

J-Quants v2 投資部門別売買の Bal カラム表示名・配色と連続買越/売越の集計。
利用者: api/service.py (/api/market/investor-flow)
"""

INVESTOR_LABELS = {
    "FrgnBal": "海外投資家",
    "IndBal": "個人",
    "TrstBnkBal": "信託銀行",
    "InvTrBal": "投資信託",
    "BusCoBal": "事業法人",
    "InsCoBal": "生損保",
    "BankBal": "都銀・地銀",
    "PropBal": "自己",
}
INVESTOR_COLORS = {
    "FrgnBal": "#00D2FF",
    "IndBal": "#FFD54F",
    "TrstBnkBal": "#B388FF",
    "InvTrBal": "#69F0AE",
    "BusCoBal": "#FF7043",
    "InsCoBal": "#90A4AE",
    "BankBal": "#7986CB",
    "PropBal": "#A1887F",
}


def flow_streak(series):
    """直近から同符号(買越/売越)が何週連続しているかと、その間の累計額を返す。"""
    s = series.dropna()
    if s.empty or s.iloc[-1] == 0:
        return None
    sign = 1 if s.iloc[-1] > 0 else -1
    n, cum = 0, 0.0
    for v in reversed(s.tolist()):
        if v * sign > 0:
            n += 1
            cum += float(v)
        else:
            break
    return {"sign": sign, "weeks": n, "cum": cum, "latest": float(s.iloc[-1])}
