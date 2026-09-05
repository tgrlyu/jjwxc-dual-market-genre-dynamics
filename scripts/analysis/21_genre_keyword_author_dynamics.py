#!/usr/bin/env python3
"""Phase B: 연도합계 완성 데이터(analysis_master) 심층 동학 분석.

산출:
  B1 연도별 장르 추세      -> v2b_genre_yearly_share.csv
  B2 장르별 제목 키워드    -> v2b_genre_title_keywords.csv
  B3 연도별 신생 키워드    -> v2b_yearly_title_keywords.csv
  B4 주요 작가별 키워드    -> v2b_top_author_keywords.csv
  B5 시기별 장르별 작가 유입/이탈 -> v2b_author_entry_exit.csv
  B6 작가 이동의 플랫폼 영향(score 집중) -> v2b_author_cohort_impact.csv

방법 주석:
- 제목 키워드는 중국어 2-4gram heavy-hitter 방식(v1 계승): 후보 사전선별 후 정확 카운트.
- 분모는 originality 시장별(原创/衍生) 분리(R1). unclassified는 별도 보고.
- score는 극단 롱테일이므로 분위수/집중도로만 사용(R: reception proxy).
- 연재중 무날짜 누락 편향 때문에 최근연도(2025-2026) 총량은 caveat 대상.
"""
import sqlite3, re, csv, collections, math
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
DB = PROJ / "data" / "analysis_master.sqlite"
OUT = PROJ / "outputs"
OUT.mkdir(exist_ok=True)
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

YEARS = [str(y) for y in range(2003, 2027)]
MARKETS = ["原创", "衍生"]
STOP = set("的了是我你他她们和与在有一不也就都而及其之为以於于对从被把让给之个这那")


def w(name, header, rows):
    with open(OUT / name, "w", newline="") as f:
        wr = csv.writer(f)
        wr.writerow(header)
        wr.writerows(rows)
    print(f"  {name}: {len(rows)}행")


def ngrams(title, n):
    t = re.sub(r"[\s\(\)\[\]（）【】\-_,，。·:：!！?？\"'“”‘’…]+", "", title or "")
    t = re.sub(r"[A-Za-z0-9]+", "", t)
    return [t[i:i+n] for i in range(len(t) - n + 1)]


# ---------- B1 연도별 장르 추세 (시장별) ----------
def b1():
    rows = []
    for mk in MARKETS:
        for y in YEARS:
            tot = con.execute("SELECT COUNT(*) FROM analysis_master WHERE originality=? AND publish_year=?",
                              (mk, y)).fetchone()[0]
            if tot == 0:
                continue
            for genre, c in con.execute(
                "SELECT genre,COUNT(*) FROM analysis_master WHERE originality=? AND publish_year=? "
                "GROUP BY genre ORDER BY 2 DESC LIMIT 8", (mk, y)):
                rows.append([mk, y, tot, genre or "(blank)", c, round(c/tot*100, 3)])
    w("v2b_genre_yearly_share.csv", ["market", "year", "year_total", "genre", "count", "share_pct"], rows)


# ---------- B2 장르별 제목 키워드 (시장별, 상위 장르만) ----------
def b2():
    rows = []
    for mk in MARKETS:
        top_genres = [r[0] for r in con.execute(
            "SELECT genre,COUNT(*) FROM analysis_master WHERE originality=? AND genre!='' "
            "GROUP BY genre ORDER BY 2 DESC LIMIT 6", (mk,))]
        # 전체 배경 빈도(해당 시장 전체)로 lift 계산
        for g in top_genres:
            titles = [r[0] for r in con.execute(
                "SELECT work_title FROM analysis_master WHERE originality=? AND genre=?", (mk, g))]
            cnt = collections.Counter()
            for t in titles:
                for n in (2, 3):
                    for gram in set(ngrams(t, n)):
                        if not any(ch in STOP for ch in gram):
                            cnt[gram] += 1
            base = len(titles)
            for kw, c in cnt.most_common(15):
                if c < 20:
                    continue
                rows.append([mk, g, base, kw, c, round(c/base*100, 3)])
    w("v2b_genre_title_keywords.csv", ["market", "genre", "genre_total", "keyword", "count", "pct_of_genre"], rows)


# ---------- B3 연도별 신생 키워드 (burst) ----------
def b3():
    # 원창 시장에서 연도별 title 2-3gram 카운트 -> 직전3년 대비 성장
    yearly = {}  # year -> Counter
    for y in YEARS:
        cnt = collections.Counter()
        for (t,) in con.execute(
            "SELECT work_title FROM analysis_master WHERE originality='原创' AND publish_year=?", (y,)):
            for n in (2, 3):
                for gram in set(ngrams(t, n)):
                    if not any(ch in STOP for ch in gram):
                        cnt[gram] += 1
        yearly[y] = cnt
    rows = []
    for i, y in enumerate(YEARS):
        if i < 3:
            continue
        prior = sum((yearly[YEARS[j]] for j in range(i-3, i)), collections.Counter())
        for kw, c in yearly[y].most_common(200):
            if c < 50:
                continue
            pv = prior.get(kw, 0) / 3
            growth = c / pv if pv >= 1 else (c if pv < 1 else 0)
            if growth >= 3 and c >= 80:
                rows.append([y, kw, c, round(pv, 1), round(growth, 1)])
    rows.sort(key=lambda r: (-r[4], -r[2]))
    w("v2b_yearly_title_keywords.csv", ["burst_year", "keyword", "count", "prior3y_avg", "growth_x"], rows[:120])


