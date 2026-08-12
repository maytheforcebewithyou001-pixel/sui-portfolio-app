"""NISA金額突合: SBI証券 summaryAll CSV(投信トータルリターン) × FORCE CAPITAL(Google Sheets)

外部通信あり(Google Sheets / yfinance / J-Quants)。実行はリポジトリ直下で:
  python scripts\\nisa_reconcile.py [summaryAll*.csvのパス]
引数省略時はリポジトリ直下の最新 summaryAll*.csv を使う。

注意: summaryAll はSBIの投資信託のみ(株式・他社口座を含まない)。
比較は「FC側: 口座=SBI かつ 市場=投資信託」に絞って行い、参考として全商品の内訳も出す。
"""
import csv
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # parity_check の既定値を使うため
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# parity_check と同じ既定値でクレデンシャル・対象シートを解決
from parity_check import DEFAULT_CREDS, DEFAULT_SHEET_ID, DEFAULT_USER  # noqa: E402


def load_summary_csv(path):
    """summaryAll CSV → {口座種別: 評価金額(円)}"""
    result = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.reader(f):
            if len(row) >= 2 and row[0] and row[0] != "口座種別":
                try:
                    result[row[0]] = float(row[1])
                except ValueError:
                    pass
    return result


def main():
    if os.path.exists(DEFAULT_CREDS) and not os.environ.get("GCP_CREDENTIALS_JSON"):
        with open(DEFAULT_CREDS, encoding="utf-8") as f:
            os.environ["GCP_CREDENTIALS_JSON"] = f.read()
    os.environ.setdefault("FC_API_USER", DEFAULT_USER)
    os.environ.setdefault("FC_SHEET_ID", DEFAULT_SHEET_ID)

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if len(sys.argv) > 1:
        csv_path = sys.argv[1]
    else:
        cands = sorted(glob.glob(os.path.join(root, "summaryAll*.csv")), key=os.path.getmtime)
        if not cands:
            print("summaryAll*.csv が見つかりません")
            sys.exit(1)
        csv_path = cands[-1]

    sbi = load_summary_csv(csv_path)
    print(f"SBI CSV: {os.path.basename(csv_path)}")
    for k, v in sbi.items():
        print(f"  {k:<20} ¥{v:>12,.0f}")

    print("\nFORCE CAPITAL のスナップショットを構築中...")
    from api.service import build_snapshot
    snap = build_snapshot()
    rows = snap["rows"]

    # 生の内訳を全部出す(グルーピング仮定のズレを目視できるように)
    print("\n=== FC側 内訳: 口座 × 口座区分 × 市場 ===")
    groups = {}
    for r in rows:
        key = (str(r.get("口座", "")), str(r.get("口座区分", "")), str(r.get("市場", "")))
        g = groups.setdefault(key, {"value": 0.0, "names": []})
        g["value"] += r.get("評価額(円)") or 0
        g["names"].append(str(r.get("銘柄名", "")))
    for key in sorted(groups):
        g = groups[key]
        print(f"  {' / '.join(key):<48} ¥{g['value']:>12,.0f}  ({len(g['names'])}行: {', '.join(n[:10] for n in g['names'])})")

    def fc_sum(broker=None, kubun_substrs=None, market=None):
        total = 0.0
        for r in rows:
            if broker and broker not in str(r.get("口座", "")):
                continue
            if kubun_substrs and not any(s in str(r.get("口座区分", "")) for s in kubun_substrs):
                continue
            if market and str(r.get("市場", "")) != market:
                continue
            total += r.get("評価額(円)") or 0
        return total

    # シート上の表記は「NISA(積立投資枠)」— SBI側の「つみたて」と表記揺れがある
    TSUMITATE = ("つみたて", "積立")
    print("\n=== 突合: SBI投信のみ(summaryAllの対象範囲) ===")
    pairs = [
        ("NISA (成長)", fc_sum(broker="SBI", kubun_substrs=("成長",), market="投資信託")),
        ("NISA (つみたて)", fc_sum(broker="SBI", kubun_substrs=TSUMITATE, market="投資信託")),
        ("特定/一般", fc_sum(broker="SBI", kubun_substrs=("特定",), market="投資信託")),
    ]
    print(f"  {'口座種別':<16} {'SBI CSV':>14} {'FORCE CAPITAL':>14} {'差額':>12} {'差%':>8}")
    for label, fc_val in pairs:
        sbi_val = sbi.get(label)
        if sbi_val is None:
            print(f"  {label:<16} {'(CSVに無し)':>14} ¥{fc_val:>12,.0f}")
            continue
        diff = fc_val - sbi_val
        pct = (diff / sbi_val * 100) if sbi_val else 0.0
        print(f"  {label:<16} ¥{sbi_val:>12,.0f} ¥{fc_val:>12,.0f} {diff:>+12,.0f} {pct:>+7.2f}%")

    print("\n=== 参考: FC側 NISA全商品(株式・ETF含む、SBI以外も) ===")
    for label, subs in (("成長", ("成長",)), ("つみたて", TSUMITATE)):
        print(f"  NISA({label}) 全商品: ¥{fc_sum(kubun_substrs=subs):>12,.0f}")

    print("\n→ 差が投信の基準価額の更新日ズレ(1営業日)で説明できる範囲か確認してください")


if __name__ == "__main__":
    main()
