"""
計算エンジン: 評価額・損益・配当・税金・シミュレーション

改善点:
  #5 AI総評に資産推移履歴を含める
"""
import pandas as pd
import math
from datetime import datetime
from config import get_tax_rate

def classify_sector(row, info_sector):
    if info_sector and info_sector not in ("不明", "ETF/その他", ""):
        return info_sector
    market, name = row["市場"], str(row["銘柄名"])
    if market == "投資信託":
        if "全世界" in name or "オール" in name: return "投信/全世界株式"
        if "S&P" in name or "米国" in name or "500" in name: return "投信/米国株式"
        if "新興国" in name: return "投信/新興国株式"
        if "高配当" in name: return "投信/高配当"
        if "債券" in name or "国債" in name: return "投信/債券"
        return "投信/その他"
    if market == "その他資産":
        if "国債" in name: return "国債"
        if "金" in name or "ゴールド" in name: return "コモディティ"
        return "その他資産"
    return "ETF/その他"

def calculate_holding(row, closes_df, info_dict, fund_prices, jpy_usd_rate):
    ticker_code = str(row["銘柄コード"])
    market_type = row["市場"]
    shares = float(row["保有株数"])
    buy_price_raw = float(row["取得単価"])
    tax_category = str(row.get("口座区分", "特定口座"))
    manual_yield = float(row.get("手動配当利回り(%)", 0.0))
    annual_div_per_share = float(row.get("年間配当金(円/株)", 0.0))
    buy_fx_rate = float(row.get("取得時為替", 0.0))

    t = f"{ticker_code}.T" if market_type == "日本株" else ticker_code
    info = info_dict.get(t, {})
    sector = classify_sector(row, info.get("sector", ""))
    price_jpy = buy_jpy = 0.0
    dod_pct = None
    fx_gain = stock_gain = 0.0
    fetch_success = False

    if market_type in ("日本株", "米国株") and t in closes_df.columns:
        series = closes_df[t].dropna()
        if not series.empty:
            latest_price = series.iloc[-1]
            fetch_success = True
            if market_type == "日本株":
                price_jpy, buy_jpy = latest_price, buy_price_raw
            else:
                price_jpy = latest_price * jpy_usd_rate
                buy_jpy = buy_price_raw * jpy_usd_rate
                if buy_fx_rate > 0:
                    stock_gain = (latest_price - buy_price_raw) * shares * jpy_usd_rate
                    fx_gain = buy_price_raw * shares * (jpy_usd_rate - buy_fx_rate)
            if len(series) >= 2:
                prev = series.iloc[-2]
                dod_pct = ((latest_price / prev) - 1) * 100 if prev != 0 else None
    elif market_type in ("日本株", "米国株"):
        # 一括DLで取得できなかった銘柄 → 個別にリトライ
        try:
            import yfinance as yf
            single = yf.download(t, period="5d", progress=False)
            if not single.empty:
                if isinstance(single.columns, pd.MultiIndex):
                    s_close = single["Close"][t].dropna()
                else:
                    s_close = single["Close"].dropna()
                if not s_close.empty:
                    latest_price = s_close.iloc[-1]
                    fetch_success = True
                    if market_type == "日本株":
                        price_jpy, buy_jpy = latest_price, buy_price_raw
                    else:
                        price_jpy = latest_price * jpy_usd_rate
                        buy_jpy = buy_price_raw * jpy_usd_rate
                        if buy_fx_rate > 0:
                            stock_gain = (latest_price - buy_price_raw) * shares * jpy_usd_rate
                            fx_gain = buy_price_raw * shares * (jpy_usd_rate - buy_fx_rate)
                    if len(s_close) >= 2:
                        prev = s_close.iloc[-2]
                        dod_pct = ((latest_price / prev) - 1) * 100 if prev != 0 else None
        except Exception:
            pass
        # それでも取得できなかった場合は取得単価をフォールバック
        if not fetch_success:
            price_jpy, buy_jpy, fetch_success = buy_price_raw, buy_price_raw, True
    else:
        if market_type == "投資信託" and ticker_code in fund_prices:
            price_jpy, buy_jpy, fetch_success = fund_prices[ticker_code], buy_price_raw, True
        else:
            price_jpy, buy_jpy, fetch_success = buy_price_raw, buy_price_raw, True

    value = price_jpy * shares
    profit = value - (buy_jpy * shares)

    div_rate = info.get("div_rate", 0.0)
    div_yield = info.get("div_yield", 0.0)
    if annual_div_per_share > 0:
        dividend = annual_div_per_share * shares * (jpy_usd_rate if market_type == "米国株" else 1)
    elif manual_yield > 0:
        dividend = value * (manual_yield / 100.0)
    elif div_rate > 0:
        dividend = div_rate * shares * (jpy_usd_rate if market_type == "米国株" else 1)
    else:
        dividend = value * div_yield

    tax_rate = get_tax_rate(tax_category)
    tax_amount = profit * tax_rate if profit > 0 else 0.0
    return {
        "セクター": sector, "取得単価(円)": buy_jpy, "現在値(円)": price_jpy,
        "前日比": dod_pct, "評価額(円)": value, "含み損益(円)": profit,
        "税引後損益(円)": profit - tax_amount, "予想配当(円)": dividend,
        "税引後配当(円)": dividend * (1 - tax_rate),
        "株価損益(円)": stock_gain, "為替損益(円)": fx_gain, "fetch_success": fetch_success,
    }

