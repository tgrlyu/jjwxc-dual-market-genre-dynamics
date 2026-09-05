#!/usr/bin/env python3
"""작품적분(score) 집중 지표의 노출기간 민감도 분석 (보충자료 C의 산출 스크립트).

작품적분은 수집 시점(2026-07)의 누적치이므로 발표 시점이 이른 작품일수록
노출 기간이 길다. 시기(period) 집계의 집중도가 이 노출기간 편향의 산물이
아닌지 확인하기 위해, 노출 기간이 동일한 '발표연도 코호트' 내부에서
상위 1%·10% 점유율과 중앙값을 재계산한다.

산출:
- outputs/v2d_score_sensitivity_yearly.csv : 연도별(동일 노출 코호트) 집중 지표
- outputs/v2d_score_period_median.csv     : 시기별 중앙값·집중 지표
"""
import sqlite3, csv, statistics
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DB = PROJ / "data" / "analysis_master.sqlite"
OUT = PROJ / "outputs"
con = sqlite3.connect(DB)

PERIODS = [("P1 2003–09", 2003, 2009), ("P2 2010–16", 2010, 2016),
           ("P3 2017–19", 2017, 2019), ("P4 2020–23", 2020, 2023),
           ("P5 2024–26", 2024, 2026)]


def top_share(scores, frac):
    scores = sorted(scores, reverse=True)
    k = max(1, int(len(scores) * frac))
    tot = sum(scores)
    return sum(scores[:k]) / tot * 100 if tot else 0.0


def fetch(cond, args):
    return [r[0] for r in con.execute(
        f"SELECT score FROM analysis_master WHERE originality='原创' AND score IS NOT NULL AND {cond}", args)]


with open(OUT / "v2d_score_sensitivity_yearly.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["year", "n", "top1pct_share", "top10pct_share", "median_score"])
    for y in range(2003, 2027):
        s = fetch("partition_year=?", (y,))
        if s:
            w.writerow([y, len(s), round(top_share(s, 0.01), 2), round(top_share(s, 0.10), 2),
                        round(statistics.median(s))])

with open(OUT / "v2d_score_period_median.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["period", "n", "top1pct_share", "top10pct_share", "median_score"])
    for name, a, b in PERIODS:
        s = fetch("partition_year BETWEEN ? AND ?", (a, b))
        w.writerow([name, len(s), round(top_share(s, 0.01), 2), round(top_share(s, 0.10), 2),
                    round(statistics.median(s))])

# 요약 출력
yr = list(csv.DictReader(open(OUT / "v2d_score_sensitivity_yearly.csv")))
vals = [float(r["top1pct_share"]) for r in yr if int(r["year"]) >= 2010]
print(f"연도별 코호트 top1% (2010–26): min {min(vals):.1f} / max {max(vals):.1f}")
pm = list(csv.DictReader(open(OUT / "v2d_score_period_median.csv")))
for r in pm:
    print(r["period"], "top1%", r["top1pct_share"], "median", r["median_score"])