# ---------- B4 주요 작가별 키워드 (score 상위 작가) ----------
def b4():
    top_authors = [r[0] for r in con.execute(
        "SELECT author, SUM(score) s FROM analysis_master WHERE originality='原创' AND author!='' "
        "GROUP BY author ORDER BY s DESC LIMIT 40")]
    rows = []
    for au in top_authors:
        recs = con.execute(
            "SELECT work_title,genre,score,publish_year FROM analysis_master "
            "WHERE author=? AND originality='原创' ORDER BY score DESC", (au,)).fetchall()
        genres = collections.Counter(r[1] for r in recs if r[1])
        cnt = collections.Counter()
        for r in recs:
            for n in (2, 3):
                for gram in set(ngrams(r[0], n)):
                    if not any(ch in STOP for ch in gram):
                        cnt[gram] += 1
        works = len(recs)
        yspan = sorted(set(r[3] for r in recs if r[3]))
        top_genre = genres.most_common(1)[0][0] if genres else ""
        top_kw = ",".join(k for k, _ in cnt.most_common(5))
        rows.append([au, works, f"{yspan[0]}-{yspan[-1]}" if yspan else "", top_genre, top_kw])
    w("v2b_top_author_keywords.csv", ["author", "works", "active_years", "top_genre", "title_keywords"], rows)


# ---------- B5 시기별 장르별 작가 유입/이탈 ----------
PERIODS = [("P1_2003-2009", range(2003, 2010)), ("P2_2010-2016", range(2010, 2017)),
           ("P3_2017-2019", range(2017, 2020)), ("P4_2020-2023", range(2020, 2024)),
           ("P5_2024-2026", range(2024, 2027))]


def b5():
    # 각 시기에 '해당 장르로 데뷔(첫 등장)'한 작가 수와, 직전 시기 대비 이탈
    # 작가별 첫 출현 연도(원창)
    first = {}
    for au, y in con.execute(
        "SELECT author, MIN(CAST(publish_year AS INT)) FROM analysis_master "
        "WHERE originality='原创' AND author!='' AND publish_year!='' GROUP BY author"):
        first[au] = y
    rows = []
    top_genres = [r[0] for r in con.execute(
        "SELECT genre,COUNT(*) FROM analysis_master WHERE originality='原创' AND genre!='' "
        "GROUP BY genre ORDER BY 2 DESC LIMIT 8")]
    for g in top_genres:
        # 각 시기 활동 작가 집합
        act = {}
        for pname, yr in PERIODS:
            ys = tuple(str(y) for y in yr)
            q = f"SELECT DISTINCT author FROM analysis_master WHERE originality='原创' AND genre=? AND publish_year IN ({','.join('?'*len(ys))})"
            act[pname] = set(r[0] for r in con.execute(q, (g, *ys)) if r[0])
        pn = [p[0] for p in PERIODS]
        for i, pname in enumerate(pn):
            cur = act[pname]
            new_debut = sum(1 for a in cur if first.get(a, 9999) in range(int(PERIODS[i][1][0]), int(PERIODS[i][1][-1])+1))
            if i == 0:
                entered = len(cur); exited = 0; retained = 0
            else:
                prev = act[pn[i-1]]
                entered = len(cur - prev); exited = len(prev - cur); retained = len(cur & prev)
            rows.append([g, pname, len(cur), new_debut, entered, exited, retained])
    w("v2b_author_entry_exit.csv",
      ["genre", "period", "active_authors", "genre_debut", "entered_vs_prev", "exited_vs_prev", "retained"], rows)


# ---------- B6 작가 코호트의 플랫폼 영향 (score 집중) ----------
def b6():
    rows = []
    for pname, yr in PERIODS:
        ys = tuple(str(y) for y in yr)
        q = f"SELECT score FROM analysis_master WHERE originality='原创' AND score IS NOT NULL AND publish_year IN ({','.join('?'*len(ys))}) ORDER BY score DESC"
        scores = [r[0] for r in con.execute(q, ys)]
        if not scores:
            continue
        n = len(scores)
        total = sum(scores)
        top1 = sum(scores[:max(1, n//100)]) / total * 100 if total else 0
        top10 = sum(scores[:max(1, n//10)]) / total * 100 if total else 0
        # 상위 1% score 작품을 데뷔시기별로 귀속
        rows.append([pname, n, round(top1, 2), round(top10, 2), int(scores[0]), int(scores[n//2])])
    w("v2b_author_cohort_impact.csv",
      ["period", "works", "top1pct_score_share", "top10pct_score_share", "max_score", "median_score"], rows)


print("Phase B 분석 실행:")
b1(); b2(); b3(); b4(); b5(); b6()
con.close()
print("완료.")
