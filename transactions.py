"""取引記録・証券会社CSV取込の共有ロジック (旧 tabs/tab_transaction.py から切り出し)

SBI証券/楽天証券/三菱UFJeスマート証券の約定履歴CSVパースと、
手動取引の記録(保有df更新+TransactionData追記)。
利用者: api/service.py (/api/transactions 系)
"""
import io

import pandas as pd

from calc import merge_position
from data import save_data, save_transaction, save_transactions_batch, _clear_sheet_cache


def _decode_broker_csv(raw: bytes):
    """バイト列を decode。UTF-8 BOM付き(三菱UFJ等)は最優先で判定し、
    無ければ shift_jis→cp932→utf-8-sig→utf-8 の順で試す。全滅なら None。
    ※cp932 は UTF-8 バイト列も例外を出さず文字化けデコードするため、BOM 判定を先に置く"""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    csv_text = None
    for enc in ["shift_jis", "cp932", "utf-8-sig", "utf-8"]:
        try: csv_text = raw.decode(enc); break
        except Exception: continue
    return csv_text


def _normalize_mufj(csv_df):
    """三菱UFJeスマート証券(投信 注文履歴)を統一カラム(_name/_qty/_price/_fee/_code/_market/_取引種別/_口座区分)へ。
    実際の注文履歴CSVは 取引種別/預り区分/約定数量、旧想定は 売買/課税区分/数量 — 双方に対応"""
    buy_col = "取引種別" if "取引種別" in csv_df.columns else "売買"
    tax_col = "預り区分" if "預り区分" in csv_df.columns else "課税区分"
    qty_col = "約定数量" if "約定数量" in csv_df.columns else "数量"

    # 約定済みの明細のみ取り込む（取消済・失効・注文中を除外）
    if "注文状況" in csv_df.columns:
        csv_df = csv_df[csv_df["注文状況"].astype(str).str.contains("完了|約定")].copy()

    csv_df["_取引種別"] = csv_df[buy_col].apply(lambda v: "売却" if ("売" in str(v) or "解約" in str(v)) else "買い増し")
    def _tax_mufj(v):
        v = str(v)
        if "つみたて" in v or "積立" in v: return "NISA(積立投資枠)"
        if "NISA" in v or "成長" in v: return "NISA(成長投資枠)"
        return "特定口座"
    csv_df["_口座区分"] = csv_df[tax_col].apply(_tax_mufj)
    if "手数料(税込)" not in csv_df.columns:
        csv_df["手数料(税込)"] = 0
    for nc in [qty_col, "約定単価", "受渡金額", "手数料(税込)", "売買損益"]:
        if nc in csv_df.columns:
            csv_df[nc] = csv_df[nc].astype(str).str.replace(",", "").str.replace("-", "0")
            csv_df[nc] = pd.to_numeric(csv_df[nc], errors="coerce").fillna(0)
    csv_df = csv_df.rename(columns={"ファンド名": "_name", qty_col: "_qty",
                                     "約定単価": "_price", "手数料(税込)": "_fee"})
    csv_df["_code"] = ""
    csv_df["_market"] = "投資信託"
    return csv_df


def _normalize_rakuten(csv_df):
    """楽天証券を統一カラムへ"""
    # 楽天証券フォーマット
    csv_df["_取引種別"] = csv_df["売買区分"].apply(lambda v: "売却" if "売" in str(v) else "買い増し")
    def _tax_rakuten(v):
        v = str(v)
        if "NISA" in v and "積立" in v: return "NISA(積立投資枠)"
        if "NISA" in v: return "NISA(成長投資枠)"
        return "特定口座"
    csv_df["_口座区分"] = csv_df["口座区分"].apply(_tax_rakuten)
    for nc in ["数量［株］", "単価［円］", "手数料［円］", "受渡金額［円］"]:
        if nc in csv_df.columns:
            csv_df[nc] = csv_df[nc].astype(str).str.replace(",", "").str.replace("-", "0")
            csv_df[nc] = pd.to_numeric(csv_df[nc], errors="coerce").fillna(0)
    # 統一カラム名にリネーム
    csv_df = csv_df.rename(columns={"銘柄コード": "_code", "銘柄名": "_name", "市場名称": "_market",
                                     "数量［株］": "_qty", "単価［円］": "_price", "手数料［円］": "_fee"})
    return csv_df


def _normalize_sbi(csv_df):
    """SBI証券を統一カラムへ"""
    # SBI証券フォーマット
    csv_df["_取引種別"] = csv_df["取引"].apply(lambda v: "売却" if "売" in str(v) or "解約" in str(v) else "買い増し")
    def _tax_sbi(v):
        v = str(v)
        if "つ" in v or "つみたて" in v or "旧つみたて" in v: return "NISA(積立投資枠)"
        if "成" in v or "NISA" in v: return "NISA(成長投資枠)"
        return "特定口座"
    csv_df["_口座区分"] = csv_df["預り"].apply(_tax_sbi)
    for nc in ["約定数量", "約定単価", "受渡金額/決済損益", "手数料/諸経費等"]:
        if nc in csv_df.columns:
            csv_df[nc] = csv_df[nc].astype(str).str.replace(",", "").str.replace("--", "0")
            csv_df[nc] = pd.to_numeric(csv_df[nc], errors="coerce").fillna(0)
    csv_df = csv_df.rename(columns={"銘柄コード": "_code", "銘柄": "_name", "市場": "_market",
                                     "約定数量": "_qty", "約定単価": "_price", "手数料/諸経費等": "_fee"})
    return csv_df


