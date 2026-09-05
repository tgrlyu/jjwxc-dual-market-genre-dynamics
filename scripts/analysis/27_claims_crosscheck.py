#!/usr/bin/env python3
"""투고본 본문·표·초록 수치의 전수 기계 대조 (보충자료 D의 산출 스크립트).

원고(진강문학성_이중시장_장르동학_KCI투고본)의 모든 데이터 기반 수치 주장을
claim 단위로 등재하고, 산출물(CSV·JSON·DB)에서 재계산한 값과 대조한다.
본문에 반올림 표기된 값은 반올림 규칙을 적용해 비교한다.
산출: outputs/claims_crosscheck.csv (claim_id, 위치, 주장, 산출값, 판정)
실패가 1건이라도 있으면 종료코드 1.
"""
import sqlite3, csv, json, statistics, sys
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "outputs"
GAP = PROJ.parent / "20260626_jinjiang-genre-trends" / "outputs"
con = sqlite3.connect(PROJ / "data" / "analysis_master.sqlite")

# ── 산출물 적재 ──
genre = {(r["market"], r["genre"], int(r["year"])): float(r["share_pct"])
         for r in csv.DictReader(open(OUT / "v2b_genre_yearly_share.csv"))}
orient = {(r["market"], r["orientation"], int(r["year"])): float(r["share_pct"])
          for r in csv.DictReader(open(OUT / "v2b_orientation_yearly_share.csv"))}
kw = {r["keyword"]: int(r["count"]) for r in csv.DictReader(open(OUT / "v2b_genre_title_keywords.csv"))
      if r["market"] == "原创" and r["genre"] == "爱情"}
kw_pct = {r["keyword"]: float(r["pct_of_genre"]) for r in csv.DictReader(open(OUT / "v2b_genre_title_keywords.csv"))
          if r["market"] == "原创" and r["genre"] == "爱情"}
burst = {(int(r["burst_year"]), r["keyword"]): (int(r["count"]), float(r["growth_x"]))
         for r in csv.DictReader(open(OUT / "v2b_yearly_title_keywords.csv"))}
ae = {(r["genre"], r["period"]): r for r in csv.DictReader(open(OUT / "v2b_author_entry_exit.csv"))}
sens_y = {int(r["year"]): r for r in csv.DictReader(open(OUT / "v2d_score_sensitivity_yearly.csv"))}
sens_p = {r["period"]: r for r in csv.DictReader(open(OUT / "v2d_score_period_median.csv"))}
gap_rate = json.load(open(GAP / "v2_gap_rate_temporally_adjusted.json"))
gap_comp = json.load(open(GAP / "v2_gap_composition_robustness.json"))

CLAIMS = []


def claim(cid, loc, desc, claimed, computed, tol=0.051):
    if isinstance(claimed, str):
        ok = str(claimed) == str(computed)
    else:
        ok = abs(float(claimed) - float(computed)) <= tol
    CLAIMS.append([cid, loc, desc, claimed, round(computed, 3) if isinstance(computed, float) else computed,
                   "PASS" if ok else "FAIL"])


def db1(sql, *args):
    return con.execute(sql, args).fetchone()[0]


# ── §2.1 모수 ──
total = db1("SELECT COUNT(*) FROM analysis_master")
orig = db1("SELECT COUNT(*) FROM analysis_master WHERE originality='原创'")
deriv = db1("SELECT COUNT(*) FROM analysis_master WHERE originality='衍生'")
untag = db1("SELECT COUNT(*) FROM analysis_master WHERE originality NOT IN ('原创','衍生')")
claim("M1", "§2.1", "총 작품 수", 3856274, total, 0)
claim("M2", "§2.1", "원창 건수", 2818576, orig, 0)
claim("M3", "§2.1", "파생 건수", 572721, deriv, 0)
claim("M4", "§2.1", "미표기 건수", 464977, untag, 0)
claim("M5", "§2.1", "원창 비중 73.1%", 73.1, orig / total * 100)
claim("M6", "§2.1", "파생 비중 14.9%", 14.9, deriv / total * 100)
claim("M7", "§2.1", "미표기 비중 12.1%", 12.1, untag / total * 100)

