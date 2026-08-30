"""市場データの更新ポリシー層 + 永続キャッシュ (P3-4)

背景: Cloud Run は min-instances=0 のためインメモリキャッシュが毎回消え、
ログインの度に yfinance/J-Quants の全量取得(20〜40秒)が走っていた。

ポリシー(岡部指定 2026-08-16):
  - 自動更新は1日2回のみ — JST 06:10(米国市場クローズ後)と 15:40(日本市場クローズ後)。
    取得時刻が直近の境界より新しければキャッシュを供給する
  - 手動更新(force)は前回の実取得から30分以上あいている場合のみ実取得。
    30分未満はキャッシュを返し、その旨を警告で伝える

永続化: 固定スプレッドシート(FC_MARKET_CACHE_SHEET_ID、既定はFC_SHEET_ID)の
`MarketCache` ワークシート。1行目=メタJSON(取得時刻・info辞書)、2行目以降=
日付×ティッカーの終値グリッド。ユーザー間で共有される公開市場データのみを置く。
対象はスナップショット経路(period=1y)のみ — 銘柄詳細等のオンデマンド取得は対象外。
"""
import json
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from config import logger

JST = ZoneInfo("Asia/Tokyo")
WS_NAME = "MarketCache"
FORCE_MIN_INTERVAL_MIN = 30
# 自動更新の境界時刻(JST)。米国クローズ後(EST/EDT両対応で余裕を持たせた6:10)と日本クローズ後
AUTO_REFRESH_TIMES = [(6, 10), (15, 40)]

# プロセス内キャッシュ(ウォームインスタンス用)
_mem = {"closes": None, "info": None, "fetched_at": None}


def latest_boundary(now: datetime) -> datetime:
    """now(JST aware)以前で最も新しい自動更新境界を返す"""
    candidates = []
    for d in (0, 1):
        day = now - timedelta(days=d)
        for h, m in AUTO_REFRESH_TIMES:
            b = day.replace(hour=h, minute=m, second=0, microsecond=0)
            if b <= now:
                candidates.append(b)
    return max(candidates)


def is_fresh(fetched_at, now=None) -> bool:
    if fetched_at is None:
        return False
    now = now or datetime.now(JST)
    return fetched_at >= latest_boundary(now)


def _cache_sheet_id():
    return os.environ.get("FC_MARKET_CACHE_SHEET_ID", "") or os.environ.get("FC_SHEET_ID", "")


def _open_ws(create=False):
    sheet_id = _cache_sheet_id()
    if not sheet_id:
        return None
    from data import init_gspread
    import gspread
    gc = init_gspread()
    if gc is None:
        return None
    sh = gc.open_by_key(sheet_id)
    try:
        return sh.worksheet(WS_NAME)
    except gspread.exceptions.WorksheetNotFound:
        if not create:
            return None
        return sh.add_worksheet(title=WS_NAME, rows="400", cols="60")


def load_persistent():
    """Sheetsのキャッシュを (closes_df, info_dict, fetched_at) で返す。無ければ (None, None, None)"""
    try:
        ws = _open_ws(create=False)
        if ws is None:
            return None, None, None
        vals = ws.get_all_values()
        if len(vals) < 3:
            return None, None, None
        meta = json.loads(vals[0][0])
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
        info = meta.get("info", {})
        header = vals[1]  # ["Date", ticker1, ...]
        rows = [r for r in vals[2:] if r and r[0].strip()]
        idx = pd.to_datetime([r[0] for r in rows])
        datadict = {}
        for ci, t in enumerate(header[1:], start=1):
            if not t.strip():
                continue
            datadict[t] = [float(r[ci]) if ci < len(r) and r[ci].strip() else float("nan") for r in rows]
        closes = pd.DataFrame(datadict, index=idx)
        return closes, info, fetched_at
    except Exception as e:
        logger.warning("MarketCache読み込み失敗(ライブ取得へフォールバック): %s", e)
        return None, None, None


def save_persistent(closes: pd.DataFrame, info: dict, fetched_at: datetime) -> None:
    """既存キャッシュと外部結合マージして保存(ユーザー毎に銘柄集合が違うため列は和集合で保持)"""
    try:
        old_closes, old_info, _ = load_persistent()
        if old_closes is not None:
            keep = [c for c in old_closes.columns if c not in closes.columns]
            if keep:
                closes = closes.join(old_closes[keep], how="outer")
        merged_info = dict(old_info or {})
        merged_info.update(info or {})

        ws = _open_ws(create=True)
        if ws is None:
            return
        closes = closes.sort_index().tail(300)  # 1y+マージンに丸めて肥大防止
        header = ["Date"] + list(closes.columns)
        body = [[str(d)[:10]] + ["" if pd.isna(v) else round(float(v), 6) for v in row]
                for d, row in zip(closes.index, closes.values)]
        meta = json.dumps({"fetched_at": fetched_at.isoformat(), "info": merged_info}, ensure_ascii=False)
        ws.clear()
        ws.update("A1", [[meta]] + [header] + body, value_input_option="RAW")
        logger.info("MarketCache保存: %d日×%dティッカー", len(body), len(closes.columns))
    except Exception as e:
        logger.warning("MarketCache保存失敗(表示には影響なし): %s", e)


def _covers(closes: pd.DataFrame, info: dict, tickers) -> bool:
    """キャッシュが要求ティッカーを全てカバーしているか(infoはJPY=X等の非対象を除く)"""
    if closes is None:
        return False
    need_info = [t for t in tickers if t != "JPY=X" and not t.startswith("^")]
    return all(t in closes.columns for t in tickers) and all(t in (info or {}) for t in need_info)


def get_market_bundle(tickers_tuple, force: bool = False):
    """スナップショット用の市場データ取得(ポリシー適用)。

    Returns: (closes_df, info_dict, fetched_at, notice)
      notice: force拒否時などにユーザーへ伝える文字列(なければNone)
    """
    import market  # 遅延import(循環import回避)

    now = datetime.now(JST)
    tickers = list(tickers_tuple)
    notice = None

    # 1. プロセス内キャッシュ
    if not force and is_fresh(_mem["fetched_at"], now) and _covers(_mem["closes"], _mem["info"], tickers):
        return _mem["closes"], _mem["info"], _mem["fetched_at"], None

    # 2. 永続キャッシュ(Sheets)
    p_closes, p_info, p_fetched = load_persistent()
    covered = _covers(p_closes, p_info, tickers)

    if force and p_fetched is not None and covered:
        age_min = (now - p_fetched).total_seconds() / 60
        if age_min < FORCE_MIN_INTERVAL_MIN:
            notice = (f"市場データは{p_fetched.astimezone(JST):%H:%M}取得のキャッシュを表示しています"
                      f"(手動更新は前回取得から{FORCE_MIN_INTERVAL_MIN}分経過後に有効)")
            _mem.update(closes=p_closes, info=p_info, fetched_at=p_fetched)
            return p_closes, p_info, p_fetched, notice

    if not force and is_fresh(p_fetched, now) and covered:
        _mem.update(closes=p_closes, info=p_info, fetched_at=p_fetched)
        return p_closes, p_info, p_fetched, None

    # 3. ライブ取得(自動=境界越え or 手動30分経過 or キャッシュ未整備/ティッカー不足)
    closes = market.get_cached_market_data(tuple(sorted(tickers)), period="1y")
    info = market.get_cached_ticker_info(tuple(sorted(tickers)))
    fetched_at = now
    _mem.update(closes=closes, info=info, fetched_at=fetched_at)
    save_persistent(closes, info, fetched_at)
    return closes, info, fetched_at, None
