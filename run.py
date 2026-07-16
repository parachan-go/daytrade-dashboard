# -*- coding: utf-8 -*-
"""デイトレード分析: universe全銘柄をスクリーニング → 上位+watchlistをチャート化
実行: python run.py
"""
import json, os, sys, time, datetime
import numpy as np
import pandas as pd
import yfinance as yf

BASE = os.path.dirname(os.path.abspath(__file__))

def dl(*args, **kw):
    """yf.downloadのリトライ付きラッパー(クラウドIPのレート制限対策)"""
    df = None
    for i in range(3):
        try:
            df = yf.download(*args, **kw)
            if df is not None and len(df):
                return df
        except Exception as e:
            print(f"  取得リトライ {i+1}/3: {e}")
        time.sleep(15 * (i + 1))
    return df

# TOPIX-17業種 → 業種ETFコード(資金流入の計測に使用)
SECTOR_ETF = {
    "食品": "1617", "エネルギー資源": "1618", "建設・資材": "1619",
    "素材・化学": "1620", "医薬品": "1621", "自動車・輸送機": "1622",
    "鉄鋼・非鉄": "1623", "機械": "1624", "電機・精密": "1625",
    "情報通信・サービス": "1626", "電力・ガス": "1627", "運輸・物流": "1628",
    "商社・卸売": "1629", "小売": "1630", "銀行": "1631",
    "金融(除く銀行)": "1632", "不動産": "1633",
}

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

def load_config():
    p = os.path.join(BASE, "config.json")
    default = {"columns": 3, "top_n": 24,
               "screening": {"min_turnover_oku": 0, "min_atr_pct": 0,
                              "min_vol_ratio": 0, "only_above_vwap": False},
               "sort_by": "score"}
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            default.update(json.load(f))
    return default

def session_elapsed_fraction(now=None):
    """東証の当日セッション経過割合(9:00-11:30, 12:30-15:30 = 330分)"""
    now = now or datetime.datetime.now()
    m = now.hour * 60 + now.minute
    elapsed = min(max(m - 540, 0), 150) + min(max(m - 750, 0), 180)
    return max(elapsed / 330.0, 0.05)

def is_intraday_now():
    now = datetime.datetime.now()
    return now.hour * 60 + now.minute < 930  # 15:30前

def daily_stats(dd, today, frac):
    """日足DataFrameから日次指標を計算(欠損時None)"""
    if dd is None or len(dd) < 25:
        return None
    close, high, low, vol = dd["Close"], dd["High"], dd["Low"], dd["Volume"]
    turnover20 = float((close * vol).tail(20).mean() / 1e8)
    prev_c = close.shift(1)
    tr = pd.concat([high - low, (high - prev_c).abs(), (low - prev_c).abs()], axis=1).max(axis=1)
    atr14 = float(tr.tail(14).mean())
    atr_pct = atr14 / float(close.iloc[-1]) * 100
    vol20 = float(vol.iloc[:-1].tail(20).mean())
    # ザラ場中は当日出来高を経過時間で補正して比較
    adj = frac if (dd.index[-1].date() == today and is_intraday_now()) else 1.0
    vol_ratio = float(vol.iloc[-1]) / adj / vol20 if vol20 > 0 else 0
    gap_pct = (float(dd["Open"].iloc[-1]) / float(close.iloc[-2]) - 1) * 100
    change_pct = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
    prev_close_map = {d.strftime("%Y-%m-%d"): float(v) for d, v in prev_c.dropna().items()}
    return {"turnover_oku": round(turnover20, 1), "atr_pct": round(atr_pct, 2),
            "vol_ratio": round(vol_ratio, 2), "gap_pct": round(gap_pct, 2),
            "change_pct": round(change_pct, 2), "last_close": float(close.iloc[-1]),
            "_prev_close_map": prev_close_map}

