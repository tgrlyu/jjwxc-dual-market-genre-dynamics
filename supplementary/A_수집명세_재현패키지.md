# 보충자료 A — 수집 명세와 재현 패키지

> 심사 요구 대응: "API 호출식·수집 일시·레코드 식별자·중복/결측/제외 처리·정제 코드·최종 데이터 파일을
> 담은 재현 패키지". 아래의 모든 항목은 실재하는 산출물 경로를 지시하며, 날조된 값은 없다.

## 1. 수집 대상과 요청식

- 대상: 진강문학성 작품고(作品库) 공개 목록 `https://www.jjwxc.net/bookbase.php`.
  소설 본문·댓글·계정정보·비공개 자료는 수집 대상이 아니다.
- 기본 검색식(2026-07-11 확인): `bookbase.php?s_typeid=1&version=1&fw=0&yc=0&xx=0&mainview=0&sd=0&lx=0&bq=-1&submit=…`
  동적 파라미터(`sign`·`time`·`jsver`)는 실행 시점 값으로, 문서·manifest에 보존하지 않는다.
- 수집 열(플랫폼 원문 헤더): `作者`·`作品`·`类型`·`进度`·`字数`·`作品积分`·`发表时间`.
- robots.txt 및 공개 목록 접근 정책은 수집 개시 전 확인했고, 로그인 세션(연구자 본인 계정)을 사용했다.
  쿠키 값·계정 식별정보는 어떤 산출물에도 전사하지 않았다.

## 2. 수집 실행 명세

| 수집 | 일시(KST) | 파티션 설계 | 실행 스크립트 |
|---|---|---|---|
| 연도 필터 본수집 | 2026-07-11 ~ 07-14 | 발표연도 필터 24개(2003–2026) | `20260626/scripts/07_crawl_jjwxc_public_metadata.py`, `08_run_jjwxc_partitioned_crawl.py` |
| 독립 검증 수집 | 2026-07-18 ~ 07-20 | 진행상태×원창성×시각×시대 14개(연도 축 불사용, 각 파티션 1만 페이지 미만) | `12_run_jjwxc_exhaustive_crawl.py` (계획: `16_plan_shallow_partitions.py`, `JJWXC_CRAWL_RUNBOOK.md`) |

- 저부하 원칙: 단일 접속, 요청 간 2초 이상 간격, 실패 페이지는 `--page-failure-policy continue`로 건너뛰고 기록.
- 보존: 페이지 원문(gzip), SHA-256 해시, 수집 시각을 파티션별 manifest에 저장
  (`20260626/data/jjwxc_partitioned_2026-07-11-cookie/`, `jjwxc_exhaustive_2026-07-17/`, `jjwxc_exhaustive_2026-07-18/`).
- 플랫폼 접근 제한: 2026-07-20 이후 목록 깊은 페이지 접근이 약 100페이지로 제한되었고
  2026-09-06 최종 확인 시점까지 유지 — 원고 §2.1에 명시. 독립 수집의 미완 파티션은 이 제한으로 중단되었다.

## 3. 레코드 식별자와 처리 흐름

| 단계 | 규칙 | 결과 |
|---|---|---:|
| 원시 페이지 → 행 파싱 | 목록 표의 행 단위 추출, 작품 상세 링크의 novelid를 `work_id`로 채록 | 파티션별 manifest |
| 파티션 통합·중복 제거 | `work_id` 기준 dedup (`09_merge_jjwxc_partitions.py`) | 3,856,274건 확정 |
| 발표연도 | 연도 파티션 소속으로 부여(`partition_year`) — 결측 0건 | 24개 연도 |
| 시장 분해 | `类型` 1번째 토큰: 原创 2,818,576 / 衍生 572,721 / 미표기 464,977 | 보충자료 B |
| 미표기(12.1%) 처리 | 임의 배정 금지, 별도 층 유지, 시장별 수치에서 제외 | 원고 §2.1 |
| 분석 DB 구축 | `scripts/20_build_analysis_master.py` → `data/analysis_master.sqlite` (5축 분해 포함) | 3,856,274행 |

- 독립 수집과의 대조(누락률 실측)는 `20260626/scripts/14_characterize_year_partition_gap.py`,
  `15_isolate_year_partition_gap.py` → `20260626/outputs/v2_gap_rate_temporally_adjusted.json`,
  `v2_gap_composition_robustness.json` (원고 표 1·§2.2의 유일 전거).

## 4. 스크립트·산출물 대응표

실행 순서와 무결성 해시는 `outputs/script_manifest.csv`(SHA-256, 2026-09-06 기준)에 고정했다.

| 원고 요소 | 산출 스크립트 | 근거 데이터 파일 |
|---|---|---|
| §2.1 모수·§2.2 표 1 | 20, 20260626/14·15 | `analysis_master.sqlite`, `v2_gap_*.json` |
| 그림 1·2, §3.1–3.2 장르 | 23 | `outputs/v2c_fig1_data.csv`, `v2c_fig2_data.csv`, `v2b_genre_yearly_share.csv` |
| 그림 3, §3.2–3.3 성향 | 25 | `outputs/v2c_fig5_data.csv`, `v2c_fig4_data.csv`, `v2b_orientation_yearly_share.csv` |
| 표 3·표 4, 5장 키워드 | 21 | `outputs/v2b_genre_title_keywords.csv`, `v2b_yearly_title_keywords.csv` |
| 표 5, §6.1 작가 동학 | 21 | `outputs/v2b_author_entry_exit.csv`, `v2b_author_cohort_impact.csv` |
| 그림 4, §6.2 수용 집중 | 23, 26 | `outputs/v2c_fig3_data.csv`, `v2d_score_period_median.csv`, `v2d_score_sensitivity_yearly.csv` |
| 원고 DOCX 조판 | 24 | 위 전부 |
| 수치 전수 대조 | 27 | `outputs/claims_crosscheck.csv` |
| 분해 규칙 검증 | 28 | `outputs/codebook_recomposition_check.csv`, `codebook_sample_200.csv` |

## 5. 재현 한계의 명시

- 플랫폼 목록은 라이브 갱신되므로(무필터 페이지 수가 관측 중에도 45,262→45,329로 변동) 동일 요청식의
  재실행이 동일 스냅샷을 반환하지 않는다. 재현성은 (i) 보존된 페이지 원문·해시로부터의 결정론적 재계산과
  (ii) 2026-07-20 이후의 접근 제한 기록으로 정의된다.
- 원시 페이지 원문 전량의 외부 공개는 플랫폼 약관·용량 문제로 유보하며, `work_id` 목록·해시·집계 CSV의
  제공으로 갈음한다(보충자료 E의 결정 대기 항목).
