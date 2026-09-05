#!/usr/bin/env python3
"""类型 문자열 5축 분해 규칙의 검증 (보충자료 B의 산출 스크립트).

1) 전수 재조립 검증: 분해된 5개 필드(originality/orientation/era/genre/perspective)를
   규칙의 역방향으로 재조립했을 때 원문 genre_full과 일치하는 비율을 전수 계측한다.
2) 표본 검수표: 고정 시드 난수로 200건을 추출해 원문·분해 결과를 나란히 실은
   검수용 CSV를 생성한다(교수의 수기 표본 검수 대상).

산출:
- outputs/codebook_recomposition_check.csv (불일치 유형별 건수)
- outputs/codebook_sample_200.csv (표본 검수표; 검수 결과 기입란 포함)
"""
import sqlite3, csv, random
from pathlib import Path

PROJ = Path(__file__).resolve().parent.parent
OUT = PROJ / "outputs"
con = sqlite3.connect(PROJ / "data" / "analysis_master.sqlite")

rows = con.execute(
    "SELECT work_id, genre_full, originality, orientation, era, genre, perspective FROM analysis_master").fetchall()

total = len(rows)
exact = 0
mismatch_kinds = {}
mismatches = []
for wid, gf, o1, o2, o3, o4, o5 in rows:
    gf = gf or ""
    if o1 == "unclassified":
        # 원창성 미표기: 분해 규칙상 5토큰 구조가 아닌 문자열
        recomposed = None
        kind = "unclassified(미표기층)"
        mismatch_kinds[kind] = mismatch_kinds.get(kind, 0) + 1
        continue
    recomposed = "-".join([o1 or "", o2 or "", o3 or "", o4 or "", o5 or ""])
    if recomposed == gf:
        exact += 1
    else:
        kind = f"토큰수 {gf.count('-')+1}"
        mismatch_kinds[kind] = mismatch_kinds.get(kind, 0) + 1
        if len(mismatches) < 50:
            mismatches.append([wid, gf, recomposed])

with open(OUT / "codebook_recomposition_check.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["category", "count", "pct_of_total"])
    w.writerow(["total_rows", total, 100.0])
    w.writerow(["classified_exact_recomposition", exact, round(exact / total * 100, 3)])
    for k, v in sorted(mismatch_kinds.items()):
        w.writerow([k, v, round(v / total * 100, 3)])

classified = total - mismatch_kinds.get("unclassified(미표기층)", 0)
print(f"전수 {total:,}행 / 분류층 {classified:,}행 / 재조립 완전일치 {exact:,}행 "
      f"({exact / classified * 100:.4f}% of 분류층)")
for k, v in sorted(mismatch_kinds.items()):
    print(f"  {k}: {v:,}")
if mismatches:
    print("불일치 예시:", mismatches[:5])

# 표본 검수표 (고정 시드)
random.seed(20260906)
sample_ids = random.sample(range(len(rows)), 200)
with open(OUT / "codebook_sample_200.csv", "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["work_id", "genre_full(원문)", "originality", "orientation", "era", "genre",
                "perspective", "검수결과(O/X)", "비고"])
    for i in sorted(sample_ids):
        wid, gf, o1, o2, o3, o4, o5 = rows[i]
        w.writerow([wid, gf, o1, o2, o3, o4, o5, "", ""])
print("표본 검수표 200건 저장: outputs/codebook_sample_200.csv (seed=20260906)")
