# 보충자료 E — 자료 가용성 진술과 편집 정합 점검

> 심사 요구 대응: "데이터·코드·대시보드 링크의 실재, 그림 수·번호-참조·서지 정합".

## 1. 자료 가용성 진술 (원고 §2.3 문안의 근거)

원고 §2.3의 진술: "모든 수치는 수집·정제·분석 스크립트와 산출 파일로 재현 가능하도록 보존하였으며,
수집 명세·분해 규칙 코드북·수치 검증표를 포함한 재현 패키지는 요청 시 제공한다."

- 요청 시 제공 범위: 보충자료 A–E 문서, `scripts/20–28`(+ 수집 스크립트 07–16), 집계 CSV 전량,
  `claims_crosscheck.csv`, `codebook_*.csv`, `script_manifest.csv`(SHA-256).
- 제공 유보 범위와 사유: 원시 페이지 원문 전량(플랫폼 약관·용량), 로그인 쿠키·계정 정보(비공개 원칙),
  `analysis_master.sqlite` 원본(작가 필명 전량 포함 — 집계 CSV로 갈음, 개별 필명의 대량 배포 회피).

### 결정 대기 항목 (연구자 결정 필요)

1. 공개 저장소(GitHub/Zenodo) 게시 여부 — 게시 시 §2.3 문장을 링크로 승격 가능.
   선행 논문(류호현 2025: 179 각주 10)은 rawdata 드라이브 링크를 제공한 전례가 있음.
2. AI 보조 관여의 원고 내 명시 수준 — 현재 원고 본문에는 미기재, 보충자료 D에 전체 명세.
   학술지 투고 규정의 AI 고지 요건 확인 후 결정.

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
