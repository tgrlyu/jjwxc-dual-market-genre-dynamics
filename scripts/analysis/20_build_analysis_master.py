#!/usr/bin/env python3
"""연도합계 완성 데이터(3,856,274작품, 2026-07-11/14 수집)를 단일 분석 마스터로 통합.

72개 shard(route × year)를 읽어 genre_full 토큰을 originality/orientation/era/genre/perspective로
분해하고, publish_year를 정규화한 analysis_master 테이블을 만든다. 이 테이블이 Phase A(표본비교)와
Phase B(장르·키워드·작가 동학)의 유일한 denominator다.

주의: 이 데이터는 '연도필터로 수집된' 3.86M이며, 연재중 무날짜 작품 누락 편향이 있다
([[jjwxc-year-filter-gap-finding]]). 최근 1~2개 연도 총량 해석 시 caveat 필수.
"""
import sqlite3, glob, re, os
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
SRC = PROJ.parent / "20260626_jinjiang-genre-trends" / "data" / "jjwxc_partitioned_2026-07-11-cookie" / "merged"
OUT = PROJ / "data"
OUT.mkdir(exist_ok=True)
DB = OUT / "analysis_master.sqlite"


def norm_year(pt: str) -> str:
    if not pt:
        return ""
    m = re.search(r"(19|20)\d{2}", pt)
    return m.group(0) if m else ""


def tok(gf: str, i: int) -> str:
    p = (gf or "").split("-")
    return p[i].strip() if len(p) > i else ""


def originality(gf: str) -> str:
    if (gf or "").startswith("原创"):
        return "原创"
    if (gf or "").startswith("衍生"):
        return "衍生"
    return "unclassified"


def main():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)
    con.execute("""CREATE TABLE analysis_master(
        work_id TEXT, author TEXT, work_title TEXT, genre_full TEXT,
        originality TEXT, orientation TEXT, era TEXT, genre TEXT, perspective TEXT,
        progress TEXT, word_count INTEGER, score REAL, publish_year TEXT,
        route TEXT, partition_year INTEGER)""")
    shards = sorted(glob.glob(str(SRC / "route=*" / "year=*" / "records.sqlite")))
    seen = set()
    n = 0
    for sh in shards:
        route = sh.split("route=")[1].split("/")[0]
        c = sqlite3.connect(sh)
        rows = c.execute("""SELECT work_id,author,work_title,genre_full,progress,
                            word_count,score,publish_time,partition_year FROM records""").fetchall()
        c.close()
        batch = []
        for wid, au, wt, gf, pg, wc, sc, pt, py in rows:
            if wid in (None, "", "0") or wid in seen:
                continue
            seen.add(wid)
            try:
                wcv = int(re.sub(r"[^\d]", "", wc)) if wc else None
            except Exception:
                wcv = None
            try:
                scv = float(re.sub(r"[^\d.]", "", sc)) if sc else None
            except Exception:
                scv = None
            batch.append((wid, au, wt, gf, originality(gf), tok(gf, 1), tok(gf, 2),
                          tok(gf, 3), tok(gf, 4), pg, wcv, scv, norm_year(pt), route, py))
        con.executemany("INSERT INTO analysis_master VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        n += len(batch)
    con.commit()
    for col in ["originality", "genre", "orientation", "publish_year", "author", "route"]:
        con.execute(f"CREATE INDEX idx_{col} ON analysis_master({col})")
    con.commit()
    tot = con.execute("SELECT COUNT(*) FROM analysis_master").fetchone()[0]
    print(f"analysis_master rows: {tot:,} (deduped work_id across {len(shards)} shards)")
    print("originality:", dict(con.execute(
        "SELECT originality,COUNT(*) FROM analysis_master GROUP BY 1").fetchall()))
    print("publish_year 결측:", con.execute(
        "SELECT COUNT(*) FROM analysis_master WHERE publish_year=''").fetchone()[0])
    con.close()


if __name__ == "__main__":
    main()