def _parse_broker_csv(csv_file):
    """SBI証券/楽天証券の約定履歴CSVを自動判別しパース。統一カラムで返す"""
    raw = csv_file.read()
    csv_text = _decode_broker_csv(raw)
    if csv_text is None: return None, None, "ファイルのエンコーディングを判別できませんでした。"

    lines = csv_text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        # 三菱UFJ(投信 注文履歴)は日付列が「発注日」、株式系は「約定日」
        if ("約定日" in line or "発注日" in line) and ("銘柄" in line or "ファンド名" in line): header_idx = i; break
    if header_idx is None: return None, None, "ヘッダー行が見つかりませんでした。"

    body_text = "\n".join(lines[header_idx:])
    csv_df = pd.read_csv(io.StringIO(body_text), encoding_errors="ignore")
    # 発注日しか無いフォーマットは約定日に寄せて以降の処理を共通化
    if "約定日" not in csv_df.columns and "発注日" in csv_df.columns:
        csv_df = csv_df.rename(columns={"発注日": "約定日"})
    csv_df = csv_df.dropna(subset=["約定日"], how="all")
    csv_df = csv_df[csv_df["約定日"].astype(str).str.match(r"^\d{4}/")]
    if csv_df.empty: return None, None, "有効な約定データが見つかりませんでした。"

    for col in csv_df.columns:
        if csv_df[col].dtype == object:
            csv_df[col] = csv_df[col].astype(str).str.strip()

    # ── 証券会社を自動判別 ──
    is_rakuten = "売買区分" in csv_df.columns
    is_mufj = "ファンド名" in csv_df.columns
    broker = "三菱UFJeスマート証券" if is_mufj else ("楽天証券" if is_rakuten else "SBI証券")

    if is_mufj:
        csv_df = _normalize_mufj(csv_df)
    elif is_rakuten:
        csv_df = _normalize_rakuten(csv_df)
    else:
        csv_df = _normalize_sbi(csv_df)

    # コード正規化
    csv_df["_code"] = csv_df["_code"].astype(str).str.strip()
    csv_df.loc[csv_df["_code"].isin(["nan", ""]), "_code"] = ""

    return csv_df, broker, None


def record_transaction(df, i, tx_type, date_str, qty, price, fee, broker, tax):
    """手動取引の記録(保有df更新+TransactionData追記)。
    戻り値: pnl_realized(売却時の確定損益)"""
    tx_code = str(df.at[i, "銘柄コード"])
    tx_name = str(df.at[i, "銘柄名"])
    cur_shares = float(df.at[i, "保有株数"])
    cur_price = float(df.at[i, "取得単価"])
    pnl_realized = 0.0
    if tx_type == "売却":
        df.at[i, "保有株数"] = max(cur_shares - qty, 0)
        pnl_realized = (price - cur_price) * qty
    else:
        new_total, new_price = merge_position(cur_shares, cur_price, qty, price)
        df.at[i, "取得単価"] = new_price
        df.at[i, "保有株数"] = new_total
    save_data(df)
    save_transaction({"日付": date_str, "銘柄コード": tx_code, "銘柄名": tx_name,
                      "市場": df.at[i, "市場"] if "市場" in df.columns else "-",
                      "取引種別": tx_type, "数量": qty, "単価(円)": price,
                      "手数料": fee, "損益確定(円)": round(pnl_realized, 0),
                      "口座": broker, "口座区分": tax})
    _clear_sheet_cache()
    return pnl_realized


def apply_csv_import(csv_df, broker, imp_mode, df):
    """CSV取込の実行(取引履歴登録/保有更新)。
    戻り値: (tx_count, upd_count, skip_count)"""
    tx_count, upd_count, skip_count = 0, 0, 0
    if imp_mode in ("取引履歴に登録", "両方（取引履歴＋保有銘柄更新）"):
        tx_batch = []
        for _, crow in csv_df.iterrows():
            code = crow["_code"]
            market = str(crow.get("_market", "")).replace("nan", "-") or "-"
            tx_batch.append({"日付": str(crow["約定日"]), "銘柄コード": code,
                             "銘柄名": str(crow.get("_name", "")).strip(),
                             "市場": market, "取引種別": crow["_取引種別"],
                             "数量": crow["_qty"], "単価(円)": crow["_price"],
                             "手数料": crow.get("_fee", 0), "損益確定(円)": 0,
                             "口座": broker, "口座区分": crow["_口座区分"]})
        save_transactions_batch(tx_batch)
        tx_count = len(tx_batch)
    if imp_mode in ("保有銘柄の数量を更新", "両方（取引履歴＋保有銘柄更新）"):
        for _, crow in csv_df.iterrows():
            code = crow["_code"]
            if not code:
                skip_count += 1; continue
            qty, price = float(crow["_qty"]), float(crow["_price"])
            idx = df[df["銘柄コード"].astype(str) == code].index
            if len(idx) == 0:
                skip_count += 1; continue
            cur_s, cur_p = float(df.at[idx[0], "保有株数"]), float(df.at[idx[0], "取得単価"])
            if crow["_取引種別"] == "売却":
                df.at[idx[0], "保有株数"] = max(cur_s - qty, 0)
            else:
                new_t, new_p = merge_position(cur_s, cur_p, qty, price)
                df.at[idx[0], "取得単価"] = new_p
                df.at[idx[0], "保有株数"] = new_t
            upd_count += 1
        save_data(df)
    _clear_sheet_cache()
    return tx_count, upd_count, skip_count
