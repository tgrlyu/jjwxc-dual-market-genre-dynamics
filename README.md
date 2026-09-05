# Jinjiang Literature City Dual-Market Genre Dynamics (2003–2026)

진강문학성(晋江文学城) 원창·파생 이중시장의 장르 동학과 정책 국면 연구의 재현 패키지
(Reproduction package for a study of genre dynamics and policy conjunctures in Jinjiang
Literature City's original/derivative dual markets, 2003–2026).

- Author: Hohyun Lyu (류호현), Korea University
- Companion manuscript: "진강문학성 원창·파생 이중시장의 장르 동학과 정책 국면 —
  2003–2026년 연도별 전수 메타데이터(386만 건)의 분석, 변곡점-정책 연동 추론, 수집 편향 검증"
  (KCI 학술지 투고 원고, 2026)
- Prior study: Lyu, Hohyun (2025), 『중국문화연구』 67, 175-196. DOI 10.18212/cccs.2025..67.008

## What is here

| Path | Contents |
|---|---|
| `scripts/collection/` | Public-catalog metadata crawlers and partition/merge/gap-analysis tools (07–16) |
| `scripts/analysis/` | Analysis DB build, aggregation, figures, sensitivity, codebook validation, full numeric crosscheck (20–28) |
| `outputs/` | Aggregate result tables: market/genre/orientation yearly shares, title-keyword tables, author-dynamics aggregates, score-concentration and exposure-sensitivity tables, the 126-claim numeric crosscheck log, decomposition-rule validation, and a SHA-256 script manifest |
| `gap/` | Year-filter omission measurements from the independent verification crawl (basis of the paper's Table 1) |
| `supplementary/` | Supplementary materials A–E: collection specification, codebook, metric specification and sensitivity analysis, verification log with AI-assistance disclosure, availability statement |

Every number in the manuscript's text, tables, and figures can be recomputed from the
aggregate tables here; `scripts/analysis/27_claims_crosscheck.py` is the machine
cross-check that enforces this (126/126 PASS as of 2026-09-06).

## Data policy

- **Included**: derived aggregate statistics only (yearly composition shares, keyword
  frequency tables, cohort aggregates). These contain no work-level records.
- **Not included**: the work-level catalog dataset (3,856,274 rows incl. pen names) and
  raw page archives. The platform imposed a deep-page access restriction in July 2026,
  making re-collection infeasible; the row-level dataset is therefore held by the author
  and is available for legitimate research purposes upon reasonable request
  (no redistribution). Contact: tgrlyu@korea.ac.kr
- Collection used only the platform's public catalog listing (no story texts, comments,
  or account data), single-connection requests at ≥2-second intervals. Session cookies
  are supplied externally at runtime and are never stored in code or outputs.

## Rights

© 2026 Hohyun Lyu. All rights reserved. Code and documents are provided for review and
research reproduction; please cite the companion manuscript (or the 2025 prior study)
when using these materials. AI-assisted components are disclosed in
`supplementary/D_수치검증로그.md`.
