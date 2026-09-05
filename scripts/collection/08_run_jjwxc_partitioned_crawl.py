#!/usr/bin/env python3
"""Plan and run a year-partitioned JJWXC metadata crawl.

Deep offsets in the unfiltered 45k-page catalog are not reliably served even
in an authenticated browser. Publication-year filters (``fbsjYYYY=YYYY``)
provide bounded checkpoint units, but records without a filterable year mean
that their union is not a complete catalog partition. This orchestrator plans
and runs one crawl per year, then leaves catalog completeness unresolved until
the residual audit is reconciled. A fresh signed base URL is a runtime input
and is never written to committed outputs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRAWLER = Path(__file__).with_name("07_crawl_jjwxc_public_metadata.py")
MERGER = Path(__file__).with_name("09_merge_jjwxc_partitions.py")
DATA_ROOT = PROJECT_ROOT / "data"
GIB = 1024**3
DEFAULT_MIN_FREE_GIB = 30.0


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def year_url(base_url: str, year: int) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    segments = []
    for segment in parsed.query.split("&"):
        raw_key = segment.split("=", 1)[0]
        key = urllib.parse.unquote_plus(raw_key, encoding="ascii", errors="replace")
        if key == "yc" or re.fullmatch(r"fbsj\d{4}", key):
            continue
        segments.append(segment)
    segments.extend(("yc=0", f"fbsj{year}={year}"))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "&".join(segments), "")
    )


def child_command(
    *,
    url: str,
    vintage: str,
    output_root: Path,
    cookie_file: Path | None,
    ca_file: Path | None,
    delay: float,
    jitter: float,
    raw_policy: str,
    expected_pages: int | None = None,
    max_pages: int | None = None,
) -> list[str]:
    command = [
        sys.executable,
        CRAWLER.as_posix(),
        "--base-url",
        url,
        "--vintage",
        vintage,
        "--output-root",
        output_root.as_posix(),
        "--delay-seconds",
        str(delay),
        "--jitter-seconds",
        str(jitter),
        "--raw-policy",
        raw_policy,
        "--json",
    ]
    if cookie_file:
        command.extend(("--cookie-file", cookie_file.as_posix()))
    if ca_file:
        command.extend(("--ca-file", ca_file.as_posix()))
    if expected_pages is not None:
        command.extend(("--expected-pages", str(expected_pages)))
    if max_pages is not None:
        command.extend(("--max-pages", str(max_pages)))
    return command


def run_child(command: list[str], label: str) -> dict[str, object]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        tail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no detail"
        raise RuntimeError(f"{label} failed with exit {result.returncode}: {tail[:500]}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def storage_status(path: Path, min_free_gib: float) -> dict[str, object]:
    probe = path.resolve()
    while not probe.exists() and probe != probe.parent:
        probe = probe.parent
    usage = shutil.disk_usage(probe)
    free_gib = usage.free / GIB
    return {
        "probe_path": probe.as_posix(),
        "free_bytes": usage.free,
        "free_gib": round(free_gib, 2),
        "minimum_free_gib": min_free_gib,
        "ready": free_gib >= min_free_gib,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run year-partitioned JJWXC metadata crawl.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--vintage", default=dt.date.today().isoformat())
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--year-start", type=int, default=2003)
    parser.add_argument("--year-end", type=int, default=dt.date.today().year)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--jitter-seconds", type=float, default=0.5)
    parser.add_argument("--raw-policy", choices=("all", "none"), default="all")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-merge", action="store_true")
    parser.add_argument("--max-partitions", type=int)
    parser.add_argument("--min-free-gib", type=float, default=DEFAULT_MIN_FREE_GIB)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.year_start < 2003 or args.year_end < args.year_start:
        raise SystemExit("invalid year range")
    if args.max_partitions is not None and args.max_partitions < 1:
        raise SystemExit("--max-partitions must be at least 1")
    if args.min_free_gib <= 0:
        raise SystemExit("--min-free-gib must be greater than 0")
    if args.cookie_file and not args.cookie_file.exists():
        raise SystemExit("cookie file does not exist")

    vintage_root = args.output_root or (DATA_ROOT / f"jjwxc_partitioned_{args.vintage}")
    storage = storage_status(vintage_root, args.min_free_gib)
    if args.execute and not storage["ready"]:
        atomic_json(
            vintage_root / "run_manifest.json",
            {
                "generated_at": now_iso(),
                "vintage": args.vintage,
                "mode": "blocked-before-network",
                "terminal_status": "storage-blocked",
                "storage": storage,
                "execution_started": False,
            },
        )
        raise SystemExit(
            f"insufficient free space: {storage['free_gib']} GiB available; "
            f"minimum {storage['minimum_free_gib']} GiB"
        )
    years = list(range(args.year_start, args.year_end + 1))
    if args.max_partitions:
        years = years[: args.max_partitions]
    plan_rows = []

    baseline = run_child(
        child_command(
            url=args.base_url,
            vintage=f"{args.vintage}-unfiltered-preflight",
            output_root=vintage_root / "preflight" / "unfiltered",
            cookie_file=args.cookie_file,
            ca_file=args.ca_file,
            delay=0,
            jitter=0,
            raw_policy="none",
            max_pages=1,
        ),
        "preflight unfiltered catalog",
    )
    unfiltered_pages = int(baseline["expected_pages"])

    for year in years:
        output = vintage_root / "preflight" / f"year={year}"
        result = run_child(
            child_command(
                url=year_url(args.base_url, year),
                vintage=f"{args.vintage}-year-{year}-preflight",
                output_root=output,
                cookie_file=args.cookie_file,
                ca_file=args.ca_file,
                delay=0,
                jitter=0,
                raw_policy="none",
                max_pages=1,
            ),
            f"preflight year {year}",
        )
        plan_rows.append(
            {
                "year": year,
                "expected_pages": result["expected_pages"],
                "first_page_rows": result["rows"],
                "query_fingerprint": result["query_fingerprint"],
                "source_url_public": result["source_url_public"],
            }
        )
        atomic_json(
            vintage_root / "partition_plan.json",
            {
                "generated_at": now_iso(),
                "vintage": args.vintage,
                "year_start": args.year_start,
                "year_end": args.year_end,
                "partition_count": len(plan_rows),
                "planned_pages": sum(int(item["expected_pages"]) for item in plan_rows),
                "unfiltered_pages": unfiltered_pages,
                "page_count_gap_indicator": unfiltered_pages
                - sum(int(item["expected_pages"]) for item in plan_rows),
                "catalog_completeness": "unproven-year-partition-scope",
                "storage": storage,
                "partitions": plan_rows,
                "execution_started": False,
            },
        )

    if not args.execute:
        report = {
            "mode": "plan-only",
            "vintage": args.vintage,
            "partition_count": len(plan_rows),
            "planned_pages": sum(int(item["expected_pages"]) for item in plan_rows),
            "unfiltered_pages": unfiltered_pages,
            "page_count_gap_indicator": unfiltered_pages
            - sum(int(item["expected_pages"]) for item in plan_rows),
            "catalog_completeness": "unproven-until-residual-partitions-are-reconciled",
            "storage": storage,
            "partitions": plan_rows,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
        return 0

    completed = []
    for item in plan_rows:
        year = int(item["year"])
        output = vintage_root / "partitions" / f"year={year}"
        result = run_child(
            child_command(
                url=year_url(args.base_url, year),
                vintage=f"{args.vintage}-year-{year}",
                output_root=output,
                cookie_file=args.cookie_file,
                ca_file=args.ca_file,
                delay=args.delay_seconds,
                jitter=args.jitter_seconds,
                raw_policy=args.raw_policy,
                expected_pages=int(item["expected_pages"]),
            ),
            f"crawl year {year}",
        )
        if not result.get("collection_complete"):
            raise RuntimeError(f"year {year} returned without complete page reconciliation")
        completed.append(
            {
                "year": year,
                "pages": result["ok_pages"],
                "rows": result["rows"],
                "duplicates": result["duplicate_work_id_rows"],
            }
        )
        atomic_json(
            vintage_root / "run_manifest.json",
            {
                "generated_at": now_iso(),
                "vintage": args.vintage,
                "partition_count": len(plan_rows),
                "completed_partition_count": len(completed),
                "completed_pages": sum(int(row["pages"]) for row in completed),
                "completed_rows": sum(int(row["rows"]) for row in completed),
                "unfiltered_pages": unfiltered_pages,
                "year_partition_pages": sum(int(item["expected_pages"]) for item in plan_rows),
                "page_count_gap_indicator": unfiltered_pages
                - sum(int(item["expected_pages"]) for item in plan_rows),
                "storage": storage,
                "partitions": completed,
                "terminal_status": "running",
            },
        )

    merge_result = None
    if not args.skip_merge:
        merge = subprocess.run(
            [
                sys.executable,
                MERGER.as_posix(),
                "--partition-root",
                (vintage_root / "partitions").as_posix(),
                "--output-root",
                (vintage_root / "merged").as_posix(),
                "--rebuild",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if merge.returncode != 0:
            raise RuntimeError("partition merge failed")
        merge_result = json.loads(merge.stdout)

    report = {
        "mode": "executed",
        "vintage": args.vintage,
        "partition_count": len(plan_rows),
        "completed_partition_count": len(completed),
        "completed_pages": sum(int(row["pages"]) for row in completed),
        "completed_rows": sum(int(row["rows"]) for row in completed),
        "unfiltered_pages": unfiltered_pages,
        "year_partition_pages": sum(int(item["expected_pages"]) for item in plan_rows),
        "page_count_gap_indicator": unfiltered_pages
        - sum(int(item["expected_pages"]) for item in plan_rows),
        "catalog_completeness": "unproven-until-residual-partitions-are-reconciled",
        "storage": storage,
        "partitions": completed,
        "merge": merge_result,
        "terminal_status": "year-partitions-complete-residual-audit-required",
    }
    atomic_json(vintage_root / "run_manifest.json", {"generated_at": now_iso(), **report})
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
