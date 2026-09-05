#!/usr/bin/env python3
"""성향(orientation) 축 분석의 스크립트 승격 (재현성 게이트).

이전에 인라인으로 산출했던 성향 연도별 구성비 CSV와 성향 그림 2종
(fig4 원창, fig5 파생)을 analysis_master.sqlite에서 결정론적으로 재생성한다.
- outputs/v2b_orientation_yearly_share.csv : 기존 파일과 완전 일치해야 함(검증 후 덮어씀)
- figures/fig4_original_orientation_trends.png / fig5_derivative_orientation_trends.png
- outputs/v2c_fig4_data.csv / v2c_fig5_data.csv : 그림 근거 데이터
"""
import sqlite3, csv, sys
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJ = Path(__file__).resolve().parent.parent
DB = PROJ / "data" / "analysis_master.sqlite"
FIG = PROJ / "figures"
OUT = PROJ / "outputs"

plt.rcParams.update({
    "font.family": "Arial Unicode MS",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 300,
})

con = sqlite3.connect(DB)
YEARS = list(range(2003, 2027))
ORIENTS = ["言情", "纯爱", "无CP", "百合", "多元"]

# ── 성향 연도별 구성비 (시장별 전체 대비; 성향 미표기 포함 분모) ──
rows = []
for market in ["原创", "衍生"]:
    tot = dict(con.execute(
        "SELECT publish_year, COUNT(*) FROM analysis_master WHERE originality=? GROUP BY 1",
        (market,)).fetchall())
    for o in ORIENTS:
        cnt = dict(con.execute(
            "SELECT publish_year, COUNT(*) FROM analysis_master WHERE originality=? AND orientation=? GROUP BY 1",
            (market, o)).fetchall())
        for y in YEARS:
            t = tot.get(str(y), 0)
            c = cnt.get(str(y), 0)
            if t:
                rows.append([market, o, y, c, t, round(c / t * 100, 3)])

new_lines = [["market", "orientation", "year", "count", "year_total", "share_pct"]] + [
    [r[0], r[1], str(r[2]), str(r[3]), str(r[4]), str(r[5])] for r in rows]

existing = OUT / "v2b_orientation_yearly_share.csv"
if existing.exists():
    old = [row for row in csv.reader(open(existing))]
    old_set = {tuple(r[:3]): tuple(float(x) for x in r[3:]) for r in old[1:]}
    new_set = {tuple(r[:3]): tuple(float(x) for x in r[3:]) for r in new_lines[1:]}
    mismatch = [k for k in new_set if k in old_set and old_set[k] != new_set[k]]
    if mismatch:
        print(f"[FAIL] 기존 CSV와 불일치 {len(mismatch)}건, 예: {mismatch[:3]}")
        sys.exit(1)
    print(f"[OK] 기존 v2b_orientation_yearly_share.csv와 일치 (교집합 {len(set(new_set) & set(old_set))}행 검증)")
with open(existing, "w", newline="") as f:
    csv.writer(f).writerows(new_lines)

# ── 그림용 시계열 ──
def orient_series(market):
    data = {}
    for o in ORIENTS:
        vals = []
        for y in YEARS:
            match = [r for r in rows if r[0] == market and r[1] == o and r[2] == y]
            vals.append(match[0][5] if match else None)
        data[o] = vals
    return data


def save_fig(market, data, fname, csv_name, note):
    with open(OUT / csv_name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year"] + ORIENTS)
        for i, y in enumerate(YEARS):
            w.writerow([y] + [data[o][i] if data[o][i] is not None else "" for o in ORIENTS])
    STYLES = ["-", "--", "-.", ":", (0, (3, 1, 1, 1))]
    MARKERS = ["o", "s", "^", "D", "v"]
    fig, ax = plt.subplots(figsize=(6.4, 3.6))
    for i, o in enumerate(ORIENTS):
        ax.plot(YEARS, data[o], linestyle=STYLES[i], marker=MARKERS[i], markersize=3,
                linewidth=1.4, color="black", markerfacecolor="white" if i % 2 else "black", label=o)
    ax.set_xlabel("발표연도")
    ax.set_ylabel("구성비(%)")
    ax.set_xticks(range(2003, 2027, 3))
    ax.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.14))
    ax.annotate(note, xy=(0.99, 0.97), xycoords="axes fraction",
                ha="right", va="top", fontsize=8, color="0.35")
    fig.tight_layout()
    fig.savefig(FIG / fname, bbox_inches="tight")
    plt.close(fig)


d_orig = orient_series("原创")
d_deriv = orient_series("衍生")
save_fig("原创", d_orig, "fig4_original_orientation_trends.png", "v2c_fig4_data.csv", "2026은 부분연도")
save_fig("衍生", d_deriv, "fig5_derivative_orientation_trends.png", "v2c_fig5_data.csv",
         "2026은 부분연도; 2003년은 소표본(132건)")

# 검증 출력: 본문 인용 수치 정합
chk = {y: d_orig["言情"][i] for i, y in enumerate(YEARS) if y in (2003, 2010, 2015, 2020, 2021, 2022, 2024, 2026)}
print("fig4 原创 言情:", chk)
print("fig4 原创 纯爱:", {y: d_orig["纯爱"][i] for i, y in enumerate(YEARS) if y in (2010, 2021, 2022, 2024, 2026)})
print("fig5 衍生 言情:", {y: d_deriv["言情"][i] for i, y in enumerate(YEARS) if y in (2010, 2017, 2024)})
print("fig5 衍生 纯爱:", {y: d_deriv["纯爱"][i] for i, y in enumerate(YEARS) if y in (2010, 2024)})
print("saved fig4/fig5 + v2c_fig4/5 data CSVs")