# ── §2.2 / 표1 수집 편향 ──
claim("G1", "표1", "완결작 누락률(보정) 0.13%", 0.13, gap_rate["01-finished"]["gap_rate_adjusted_pct"], 0.005)
claim("G2", "표1", "연재·파생 누락률(보정) 14.46%", 14.46, gap_rate["02-ongoing-derivative"]["gap_rate_adjusted_pct"], 0.005)
claim("G3", "표1", "연재·원작 누락률(보정) 12.83%", 12.83, gap_rate["03-ongoing-original-mv1"]["gap_rate_adjusted_pct"], 0.005)
claim("G4", "표1", "완결 무일자 25.5%", 25.5, gap_rate["01-finished"]["undated_pct"], 0.05)
claim("G5", "표1", "연재·파생 무일자 92.6%", 92.6, gap_rate["02-ongoing-derivative"]["undated_pct"], 0.05)
claim("G6", "표1", "연재·원작 무일자 83.0%", 83.0, gap_rate["03-ongoing-original-mv1"]["undated_pct"], 0.05)
claim("G7", "§2.2", "누락분 기타연생 21.1% 대 포착분 13.6%", 21.1,
      dict((g, gp) for g, cp, gp in gap_comp["02-ongoing-derivative"]["top_genres_[captured%,gap%]"])["其他衍生"], 0.05)

# ── §3.1 원창 장르 ──
for cid, y, v in [("A1", 2003, 80.8), ("A2", 2010, 88.2), ("A3", 2017, 81.9), ("A4", 2018, 74.2),
                  ("A5", 2019, 68.1), ("A6", 2023, 59.5), ("A7", 2024, 56.4)]:
    claim(cid, "§3.1", f"애정 {y}년 {v}%", v, genre[("原创", "爱情", y)])
claim("A8", "§3.1", "정점 대비 하락 31.8%p", 31.8, genre[("原创", "爱情", 2010)] - genre[("原创", "爱情", 2024)])
claim("A9", "§3.1", "2008–14 애정 하한 84.1%", 84.1, min(genre[("原创", "爱情", y)] for y in range(2008, 2015)))
claim("A10", "§3.1", "2015–17 애정 하한 81.9%", 81.9, min(genre[("原创", "爱情", y)] for y in range(2015, 2018)))
claim("A11", "§3.1", "2025–26 애정 58%대", 58.0, min(genre[("原创", "爱情", 2025)], genre[("原创", "爱情", 2026)]), 0.5)
claim("J1", "§3.1/표2", "극정 2019년 5.0%", 5.0, genre[("原创", "剧情", 2019)])
claim("J2", "§3.1", "극정 2020년 9.0%", 9.0, genre[("原创", "剧情", 2020)])
claim("J3", "§3.1", "극정 2024년 14.6%", 14.6, genre[("原创", "剧情", 2024)])
j2018 = db1("SELECT COUNT(*) FROM analysis_master WHERE originality='原创' AND genre='剧情' AND publish_year='2018'") / \
        db1("SELECT COUNT(*) FROM analysis_master WHERE originality='原创' AND publish_year='2018'") * 100
claim("J4", "표2/§4.3", "극정 2018년 0.4%", 0.4, j2018)

# ── §3.2 파생 시장 ──
for cid, y, v in [("D1", 2009, 96.1), ("D2", 2010, 95.8), ("D3", 2017, 85.0), ("D4", 2018, 65.9), ("D5", 2019, 30.6)]:
    claim(cid, "§3.2", f"동방연생 {y}년 {v}%", v, genre[("衍生", "东方衍生", y)])
claim("D6", "§3.2", "2024 기타연생 34.8%", 34.8, genre[("衍生", "其他衍生", 2024)])
claim("D7", "§3.2", "2024 경소설 24.0%", 24.0, genre[("衍生", "轻小说", 2024)])
claim("D8", "§3.2", "2024 동방연생 23.6%", 23.6, genre[("衍生", "东方衍生", 2024)])
claim("D9", "§3.2", "2024 서방연생 14.3%", 14.3, genre[("衍生", "西方衍生", 2024)])
claim("D10", "§4.2", "파생 경소설 2017 2.1%", 2.1, genre[("衍生", "轻小说", 2017)])
claim("D11", "§4.2", "파생 경소설 2018 10.2%", 10.2, genre[("衍生", "轻小说", 2018)])
claim("D12", "§4.2/표2", "파생 경소설 2019 25.5%", 25.5, genre[("衍生", "轻小说", 2019)])
claim("D13", "§4.2", "서방연생 2017 6.7%", 6.7, genre[("衍生", "西方衍生", 2017)])
claim("D14", "§4.2", "서방연생 2019 12.0%", 12.0, genre[("衍生", "西方衍生", 2019)])

