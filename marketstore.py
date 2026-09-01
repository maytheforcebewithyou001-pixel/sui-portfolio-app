"""市場データの更新ポリシー層 + 永続キャッシュ (P3-4)

背景: Cloud Run は min-instances=0 のためインメモリキャッシュが毎回消え、
ログインの度に yfinance/J-Quants の全量取得(20〜40秒)が走っていた。

ポリシー(岡部指定 2026-09-01 改定):
  - 自動更新は市場別の1日1回境界 — 日本市場(.T/^N225)は JST 18:00、
    米国市場・指数・為替(それ以外)は JST 06:00。境界を越えて古くなった
    セグメントだけライブ取得し、他方はキャッシュを供給する(部分更新)
  - 手動更新(force)は前回の実取得から30分以上あいている場合のみ全量取得。
    30分未満はキャッシュを返し、その旨を警告で伝える

永続化: 固定スプレッドシート(FC_MARKET_CACHE_SHEET_ID、既定はFC_SHEET_ID)の
`MarketCache` ワークシート。1行目=メタJSON(市場別取得時刻・info辞書)、2行目以降=
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
# 市場別の自動更新境界(JST)。日本=EODデータ反映後の18:00、米国=クローズ後の6:00
AUTO_REFRESH_BOUNDARIES = {"jp": (18, 0), "us": (6, 0)}
SEGMENTS = ("jp", "us")

# プロセス内キャッシュ(ウォームインスタンス用)。fetched は {"jp": dt, "us": dt}
_mem = {"closes": None, "info": None, "fetched": {}}


def segment_of(ticker: str) -> str:
    """ティッカーの所属市場セグメント。日本株(.T)と日経平均のみ jp、他は us 扱い"""
    return "jp" if ticker.endswith(".T") or ticker == "^N225" else "us"


def latest_boundary(now: datetime, seg: str) -> datetime:
    """now(JST aware)以前で最も新しい自動更新境界(セグメント別)を返す"""
    h, m = AUTO_REFRESH_BOUNDARIES[seg]
    b = now.replace(hour=h, minute=m, second=0, microsecond=0)
    if b > now:
        b -= timedelta(days=1)
    return b


def is_fresh(fetched_at, now=None, seg: str = "jp") -> bool:
    if fetched_at is None:
        return False
    now = now or datetime.now(JST)
    return fetched_at >= latest_boundary(now, seg)


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


def _parse_fetched(meta: dict) -> dict:
    """メタJSONから市場別取得時刻を復元。旧形式(単一fetched_at)は両セグメント扱い"""
    fetched = {}
    for seg in SEGMENTS:
        v = meta.get(f"fetched_at_{seg}")
        if v:
            fetched[seg] = datetime.fromisoformat(v)
    if not fetched and meta.get("fetched_at"):
        dt = datetime.fromisoformat(meta["fetched_at"])
        fetched = {seg: dt for seg in SEGMENTS}
    return fetched


def load_persistent():
    """Sheetsのキャッシュを (closes_df, info_dict, fetched: dict) で返す。無ければ (None, None, {})"""
    try:
        ws = _open_ws(create=False)
        if ws is None:
            return None, None, {}
        vals = ws.get_all_values()
        if len(vals) < 3:
            return None, None, {}
        meta = json.loads(vals[0][0])
        fetched = _parse_fetched(meta)
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
        return closes, info, fetched
    except Exception as e:
        logger.warning("MarketCache読み込み失敗(ライブ取得へフォールバック): %s", e)
        return None, None, {}


def save_persistent(closes: pd.DataFrame, info: dict, fetched: dict) -> None:
    """既存キャッシュと外部結合マージして保存(ユーザー毎に銘柄集合が違うため列は和集合で保持)"""
    try:
        old_closes, old_info, old_fetched = load_persistent()
        if old_closes is not None:
            keep = [c for c in old_closes.columns if c not in closes.columns]
            if keep:
                closes = closes.join(old_closes[keep], how="outer")
        merged_info = dict(old_info or {})
        merged_info.update(info or {})
        merged_fetched = dict(old_fetched or {})
        merged_fetched.update(fetched or {})

        ws = _open_ws(create=True)
        if ws is None:
            return
        closes = closes.sort_index().tail(300)  # 1y+マージンに丸めて肥大防止
        header = ["Date"] + list(closes.columns)
        body = [[str(d)[:10]] + ["" if pd.isna(v) else round(float(v), 6) for v in row]
                for d, row in zip(closes.index, closes.values)]
        meta = {f"fetched_at_{seg}": dt.isoformat() for seg, dt in merged_fetched.items()}
        meta["info"] = merged_info
        ws.clear()
        ws.update("A1", [[json.dumps(meta, ensure_ascii=False)]] + [header] + body, value_input_option="RAW")
        logger.info("MarketCache保存: %d日×%dティッカー", len(body), len(closes.columns))
    except Exception as e:
        logger.warning("MarketCache保存失敗(表示には影響なし): %s", e)


def _covers(closes: pd.DataFrame, info: dict, tickers) -> bool:
    """キャッシュが要求ティッカーを全てカバーしているか(infoはJPY=X等の非対象を除く)"""
    if closes is None:
        return False
    need_info = [t for t in tickers if t != "JPY=X" and not t.startswith("^")]
    return all(t in closes.columns for t in tickers) and all(t in (info or {}) for t in need_info)


def _seg_ok(closes, info, fetched: dict, seg: str, seg_tickers, now) -> bool:
    """セグメントの要求ティッカーがキャッシュで賄えるか(鮮度+カバレッジ)"""
    if not seg_tickers:
        return True
    return is_fresh(fetched.get(seg), now, seg) and _covers(closes, info, seg_tickers)


def _merge_closes(base: pd.DataFrame, fresh: pd.DataFrame) -> pd.DataFrame:
    """freshの列を正としてbaseの残り列を外部結合で保持"""
    if base is None:
        return fresh
    keep = [c for c in base.columns if c not in fresh.columns]
    return fresh.join(base[keep], how="outer") if keep else fresh


def _latest(fetched: dict):
    return max(fetched.values()) if fetched else None


def get_market_bundle(tickers_tuple, force: bool = False):
    """スナップショット用の市場データ取得(ポリシー適用)。

    Returns: (closes_df, info_dict, fetched_at, notice)
      fetched_at: 最後にライブ取得した時刻(セグメント別の最新)
      notice: force拒否時などにユーザーへ伝える文字列(なければNone)
    """
    import market  # 遅延import(循環import回避)

    now = datetime.now(JST)
    tickers = list(tickers_tuple)
    seg_tickers = {seg: [t for t in tickers if segment_of(t) == seg] for seg in SEGMENTS}
    notice = None

    # 1. プロセス内キャッシュ(全セグメント充足時のみ)
    if not force and _mem["closes"] is not None and all(
            _seg_ok(_mem["closes"], _mem["info"], _mem["fetched"], seg, seg_tickers[seg], now)
            for seg in SEGMENTS):
        return _mem["closes"], _mem["info"], _latest(_mem["fetched"]), None

    # 2. 永続キャッシュ(Sheets)
    p_closes, p_info, p_fetched = load_persistent()

    if force and p_fetched and _covers(p_closes, p_info, tickers):
        age_min = (now - _latest(p_fetched)).total_seconds() / 60
        if age_min < FORCE_MIN_INTERVAL_MIN:
            notice = (f"市場データは{_latest(p_fetched).astimezone(JST):%H:%M}取得のキャッシュを表示しています"
                      f"(手動更新は前回取得から{FORCE_MIN_INTERVAL_MIN}分経過後に有効)")
            _mem.update(closes=p_closes, info=p_info, fetched=dict(p_fetched))
            return p_closes, p_info, _latest(p_fetched), notice

    stale = [seg for seg in SEGMENTS if seg_tickers[seg] and (
        force or not _seg_ok(p_closes, p_info, p_fetched, seg, seg_tickers[seg], now))]

    if not stale:
        _mem.update(closes=p_closes, info=p_info, fetched=dict(p_fetched))
        return p_closes, p_info, _latest(p_fetched), None

    # 3. ライブ取得(自動=境界を越えたセグメントのみ / 手動30分経過=全量 / キャッシュ未整備分)
    closes, info, fetched = p_closes, dict(p_info or {}), dict(p_fetched or {})
    for seg in stale:
        t = tuple(sorted(seg_tickers[seg]))
        seg_closes = market.get_cached_market_data(t, period="1y")
        seg_info = market.get_cached_ticker_info(t)
        closes = _merge_closes(closes, seg_closes)
        info.update(seg_info or {})
        fetched[seg] = now
    _mem.update(closes=closes, info=info, fetched=dict(fetched))
    save_persistent(closes, info, {seg: fetched[seg] for seg in stale})
    return closes, info, _latest(fetched), None
