# 보충자료 E — 자료 가용성 진술과 편집 정합 점검

> 심사 요구 대응: "데이터·코드·대시보드 링크의 실재, 그림 수·번호-참조·서지 정합".

## 1. 자료 가용성 진술 (원고 §2.3 문안의 근거)

원고 §2.3의 진술(2026-09-06 확정): 재현 패키지를 공개 저장소에 공개하고, 작품 단위 원자료는
연구 목적의 합리적 요청 시 제공한다.

- **공개 저장소(연구자 승인, 2026-09-06 게시)**: https://github.com/tgrlyu/jjwxc-dual-market-genre-dynamics
  — 수집·분석 코드(07–16, 20–28), 집계 CSV 전량, gap 실측 JSON, `claims_crosscheck.csv`,
  `codebook_recomposition_check.csv`, `script_manifest.csv`(SHA-256), 보충자료 A–E.
- 제공 유보 범위와 사유: 원시 페이지 원문 전량(플랫폼 약관·용량), 로그인 쿠키·계정 정보(비공개 원칙),
  `analysis_master.sqlite` 원본과 표본 검수표(작가 필명·작품 단위 기록 포함 — 집계 CSV로 갈음,
  재수집 불가능한 배타적 자료로서 연구 목적의 합리적 요청 시에만 재배포 금지 조건으로 제공).

### 확정된 결정 (2026-09-06, 연구자 승인)

1. 공개 방식: 위 GitHub 저장소에 코드·집계 산출물·보충자료만 공개, 작품 단위 원자료는 비공개
   (요청 시 제공). §2.3 문장을 저장소 링크로 승격 완료.
2. AI 고지 수준: 원고 §2.3 말미에 1문장 고지(도구·범위·인간 책임), 전체 역할 명세는 보충자료 D.
3. 표본 검수: 연구자(류호현)가 수행.

## 2. 편집 정합 점검 (2026-09-06 빌드 기준)

| 항목 | 결과 |
|---|---|
| 그림 번호-참조 | 그림 1–4 각 1회 이상 본문 지시(<그림 n>), 캡션 위치 일관, 등장 순서와 번호 일치 |
| 표 번호-참조 | 표 1–5 동일 (표 3 신설에 따른 구 표 3→4, 표 4→5 재번호 및 본문 참조 갱신 확인) |
| placeholder | 0건 (본문·서지에 미확정 표기 없음) |
| 미인용 서지 | 0건 (초고의 미인용 2건 — 安静·张妮 2022, 田丽·李彤 2021 — 삭제) |
| 내주-서지 매칭 | 전 내주의 저자·연도가 참고문헌 항목과 대응(2015 지도의견은 "2014년 12월 인발, 2015년 1월 공포" 병기로 해소) |
| 무표식 조판 게이트 | document.xml의 keepNext·keepLines·pageBreakBefore·widowControl·numPr 각 0; 적용 스타일(Normal·TableGrid·Caption) 청정; 추적변경·주석 0 |
| 전면 렌더 검수 | LibreOffice 렌더 23쪽 전량 육안 확인(비인쇄 표식·불릿·표 깨짐 없음) |

## 3. 재현 실행 순서 (요청 시 제공 패키지의 사용법)

```
# 1) 분석 DB 구축 (수집 산출물 → SQLite)
python3 scripts/20_build_analysis_master.py
# 2) 집계·키워드·작가 동학
python3 scripts/21_genre_keyword_author_dynamics.py
# 3) 그림 1·2·4(적분) + 근거 CSV
python3 scripts/23_make_figures.py
# 4) 성향 CSV 일치 검증 + 그림 3(파생 성향)
python3 scripts/25_orientation_analysis.py
# 5) 적분 민감도
python3 scripts/26_score_sensitivity.py
# 6) 분해 규칙 검증 + 표본 검수표
python3 scripts/28_codebook_validation.py
# 7) 원고 빌드
python3 scripts/24_build_kci_submission.py
# 8) 수치 전수 대조 (모든 수치 재검증; FAIL 시 종료코드 1)
python3 scripts/27_claims_crosscheck.py
```