def intraday_series(df, prev_close_map):
    """5分足から日別のVWAP付きシリーズとサマリーを構築"""
    df = df.dropna(subset=["Close"]).copy()
    if df.empty:
        return None, None
    df["date"] = df.index.strftime("%Y-%m-%d")
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    df["cum_pv"] = (tp * df["Volume"]).groupby(df["date"]).cumsum()
    df["cum_v"] = df["Volume"].groupby(df["date"]).cumsum()
    df["vwap"] = (df["cum_pv"] / df["cum_v"].replace(0, np.nan)).ffill()
    series, daysum = {}, {}
    for d, g in df.groupby("date"):
        if g["Close"].isna().all():
            continue
        vw, c = g["vwap"].round(2), g["Close"]
        if not len(c) or pd.isna(vw.iloc[-1]) or vw.iloc[-1] == 0:
            continue
        dev = (float(c.iloc[-1]) / float(vw.iloc[-1]) - 1) * 100
        above = float((c > g["vwap"]).mean() * 100)
        pc = prev_close_map.get(d)
        chg = (float(c.iloc[-1]) / pc - 1) * 100 if pc else None
        # 9:30時点VWAP(9:00〜9:25の5分足まで=寄りから30分の累積VWAP)
        early = g[g.index.strftime("%H:%M") <= "09:25"]
        vwap930 = float(early["vwap"].iloc[-1]) if len(early) else None
        dev930 = (float(c.iloc[-1]) / vwap930 - 1) * 100 if vwap930 else None
        series[d] = {"t": g.index.strftime("%H:%M").tolist(),
                     "o": g["Open"].round(1).tolist(), "h": g["High"].round(1).tolist(),
                     "l": g["Low"].round(1).tolist(), "c": c.round(1).tolist(),
                     "v": g["Volume"].fillna(0).astype(int).tolist(),
                     "vwap": vw.tolist(), "prev_close": pc,
                     "vwap930": round(vwap930, 2) if vwap930 else None}
        daysum[d] = {"dev": round(dev, 2), "above_pct": round(above, 1),
                     "chg": round(chg, 2) if chg is not None else None,
                     "dev930": round(dev930, 2) if dev930 is not None else None,
                     "close": float(c.iloc[-1])}
    return series, daysum

def update_records(symbols):
    """9:30VWAP vs 終値の日次記録をrecords.csvに追記(確定日のみ)"""
    path = os.path.join(BASE, "records.csv")
    existing = set()
    rows = []
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            header = f.readline()
            for line in f:
                p = line.strip().split(",")
                if len(p) >= 2:
                    existing.add((p[0], p[1]))
                    rows.append(line.rstrip("\n"))
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    added = 0
    for s in symbols:
        for d, ds in sorted(s["daysum"].items()):
            if ds.get("dev930") is None:
                continue
            if d == today_str and is_intraday_now():
                continue  # 当日ザラ場中は未確定なので記録しない
            key = (d, s["code"])
            if key in existing:
                continue
            result = "高" if ds["dev930"] > 0 else "低"
            rows.append(f"{d},{s['code']},{s['name']},{s['series'][d]['vwap930']},"
                        f"{ds['close']},{result},{ds['dev930']}")
            existing.add(key)
            added += 1
    rows.sort()
    with open(path, "w", encoding="utf-8") as f:
        f.write("date,code,name,vwap930,close,result,dev930_pct\n")
        f.write("\n".join(rows) + ("\n" if rows else ""))
    print(f"records.csv: {added}件追記(累計{len(rows)}件)")
    # 銘柄別の高値終い率を集計
    agg = {}
    for line in rows:
        p = line.split(",")
        code, name, result, dev = p[1], p[2], p[5], float(p[6])
        a = agg.setdefault(code, {"win": 0, "total": 0, "sum_dev": 0.0, "name": name, "days": {}})
        a["total"] += 1
        a["sum_dev"] += dev
        a["days"][p[0]] = result
        if result == "高":
            a["win"] += 1
    return agg