# ── §3.2 파생 성향 / 그림3 ──
claim("DO1", "§3.2", "파생 언정 2010 50.1%", 50.1, orient[("衍生", "言情", 2010)])
claim("DO2", "§3.2", "파생 언정 2017 52.0%", 52.0, orient[("衍生", "言情", 2017)])
claim("DO3", "§3.2", "파생 언정 2024 41.8%", 41.8, orient[("衍生", "言情", 2024)])
claim("DO4", "§3.2", "파생 순애 2010 44.1%", 44.1, orient[("衍生", "纯爱", 2010)])
claim("DO5", "§3.2", "파생 순애 2024 23.9%", 23.9, orient[("衍生", "纯爱", 2024)])
claim("DO6", "그림3 캡션", "파생 2003년 소표본 132건", 132,
      db1("SELECT COUNT(*) FROM analysis_master WHERE originality='衍生' AND publish_year='2003'"), 0)
deriv_cnt = {}
for r in csv.DictReader(open(OUT / "v2b_orientation_yearly_share.csv")):
    if r["market"] == "衍生":
        deriv_cnt.setdefault(int(r["year"]), {})[r["orientation"]] = int(r["count"])
top_by_year = {y: max(d, key=d.get) for y, d in deriv_cnt.items()}
claim("DO7", "§3.2", "파생 2003–06년 순애 우위", "纯爱,纯爱,纯爱,纯爱",
      ",".join(top_by_year[y] for y in range(2003, 2007)))
claim("DO8", "§3.2/결론", "파생 2007년 이후 언정 일관 1위", "OK",
      "OK" if all(top_by_year[y] == "言情" for y in range(2007, 2027)) else
      str([y for y in range(2007, 2027) if top_by_year[y] != "言情"]))
claim("DO9", "§3.2", "파생 2006년 총 4,220건", 4220,
      db1("SELECT COUNT(*) FROM analysis_master WHERE originality='衍生' AND publish_year='2006'"), 0)

# ── §3.3 원창 성향 ──
for cid, y, v in [("O1", 2003, 89.1), ("O2", 2010, 69.6), ("O3", 2015, 61.3), ("O4", 2020, 48.3),
                  ("O5", 2021, 45.8), ("O6", 2022, 54.4), ("O7", 2024, 44.8), ("O8", 2026, 40.2)]:
    claim(cid, "§3.3", f"원창 언정 {y}년 {v}%", v, orient[("原创", "言情", y)])
for cid, y, v in [("P1", 2010, 24.2), ("P2", 2021, 39.2), ("P3", 2022, 30.6), ("P4", 2024, 34.1),
                  ("P5", 2026, 38.2), ("P6", 2015, 27.4)]:
    claim(cid, "§3.3/§4.1", f"원창 순애 {y}년 {v}%", v, orient[("原创", "纯爱", y)])
claim("P7", "§3.3", "순애 급락 8.6%p", 8.6, orient[("原创", "纯爱", 2021)] - orient[("原创", "纯爱", 2022)])
claim("P8", "§3.3", "언정 반등 8.6%p", 8.6, orient[("原创", "言情", 2022)] - orient[("原创", "言情", 2021)])
claim("P9", "§3.3/§4.4/결론", "다원 2024 4.0%", 4.0, orient[("原创", "多元", 2024)])
claim("P10", "§3.3/§4.4/결론", "다원 2025 7.0%", 7.0, orient[("原创", "多元", 2025)])
claim("P11", "§4.4", "다원 2023년분 0.3%", 0.3, orient[("原创", "多元", 2023)])

# ── §5 키워드 / 표3·표4 ──
top10 = [("重生", 33087), ("快穿", 27583), ("穿越", 19234), ("喜欢", 16352), ("恋爱", 15263),
         ("穿书", 13347), ("爱情", 13230), ("世界", 12338), ("暗恋", 11699), ("反派", 10433)]
ranked = sorted(kw.items(), key=lambda x: -x[1])[:10]
claim("K0", "표3", "상위 10위 키워드 순서", ",".join(k for k, _ in top10), ",".join(k for k, _ in ranked))
for i, (k, v) in enumerate(top10, 1):
    claim(f"K{i}", "표3", f"{k} {v:,}건", v, kw[k], 0)
claim("K11", "§5.1", "장치 어휘군 합산 105,589건", 105589,
      sum(kw[k] for k in ["重生", "快穿", "穿越", "穿书", "世界"]), 0)
claim("K12", "§5.1", "감정 어휘군 합산 56,544건", 56544,
      sum(kw[k] for k in ["喜欢", "恋爱", "爱情", "暗恋"]), 0)
