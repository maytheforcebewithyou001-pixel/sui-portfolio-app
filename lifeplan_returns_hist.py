# -*- coding: utf-8 -*-
"""ライフプランMC用 ヒストリカル・リターン形状ソース (2026-07-26)

役割: モンテカルロの「正規分布・年次独立」仮定を実史の形状（ファットテール・歪み・
年をまたぐ連鎖）で置き換えるためのデータとサンプラーを提供する。

設計方針（水準はプラン、形状は実史）:
  実史系列はそのまま使わず、対数リターンを標準化した偏差 z（平均0・分散1）に
  変換して使う。実際の年次リターンは exp(ln(1+μ) + σ·z) - 1 で再構成するため、
  幾何平均=μ・対数分散=σ² はプラン前提と厳密に一致し、実史からは
  「分布の形と並び順」だけを借りる。これにより
    - 基準ケース（i.i.d.対数正規）とμ・σを揃えた公平な比較になる
    - 組込系列の水準誤差（配当込み近似等）が結果をほぼ汚さない

組込系列: S&P500 年次トータルリターン（名目USD、1928-2024、%）。
  出典: NYU Stern A. Damodaran "Historical Returns on Stocks, Bonds and Bills"
  ベースの近似値（±1pt程度の転記誤差があり得る。標準化して形状のみ使うため
  影響は二次的）。オルカン(JPY)投資家には円高リスクオフ局面の下振れ増幅が
  乗らない分、テールがやや甘い可能性に注意。
差し替え: 同フォルダに lifeplan_hist_returns.csv（ヘッダ year,return、returnは
  小数表記 例 -0.421）を置けばそちらを優先して読む。
"""
from pathlib import Path

import numpy as np

CSV_OVERRIDE = Path(__file__).with_name("lifeplan_hist_returns.csv")

# (年, 年次トータルリターン%) 名目USD
SP500_NOMINAL = (
    (1928, 43.8), (1929, -8.3), (1930, -25.1), (1931, -43.8), (1932, -8.6),
    (1933, 50.0), (1934, -1.2), (1935, 46.7), (1936, 31.9), (1937, -35.3),
    (1938, 29.3), (1939, -1.1), (1940, -10.7), (1941, -12.8), (1942, 19.2),
    (1943, 25.1), (1944, 19.0), (1945, 35.8), (1946, -8.4), (1947, 5.2),
    (1948, 5.7), (1949, 18.3), (1950, 30.8), (1951, 23.7), (1952, 18.2),
    (1953, -1.2), (1954, 52.6), (1955, 32.6), (1956, 7.4), (1957, -10.5),
    (1958, 43.7), (1959, 12.1), (1960, 0.3), (1961, 26.6), (1962, -8.8),
    (1963, 22.6), (1964, 16.4), (1965, 12.4), (1966, -10.0), (1967, 23.8),
    (1968, 10.8), (1969, -8.2), (1970, 3.6), (1971, 14.2), (1972, 18.8),
    (1973, -14.3), (1974, -25.9), (1975, 37.0), (1976, 23.8), (1977, -7.0),
    (1978, 6.5), (1979, 18.5), (1980, 31.7), (1981, -4.7), (1982, 20.4),
    (1983, 22.3), (1984, 6.1), (1985, 31.2), (1986, 18.5), (1987, 5.8),
    (1988, 16.5), (1989, 31.5), (1990, -3.1), (1991, 30.2), (1992, 7.5),
    (1993, 10.0), (1994, 1.3), (1995, 37.2), (1996, 22.7), (1997, 33.1),
    (1998, 28.3), (1999, 20.9), (2000, -9.0), (2001, -11.9), (2002, -22.0),
    (2003, 28.4), (2004, 10.7), (2005, 4.8), (2006, 15.6), (2007, 5.5),
    (2008, -36.6), (2009, 25.9), (2010, 14.8), (2011, 2.1), (2012, 15.9),
    (2013, 32.2), (2014, 13.5), (2015, 1.4), (2016, 11.8), (2017, 21.6),
    (2018, -4.2), (2019, 31.2), (2020, 18.0), (2021, 28.5), (2022, -18.0),
    (2023, 26.1), (2024, 24.9),
)


def load_returns():
    """(年配列, リターン小数配列) を返す。CSVがあればそちらを優先。"""
    if CSV_OVERRIDE.exists():
        rows = []
        for ln in CSV_OVERRIDE.read_text(encoding="utf-8-sig").splitlines()[1:]:
            ln = ln.strip()
            if ln:
                y, r = ln.split(",")[:2]
                rows.append((int(y), float(r)))
        if len(rows) < 20:
            raise ValueError(f"{CSV_OVERRIDE.name} の行数が少なすぎる({len(rows)}年)")
        years, rets = zip(*rows)
        return np.array(years), np.array(rets, float)
    years, pct = zip(*SP500_NOMINAL)
    return np.array(years), np.array(pct, float) / 100.0


def standardized_log_dev(returns):
    """対数リターンを標準化した偏差 z（平均0・標本標準偏差1）。"""
    r = np.asarray(returns, float)
    if np.any(r <= -1.0):
        raise ValueError("リターン-100%以下は対数変換不可")
    lg = np.log1p(r)
    sd = lg.std(ddof=1)
    if sd <= 0:
        raise ValueError("分散ゼロの系列")
    return (lg - lg.mean()) / sd


def block_bootstrap_z(z, n_paths, n_years, block_len, rng):
    """循環ブロック・ブートストラップ。(n_paths, n_years) のz行列を返す。

    連続block_len年をひと塊で抽出するため、暴落→回復のような年をまたぐ
    連鎖（自己相関）が保存される。block_len=1で単純ブートストラップ。"""
    z = np.asarray(z, float)
    L = len(z)
    block_len = max(1, int(block_len))
    n_blocks = -(-n_years // block_len)          # ceil
    starts = rng.integers(0, L, size=(n_paths, n_blocks))
    offs = np.arange(block_len)
    idx = (starts[:, :, None] + offs[None, None, :]).reshape(n_paths, -1)
    return z[idx[:, :n_years] % L]


def sequence_indices(start_i, n_years, length):
    """開始位置 start_i から n_years 分の循環インデックス。"""
    return (start_i + np.arange(n_years)) % length
