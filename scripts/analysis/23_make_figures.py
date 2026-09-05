#!/usr/bin/env python3
"""KCI 논문용 그림 3종 생성 (300dpi, 흑백 인쇄 구분 가능한 스타일).

그림 데이터는 v2b CSV의 top-8 절단을 피해 analysis_master에서 정확 재계산하고,
근거 CSV(outputs/v2c_fig*_data.csv)를 함께 저장해 재현 가능성을 보장한다.
"""
import sqlite3, csv
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

PROJ = Path(__file__).resolve().parent.parent
DB = PROJ / "data" / "analysis_master.sqlite"
FIG = PROJ / "figures"
OUT = PROJ / "outputs"
FIG.mkdir(exist_ok=True)

plt.rcParams.update({
    "font.family": "Arial Unicode MS",
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "figure.dpi": 300,
})

con = sqlite3.connect(DB)
YEARS = list(range(2003, 2027))


def shares(market, genres):
    """market 내 지정 장르들의 연도별 정확 share(%) — top-8 절단 없음."""
    tot = dict(con.execute(
        "SELECT publish_year, COUNT(*) FROM analysis_master WHERE originality=? GROUP BY 1",
        (market,)).fetchall())
    data = {g: [] for g in genres}
    for g in genres:
        cnt = dict(con.execute(
            "SELECT publish_year, COUNT(*) FROM analysis_master WHERE originality=? AND genre=? GROUP BY 1",
            (market, g)).fetchall())
        for y in YEARS:
            t = tot.get(str(y), 0)
            data[g].append(cnt.get(str(y), 0) / t * 100 if t else None)
    return data


def save_csv(name, header, genres, data):
    with open(OUT / name, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["year"] + list(genres))
        for i, y in enumerate(YEARS):
            w.writerow([y] + [round(data[g][i], 3) if data[g][i] is not None else "" for g in genres])


STYLES = ["-", "--", "-.", ":", (0, (3, 1, 1, 1))]
MARKERS = ["o", "s", "^", "D", "v"]

# ── 그림 1: 원창 시장 주요 장르 추세 ──
g1 = ["爱情", "剧情", "轻小说", "仙侠", "奇幻"]
d1 = shares("原创", g1)
save_csv("v2c_fig1_data.csv", "yr", g1, d1)
fig, ax = plt.subplots(figsize=(6.4, 3.6))
for i, g in enumerate(g1):
    ax.plot(YEARS, d1[g], linestyle=STYLES[i], marker=MARKERS[i], markersize=3,
            linewidth=1.4, color="black", markerfacecolor="white" if i % 2 else "black", label=g)
ax.set_xlabel("발표연도")
ax.set_ylabel("구성비(%)")
ax.set_xticks(range(2003, 2027, 3))
ax.legend(frameon=False, ncol=5, loc="upper center", bbox_to_anchor=(0.5, 1.14))
ax.annotate("2026은 부분연도", xy=(0.99, 0.97), xycoords="axes fraction",
            ha="right", va="top", fontsize=8, color="0.35")
fig.tight_layout()
fig.savefig(FIG / "fig1_original_genre_trends.png", bbox_inches="tight")
plt.close(fig)

# ── 그림 2: 파생 시장 구성 재편 ──
g2 = ["东方衍生", "其他衍生", "轻小说", "西方衍生"]
d2 = shares("衍生", g2)
save_csv("v2c_fig2_data.csv", "yr", g2, d2)
fig, ax = plt.subplots(figsize=(6.4, 3.6))
for i, g in enumerate(g2):
    ax.plot(YEARS, d2[g], linestyle=STYLES[i], marker=MARKERS[i], markersize=3,
            linewidth=1.4, color="black", markerfacecolor="white" if i % 2 else "black", label=g)
ax.set_xlabel("발표연도")
ax.set_ylabel("구성비(%)")
ax.set_xticks(range(2003, 2027, 3))
ax.legend(frameon=False, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.14))
ax.annotate("2026은 부분연도", xy=(0.99, 0.97), xycoords="axes fraction",
            ha="right", va="top", fontsize=8, color="0.35")
fig.tight_layout()
fig.savefig(FIG / "fig2_derivative_recomposition.png", bbox_inches="tight")
plt.close(fig)

# ── 그림 3: 시기별 score 집중 (상위 1%·10% 점유) ──
periods = ["P1\n2003–09", "P2\n2010–16", "P3\n2017–19", "P4\n2020–23", "P5\n2024–26*"]
top1 = [65.64, 74.88, 67.63, 74.95, 73.22]
top10 = [93.61, 97.31, 97.28, 99.11, 97.79]
with open(OUT / "v2c_fig3_data.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["period", "top1pct_share", "top10pct_share"])
    for p, a, b in zip(periods, top1, top10):
        w.writerow([p.replace("\n", " "), a, b])
fig, ax = plt.subplots(figsize=(5.6, 3.2))
x = range(len(periods))
ax.bar([i - 0.19 for i in x], top1, width=0.36, color="0.25", label="상위 1% 점유")
ax.bar([i + 0.19 for i in x], top10, width=0.36, color="0.7", label="상위 10% 점유")
for i, v in enumerate(top1):
    ax.text(i - 0.19, v + 1, f"{v:.1f}", ha="center", fontsize=8)
for i, v in enumerate(top10):
    ax.text(i + 0.19, v + 1, f"{v:.1f}", ha="center", fontsize=8)
ax.set_xticks(list(x), periods)
ax.set_ylabel("작품적분 점유율(%)")
ax.set_ylim(0, 108)
ax.legend(frameon=False, loc="lower right")
fig.tight_layout()
fig.savefig(FIG / "fig3_score_concentration.png", bbox_inches="tight")
plt.close(fig)

# 검증 출력: 본문 인용 수치와의 정합
print("fig1 爱情:", {y: round(d1['爱情'][i],1) for i,y in enumerate(YEARS) if y in (2003,2010,2018,2024,2026)})
print("fig1 剧情:", {y: round(d1['剧情'][i],1) for i,y in enumerate(YEARS) if y in (2020,2024)})
print("fig2 东方衍生:", {y: round(d2['东方衍生'][i],1) for i,y in enumerate(YEARS) if y in (2010,2024)})
print("saved 3 figures + 3 data CSVs")
