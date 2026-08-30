"""業績推移の共有ロジック (旧 tabs/tab_portfolio.py から切り出し)

J-Quants 財務サマリ時系列の表示用整形と業績修正検出。
利用者: api/service.py (/api/stock/detail)
"""
import pandas as pd

_FIN_ALIASES = {
    "date": ("DiscDate", "DisclosedDate"),
    "period": ("CurPerType", "TypeOfCurrentPeriod"),
    "売上": ("Sales", "NetSales"),
    "営業利益": ("OP", "OperatingProfit"),
    "純利益": ("NP", "Profit"),
    "EPS": ("EPS", "EarningsPerShare"),
    "f_sales": ("FSales", "ForecastNetSales"),
    "f_profit": ("FNP", "ForecastProfit"),
}


def build_fin_view(fin_hist):
    """財務サマリ時系列を表示用に整形し (rows, metrics, revisions) を返す。

    - カラム名はJ-Quants V2短縮名(Sales/OP/NP/EPS/CurPerType)を優先しV1名にフォールバック
      (V1名のみ参照していた旧実装はV2移行後サイレントに非表示だった)
    - rows: [{"label": "2026/08 (3Q)", "売上": 737.07(億円), ..., "EPS": 359.8(円)}]
    - 実績vs予想売上の乖離判定は通期(FY)行のみ — 四半期行は累計実績と通期予想の
      比較になり必ず偽の「下振れ」が出るため
    """
    if fin_hist is None or fin_hist.empty:
        return [], [], []
    fin_hist = fin_hist.copy()

    def col(key):
        return next((c for c in _FIN_ALIASES[key] if c in fin_hist.columns), None)

    date_col, period_col = col("date"), col("period")
    available = [(col(label), label) for label in ("売上", "営業利益", "純利益", "EPS") if col(label)]
    rows, metrics = [], []
    if date_col and available:
        for k, _ in available:
            fin_hist[k] = pd.to_numeric(fin_hist[k], errors="coerce")
        xlabel = pd.to_datetime(fin_hist[date_col]).dt.strftime("%Y/%m")
        if period_col:
            xlabel = xlabel + " (" + fin_hist[period_col].astype(str) + ")"
        for i in range(len(fin_hist)):
            row = {"label": xlabel.iloc[i]}
            for k, label in available:
                v = fin_hist[k].iloc[i]
                # 売上/利益は億円換算、EPSは円のまま
                row[label] = None if pd.isna(v) else round(float(v) / 1e8, 2) if label != "EPS" else round(float(v), 2)
            rows.append(row)
        metrics = [label for _, label in available]

    rev_msgs = []
    fs_col, sales_col, fp_col = col("f_sales"), col("売上"), col("f_profit")
    is_fy = (str(fin_hist.iloc[-1].get(period_col, "")) == "FY") if period_col else False
    if fs_col and sales_col and is_fy:
        last = fin_hist.iloc[-1]
        fc = pd.to_numeric(last.get(fs_col), errors="coerce")
        ac = pd.to_numeric(last.get(sales_col), errors="coerce")
        if pd.notna(fc) and pd.notna(ac) and fc > 0:
            diff = (ac / fc - 1) * 100
            if abs(diff) >= 3:
                rev_msgs.append(f"{'🟢 上振れ' if diff > 0 else '🔴 下振れ'}：直近期の売上が予想比 {diff:+.1f}%")
    if fp_col and len(fin_hist) >= 2:
        prev_fc = pd.to_numeric(fin_hist.iloc[-2].get(fp_col), errors="coerce")
        curr_fc = pd.to_numeric(fin_hist.iloc[-1].get(fp_col), errors="coerce")
        if pd.notna(prev_fc) and pd.notna(curr_fc) and prev_fc != 0:
            rev = (curr_fc / abs(prev_fc) - (1 if prev_fc > 0 else -1)) * 100
            if abs(rev) >= 5:
                rev_msgs.append(f"{'🟢 通期純利益予想を上方修正' if rev > 0 else '🔴 通期純利益予想を下方修正'}：前回比 {rev:+.1f}%")
    return rows, metrics, rev_msgs
