# -*- coding: utf-8 -*-
"""過去約60日分(yfinance 5分足の上限)の9:30VWAP vs 終値をrecords.csvに一括投入
使い方: python backfill.py <開始index> <件数>   例: python backfill.py 0 25
"""
import sys, os, datetime
import numpy as np
import pandas as pd
import yfinance as yf

BASE = os.path.dirname(os.path.abspath(__file__))

def read_csv3(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = [x.strip() for x in line.split(",")]
            rows.append((p[0], p[1], p[2] if len(p) > 2 and p[2] else "その他"))
    return rows

def main():
    start, count = int(sys.argv[1]), int(sys.argv[2])
    universe = read_csv3(os.path.join(BASE, "universe.csv"))
    known = {c for c, _, _ in universe}
    universe += [w for w in read_csv3(os.path.join(BASE, "watchlist.csv")) if w[0] not in known]
    batch = universe[start:start + count]
    if not batch:
        print("対象なし")
        return
    path = os.path.join(BASE, "records.csv")
    existing, rows = set(), []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            f.readline()
            for line in f:
                p = line.strip().split(",")
                if len(p) >= 2:
                    existing.add((p[0], p[1]))
                    rows.append(line.rstrip("\n"))
    today = datetime.date.today().strftime("%Y-%m-%d")
    now = datetime.datetime.now()
    intraday_now = now.hour * 60 + now.minute < 930

    data = yf.download([f"{c}.T" for c, _, _ in batch], period="60d", interval="5m",
                       group_by="ticker", auto_adjust=False, progress=False, threads=True)
    added = 0
    for code, name, _ in batch:
        try:
            df = data[f"{code}.T"].dropna(subset=["Close"]).copy()
        except KeyError:
            continue
        if df.empty:
            continue
        df["date"] = df.index.strftime("%Y-%m-%d")
        tp = (df["High"] + df["Low"] + df["Close"]) / 3
        df["cum_pv"] = (tp * df["Volume"]).groupby(df["date"]).cumsum()
        df["cum_v"] = df["Volume"].groupby(df["date"]).cumsum()
        df["vwap"] = (df["cum_pv"] / df["cum_v"].replace(0, np.nan)).ffill()
        for d, g in df.groupby("date"):
            if (d, code) in existing or (d == today and intraday_now):
                continue
            early = g[g.index.strftime("%H:%M") <= "09:25"]
            if not len(early) or pd.isna(early["vwap"].iloc[-1]):
                continue
            vwap930 = float(early["vwap"].iloc[-1])
            close = float(g["Close"].iloc[-1])
            dev = (close / vwap930 - 1) * 100
            rows.append(f"{d},{code},{name},{round(vwap930,2)},{close},"
                        f"{'高' if dev > 0 else '低'},{round(dev,2)}")
            existing.add((d, code))
            added += 1
    rows.sort()
    with open(path, "w", encoding="utf-8") as f:
        f.write("date,code,name,vwap930,close,result,dev930_pct\n")
        f.write("\n".join(rows) + ("\n" if rows else ""))
    print(f"batch {start}-{start+len(batch)-1}: {added}件追記(累計{len(rows)}件)")

if __name__ == "__main__":
    main()