def update_market():
    """日経225の9:30→引け方向をmarket.csvに蓄積し、date->方向 のdictを返す"""
    path = os.path.join(BASE, "market.csv")
    existing = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            f.readline()
            for line in f:
                p = line.strip().split(",")
                if len(p) >= 4:
                    existing[p[0]] = line.rstrip("\n")
    try:
        n5 = dl("^N225", period="60d", interval="5m", progress=False, auto_adjust=False)
        nd = dl("^N225", period="4mo", interval="1d", progress=False, auto_adjust=False)
        for df in (n5, nd):
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.droplevel(1)
        prev_map = {d.strftime("%Y-%m-%d"): float(v)
                    for d, v in nd["Close"].shift(1).dropna().items()}
        n5 = n5.dropna(subset=["Close"]).copy()
        n5["date"] = n5.index.strftime("%Y-%m-%d")
        today = datetime.date.today().strftime("%Y-%m-%d")
        for d, g in n5.groupby("date"):
            if d in existing or (d == today and is_intraday_now()):
                continue
            early = g[g.index.strftime("%H:%M") <= "09:25"]
            if not len(early):
                continue
            p930, close = float(early["Close"].iloc[-1]), float(g["Close"].iloc[-1])
            chg930 = (close / p930 - 1) * 100
            pc = prev_map.get(d)
            daychg = (close / pc - 1) * 100 if pc else None
            existing[d] = (f"{d},{round(p930,2)},{round(close,2)},{'高' if chg930 > 0 else '低'},"
                           f"{round(chg930,3)},{'高' if daychg and daychg > 0 else '低'},"
                           f"{round(daychg,3) if daychg is not None else ''}")
    except Exception as e:
        print(f"  日経データ取得エラー(既存market.csvで継続): {e}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("date,n225_930,n225_close,dir930,chg930_pct,day_dir,day_chg_pct\n")
        f.write("\n".join(v for _, v in sorted(existing.items())) + ("\n" if existing else ""))
    print(f"market.csv: {len(existing)}日分")
    return {d: line.split(",")[3] for d, line in existing.items()}  # date -> 9:30→引け方向

def fetch_sector_flow():
    tickers = [f"{c}.T" for c in SECTOR_ETF.values()]
    dd = dl(tickers, period="3mo", interval="1d",
                     group_by="ticker", auto_adjust=False, progress=False, threads=True)
    today = datetime.date.today()
    frac = session_elapsed_fraction()
    out = []
    for name, code in SECTOR_ETF.items():
        try:
            df = dd[f"{code}.T"].dropna(subset=["Close"])
        except KeyError:
            continue
        if len(df) < 25:
            continue
        close, vol = df["Close"], df["Volume"]
        turnover = close * vol
        adj = frac if (df.index[-1].date() == today and is_intraday_now()) else 1.0
        t20 = float(turnover.iloc[:-1].tail(20).mean())
        turn_ratio = float(turnover.iloc[-1]) / adj / t20 if t20 > 0 else 0
        chg = (float(close.iloc[-1]) / float(close.iloc[-2]) - 1) * 100
        chg5 = (float(close.iloc[-1]) / float(close.iloc[-6]) - 1) * 100 if len(df) > 6 else None
        out.append({"name": name, "etf": code, "chg": round(chg, 2),
                    "chg5d": round(chg5, 2) if chg5 is not None else None,
                    "turn_ratio": round(turn_ratio, 2)})
    out.sort(key=lambda x: x["turn_ratio"], reverse=True)
    return out, ("補正あり" if is_intraday_now() else "確定値")

def main():
    cfg = load_config()
    universe = read_csv3(os.path.join(BASE, "universe.csv"))
    watch = read_csv3(os.path.join(BASE, "watchlist.csv"))
    watch_codes = {c for c, _, _ in watch}
    # watchlistにしかない銘柄もユニバースに合流
    known = {c for c, _, _ in universe}
    universe += [w for w in watch if w[0] not in known]
    print(f"ユニバース {len(universe)}銘柄の日足を取得中...")
    tickers = [f"{c}.T" for c, _, _ in universe]
    daily = dl(tickers, period="3mo", interval="1d",
                        group_by="ticker", auto_adjust=False, progress=False, threads=True)
    today = datetime.date.today()
    frac = session_elapsed_fraction()
    stats = {}
    for code, name, sector in universe:
        try:
            dd = daily[f"{code}.T"].dropna(subset=["Close"])
        except KeyError:
            continue
        st = daily_stats(dd, today, frac)
        if st:
            stats[code] = st
    print(f"  日足取得OK: {len(stats)}銘柄")

    # スコア(ユニバース全体でのパーセンタイル)
    codes = list(stats)
    def pct_rank(key):
        s = pd.Series([stats[c][key] for c in codes], index=codes)
        return (s.rank(pct=True) * 100)
    pr = 0.35 * pct_rank("atr_pct") + 0.35 * pct_rank("turnover_oku") + 0.30 * pct_rank("vol_ratio")
    for c in codes:
        stats[c]["score"] = round(float(pr[c]), 1)

    # 上位N + watchlist を選抜
    top_n = int(cfg.get("top_n", 24))
    ranked = sorted(codes, key=lambda c: stats[c]["score"], reverse=True)
    selected = ranked[:top_n]
    selected += [c for c in watch_codes if c in stats and c not in selected]
    sel_set = set(selected)
    meta = {c: (n, s) for c, n, s in universe}
    print(f"選抜 {len(selected)}銘柄(上位{top_n}+watchlist)の5分足を取得中...")
    intra = dl([f"{c}.T" for c in selected], period="5d", interval="5m",
                        group_by="ticker", auto_adjust=False, progress=False, threads=True)

    print("業種ETF(TOPIX-17)の資金フローを取得中...")
    sectors, flow_status = fetch_sector_flow()

    out = []
    for code in selected:
        name, sector = meta[code]
        try:
            df = intra[f"{code}.T"]
        except KeyError:
            print(f"  skip: {code} {name}(分足なし)")
            continue
        st = dict(stats[code])
        series, daysum = intraday_series(df, st.pop("_prev_close_map"))
        if not series:
            print(f"  skip: {code} {name}(分足なし)")
            continue
        out.append({"code": code, "name": name, "sector": sector,
                    "pinned": code in watch_codes, "stats": st,
                    "daysum": daysum, "series": series})
    if not out:
        sys.exit("データが取得できませんでした")
    out.sort(key=lambda s: s["stats"]["score"], reverse=True)
    rec = update_records(out)
    for s in out:
        a = rec.get(s["code"])
        s["rec930"] = {"win": a["win"], "total": a["total"],
                       "rate": round(a["win"] / a["total"] * 100)} if a else None
    # 日経225の9:30→引け方向(market.csv蓄積)
    mdir = update_market()
    # 全記録から「VWAP予測しやすさ」ランキング(一貫性=高値終い/低値終いへの偏り)
    # + 日経条件付き分析(連動型か独立型か)
    rec_ranking = []
    for code, a in rec.items():
        rate = a["win"] / a["total"] * 100
        up = [r for d, r in a["days"].items() if mdir.get(d) == "高"]
        dn = [r for d, r in a["days"].items() if mdir.get(d) == "低"]
        up_rate = round(up.count("高") / len(up) * 100) if len(up) >= 10 else None
        dn_rate = round(dn.count("高") / len(dn) * 100) if len(dn) >= 10 else None
        spread = (up_rate - dn_rate) if (up_rate is not None and dn_rate is not None) else None
        cons = round(max(rate, 100 - rate))
        if spread is None:
            mtype = "─"
        elif abs(spread) >= 40:
            mtype = "日経連動◎"
        elif abs(spread) >= 25:
            mtype = "日経連動"
        elif cons >= 58 and abs(spread) < 15:
            mtype = "独立"
        else:
            mtype = "─"
        rec_ranking.append({
            "code": code, "name": a["name"],
            "sector": meta.get(code, ("", "その他"))[1],
            "total": a["total"], "rate": round(rate),
            "cons": cons,
            "trend": "高値終い" if rate >= 50 else "低値終い",
            "avg_dev": round(a["sum_dev"] / a["total"], 2),
            "up_rate": up_rate, "dn_rate": dn_rate, "spread": spread, "mtype": mtype,
            "shown": code in {s["code"] for s in out}})
    rec_ranking.sort(key=lambda x: (x["cons"], x["total"]), reverse=True)
    days = sorted({d for s in out for d in s["series"]})
    data = {"generated": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            "days": days, "symbols": out, "config": cfg,
            "sectors": sectors, "flow_status": flow_status,
            "universe_count": len(stats), "rec_ranking": rec_ranking}

    with open(os.path.join(BASE, "template.html"), encoding="utf-8") as f:
        html = f.read()
    html = html.replace("/*__DATA__*/", "const DATA = " + json.dumps(data, ensure_ascii=False) + ";")
    out_path = os.path.join(BASE, "dashboard.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"OK: {out_path}({len(out)}銘柄表示 / 母集団{len(stats)}銘柄, {len(days)}営業日)")

if __name__ == "__main__":
    main()