def calculate_portfolio(df, closes_df, info_dict, fund_prices, jpy_usd_rate):
    now_str = datetime.now().strftime("%Y/%m/%d %H:%M")
    results = []
    for _, row in df.iterrows():
        r = calculate_holding(row, closes_df, info_dict, fund_prices, jpy_usd_rate)
        r["手動配当利回り(%)"] = float(row.get("手動配当利回り(%)", 0.0))
        r["配当月"] = str(row.get("配当月", ""))
        r["最新更新日"] = now_str if r["fetch_success"] else str(row.get("最新更新日", "-"))
        results.append(r)
    result_df = pd.DataFrame(results)
    display_df = df.copy()
    display_df["最新更新日"] = result_df["最新更新日"].values
    for col in ["セクター", "取得単価(円)", "現在値(円)", "前日比", "評価額(円)",
                "含み損益(円)", "税引後損益(円)", "予想配当(円)", "税引後配当(円)",
                "株価損益(円)", "為替損益(円)", "手動配当利回り(%)", "配当月"]:
        display_df[col] = result_df[col].values
    return display_df

def get_portfolio_totals(display_df):
    ta = display_df["評価額(円)"].sum()
    return {
        "total_asset": ta,
        "total_net_profit": display_df["税引後損益(円)"].sum(),
        "total_dividend": display_df["予想配当(円)"].sum(),
        "total_dividend_after_tax": display_df["税引後配当(円)"].sum(),
        "total_fx_gain": display_df["為替損益(円)"].sum(),
        "total_stock_gain": display_df["株価損益(円)"].sum(),
        "avg_dividend_yield": (display_df["予想配当(円)"].sum() / ta * 100) if ta > 0 else 0.0,
        "stock_count": len(display_df),
    }

def get_future_simulation(current_asset, annual_rate, years, yearly_addition):
    months = years * 12
    monthly_rate = annual_rate / 12
    monthly_add = yearly_addition / 12
    today = datetime.now()
    dates, values, principals, gains = [], [], [], []
    cv, cp = current_asset, current_asset
    for i in range(months + 1):
        dates.append(today + pd.DateOffset(months=i))
        values.append(cv); principals.append(cp); gains.append(max(cv - cp, 0))
        cv = cv * (1 + monthly_rate) + monthly_add
        cp += monthly_add
    return pd.DataFrame({"日時": dates, "予測評価額(円)": values, "積立元本(円)": principals, "運用益(円)": gains})

def round_up_3(val):
    try:
        val = float(val)
        rounded = math.ceil(val * 1000) / 1000
        return f"{int(rounded):,}" if rounded.is_integer() else f"{rounded:,.3f}".rstrip("0").rstrip(".")
    except (ValueError, TypeError): return val

def build_portfolio_summary_text(display_df, totals, jpy_usd_rate, history_df=None):
    """#5 AI総評用サマリー — 資産推移履歴も含める"""
    ta = totals["total_asset"]
    lines = [
        "■ ポートフォリオ概要",
        f"  評価額合計: {ta:,.0f}円", f"  税引後含み損益: {totals['total_net_profit']:,.0f}円",
        f"  年間予想配当（税引前）: {totals['total_dividend']:,.0f}円",
        f"  配当利回り: {totals['avg_dividend_yield']:.2f}%",
        f"  為替レート: $1 = ¥{jpy_usd_rate:.1f}", f"  銘柄数: {totals['stock_count']}", "",
        "■ 保有銘柄一覧",
    ]
    for _, row in display_df.iterrows():
        val = row.get("評価額(円)", 0)
        pct = (val / ta * 100) if ta > 0 else 0
        dod = row.get("前日比", None)
        dod_s = f"前日比{dod:+.1f}%" if pd.notna(dod) else ""
        lines.append(f"  {row.get('銘柄コード','')} {row.get('銘柄名','')} [{row.get('市場','')}/{row.get('セクター','')}] "
                     f"評価額:{val:,.0f}円({pct:.1f}%) 損益:{row.get('税引後損益(円)',0):+,.0f}円 {dod_s} "
                     f"配当:{row.get('予想配当(円)',0):,.0f}円")
    lines += ["", "■ セクター配分"]
    for sec, val in display_df[display_df["評価額(円)"] > 0].groupby("セクター")["評価額(円)"].sum().sort_values(ascending=False).items():
        lines.append(f"  {sec}: {val:,.0f}円 ({val/ta*100:.1f}%)")

    # #5 資産推移履歴を追加（直近10件）
    if history_df is not None and not history_df.empty:
        lines += ["", "■ 資産推移（直近の記録）"]
        recent = history_df.tail(10)
        for _, hr in recent.iterrows():
            lines.append(f"  {hr['日付']}: {hr['総資産額(円)']:,.0f}円")
        if len(history_df) >= 2:
            first_val = history_df["総資産額(円)"].iloc[0]
            last_val = history_df["総資産額(円)"].iloc[-1]
            if first_val > 0:
                change_pct = (last_val / first_val - 1) * 100
                lines.append(f"  記録期間の変化: {change_pct:+.1f}%")

    return "\n".join(lines)