claim("K13", "§5.1", "장치/감정 약 1.9배", 1.9, 105589 / 56544)
for cid, y, k, cnt, gx in [("B1", 2006, "清宫", 112, 22.4), ("B2", 2013, "女配", 287, 12.5),
                           ("B3", 2013, "逆袭", 143, 14.8), ("B4", 2014, "快穿", 466, 17.9),
                           ("B5", 2017, "电竞", 158, 12.8), ("B6", 2018, "佛系", 178, 38.1),
                           ("B7", 2019, "穿书后", 211, 27.5), ("B8", 2020, "团宠", 352, 12.0),
                           ("B9", 2020, "绿茶", 434, 10.9), ("B10", 2022, "摆烂", 701, 35.0),
                           ("B11", 2022, "恋综", 408, 13.2)]:
    claim(cid, "표4", f"{y} {k} {cnt}건", cnt, burst[(y, k)][0], 0)
    claim(cid + "x", "표4", f"{y} {k} {gx}배", gx, burst[(y, k)][1], 0.05)

# ── §6.1 / 표5 작가 동학 ──
love = {p: ae[("爱情", p)] for p in ["P1_2003-2009", "P2_2010-2016", "P3_2017-2019", "P4_2020-2023", "P5_2024-2026"]}
debut_rates = [int(r["genre_debut"]) / int(r["active_authors"]) * 100 for p, r in love.items() if p != "P1_2003-2009"]
claim("W1", "§6.1", "데뷔율 상한 97.2%", 97.2, max(debut_rates))
claim("W2", "§6.1", "데뷔율 하한 85.0%", 85.0, min(debut_rates))
prev_active = [int(love[p]["active_authors"]) for p in ["P1_2003-2009", "P2_2010-2016", "P3_2017-2019", "P4_2020-2023"]]
retained = [int(love[p]["retained"]) for p in ["P2_2010-2016", "P3_2017-2019", "P4_2020-2023", "P5_2024-2026"]]
ret_rates = [r / a * 100 for r, a in zip(retained, prev_active)]
claim("W3", "§6.1", "잔존율 하한 5.1%", 5.1, min(ret_rates))
claim("W4", "§6.1", "잔존율 상한 11.6%", 11.6, max(ret_rates))
claim("W5", "§6.1", "잔존 8,269→22,508명", 22508, int(love["P4_2020-2023"]["retained"]), 0)
jj = {p: ae[("剧情", p)] for p in ["P3_2017-2019", "P4_2020-2023"]}
claim("W6", "§6.1", "극정 작가 6,654→99,434 (15배)", 14.9, int(jj["P4_2020-2023"]["active_authors"]) / int(jj["P3_2017-2019"]["active_authors"]), 0.05)
claim("W7", "§6.1", "극정 신규 데뷔 93.7%", 93.7, int(jj["P4_2020-2023"]["genre_debut"]) / int(jj["P4_2020-2023"]["active_authors"]) * 100)

# ── §6.2 / 그림4 수용 집중 ──
for cid, p, v in [("S1", "P1 2003–09", 65.64), ("S2", "P2 2010–16", 74.88), ("S3", "P3 2017–19", 67.63),
                  ("S4", "P4 2020–23", 74.95), ("S5", "P5 2024–26", 73.22)]:
    claim(cid, "§6.2/그림4", f"{p} 상위1% {v}%", v, float(sens_p[p]["top1pct_share"]), 0.005)
claim("S6", "§6.2", "P4 상위10% 99.1%", 99.11, float(sens_p["P4 2020–23"]["top10pct_share"]), 0.005)
claim("S7", "§6.2", "중앙값 P3 86,285점", 86285, int(sens_p["P3 2017–19"]["median_score"]), 0)
claim("S8", "§6.2", "중앙값 P4 42,291점", 42291, int(sens_p["P4 2020–23"]["median_score"]), 0)
y_vals = [float(sens_y[y]["top1pct_share"]) for y in range(2010, 2027)]
claim("S9", "§6.2", "연도 코호트 하한 64.9%", 64.9, min(y_vals))
claim("S10", "§6.2", "연도 코호트 상한 76.9%", 76.9, max(y_vals))
claim("S11", "§6.2", "priest 원창 작품 35편", 35,
      db1("SELECT COUNT(*) FROM analysis_master WHERE author='priest' AND originality='原创'"), 0)
claim("S12", "§6.2", "墨香铜臭 원창 작품 3편", 3,
      db1("SELECT COUNT(*) FROM analysis_master WHERE author='墨香铜臭' AND originality='原创'"), 0)

# ── 결과 저장 ──
with open(OUT / "claims_crosscheck.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["claim_id", "location", "claim", "claimed", "computed", "verdict"])
    w.writerows(CLAIMS)

fails = [c for c in CLAIMS if c[5] == "FAIL"]
print(f"총 {len(CLAIMS)}건 대조: PASS {len(CLAIMS) - len(fails)} / FAIL {len(fails)}")
for c in fails:
    print("  FAIL:", c)
sys.exit(1 if fails else 0)
