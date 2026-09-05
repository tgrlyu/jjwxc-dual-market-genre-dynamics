#!/usr/bin/env python3
"""Run the JJWXC crawl through the verified filter-based partition tree.

This orchestrator uses a browser-verified partition plan that keeps every
leaf below the 10k page wall observed on the unfiltered catalog. The crawler
itself remains the same checkpointed metadata collector; this wrapper only
chooses a sequence of base URLs, launches the child crawl, and records the
per-partition manifests.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRAWLER = Path(__file__).with_name("07_crawl_jjwxc_public_metadata.py")
DATA_ROOT = PROJECT_ROOT / "data"
GIB = 1024**3
DEFAULT_MIN_FREE_GIB = 5.0
BASE_URL = "https://www.jjwxc.net/bookbase.php?s_typeid=1&version=1&fw=0&yc=0&xx=0&mainview=0&sd=0&lx=0&bq=-1&submit=%C9%B8%D1%A1"


PARTITIONS: list[tuple[str, str]] = [
    ("finished", "isfinish=2"),
    ("ongoing-derivative", "isfinish=1&yc2=2"),
    ("ongoing-original-mv1", "isfinish=1&yc1=1&mainview1=1"),
    ("ongoing-original-mv2-sd1", "isfinish=1&yc1=1&mainview2=2&sd1=1"),
    ("ongoing-original-mv2-sd2", "isfinish=1&yc1=1&mainview2=2&sd2=2"),
    ("ongoing-original-mv2-sd4", "isfinish=1&yc1=1&mainview2=2&sd4=4"),
    ("ongoing-original-mv2-sd5", "isfinish=1&yc1=1&mainview2=2&sd5=5"),
    ("ongoing-original-mv3", "isfinish=1&yc1=1&mainview3=3"),
    ("ongoing-original-mv4", "isfinish=1&yc1=1&mainview4=4"),
    ("ongoing-original-mv5", "isfinish=1&yc1=1&mainview5=5"),
    ("ongoing-original-mv8", "isfinish=1&yc1=1&mainview8=8"),
    ("ongoing-original-mv9", "isfinish=1&yc1=1&mainview9=9"),
    ("ongoing-original-mv12", "isfinish=1&yc1=1&mainview12=12"),
    ("ongoing-original-mv13", "isfinish=1&yc1=1&mainview13=13"),
]


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


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


def build_url(base_url: str, suffix: str) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    query = parsed.query
    if suffix:
        query = f"{query}&{suffix}" if query else suffix
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


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
        "--page-failure-policy",
        "continue",
        "--json",
    ]
    if cookie_file:
        command.extend(("--cookie-file", cookie_file.as_posix()))
    if ca_file:
        command.extend(("--ca-file", ca_file.as_posix()))
    return command


def run_child(command: list[str], label: str) -> dict[str, object]:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode not in (0, 2):
        tail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no detail"
        raise RuntimeError(f"{label} failed with exit {result.returncode}: {tail[:500]}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label} returned invalid JSON") from exc
    payload["exit_code"] = result.returncode
    return payload


def partition_is_complete(payload: dict[str, object]) -> bool:
    return (
        payload.get("exit_code") == 0
        and payload.get("collection_complete") is True
        and payload.get("requested_range_complete") is True
    )


def completed_count(partitions: list[dict[str, object]]) -> int:
    return sum(partition_is_complete(partition) for partition in partitions)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the exhaustive JJWXC filter crawl.")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--vintage", default=dt.date.today().isoformat())
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--jitter-seconds", type=float, default=0.5)
    parser.add_argument("--raw-policy", choices=("all", "none"), default="all")
    parser.add_argument("--min-free-gib", type=float, default=DEFAULT_MIN_FREE_GIB)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--start-at", type=int, default=1)
    parser.add_argument("--stop-after", type=int)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.start_at < 1:
        raise SystemExit("--start-at must be at least 1")
    if args.stop_after is not None and args.stop_after < args.start_at:
        raise SystemExit("--stop-after must be greater than or equal to --start-at")
    if args.min_free_gib <= 0:
        raise SystemExit("--min-free-gib must be greater than 0")
    if args.cookie_file and not args.cookie_file.exists():
        raise SystemExit("cookie file does not exist")

    vintage_root = args.output_root or (DATA_ROOT / f"jjwxc_exhaustive_{args.vintage}")
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

    partitions = PARTITIONS[args.start_at - 1 : args.stop_after]
    plan = []
    if not partitions:
        raise SystemExit("no partitions selected")

    progress_path = vintage_root / "run_manifest.json"
    atomic_json(
        progress_path,
        {
            "generated_at": now_iso(),
            "vintage": args.vintage,
            "mode": "planned" if not args.execute else "executing",
            "storage": storage,
            "execution_started": bool(args.execute),
            "partitions_total": len(PARTITIONS),
            "partitions_completed": 0,
            "partitions": [],
            "active_partition": None,
        },
    )

    if args.execute:
        for index, (name, suffix) in enumerate(partitions, start=args.start_at):
            partition_root = vintage_root / "partitions" / f"{index:02d}-{name}"
            url = build_url(args.base_url, suffix)
            atomic_json(
                progress_path,
                {
                    "generated_at": now_iso(),
                    "vintage": args.vintage,
                    "mode": "executing",
                    "storage": storage,
                    "execution_started": True,
                    "partitions_total": len(PARTITIONS),
                    "partitions_attempted": len(plan),
                    "partitions_completed": completed_count(plan),
                    "partitions": plan,
                    "active_partition": {
                        "index": index,
                        "name": name,
                        "suffix": suffix,
                        "output_root": partition_root.as_posix(),
                        "source_url_public": url,
                    },
                },
            )
            payload = run_child(
                child_command(
                    url=url,
                    vintage=f"{args.vintage}-{name}",
                    output_root=partition_root,
                    cookie_file=args.cookie_file,
                    ca_file=args.ca_file,
                    delay=args.delay_seconds,
                    jitter=args.jitter_seconds,
                    raw_policy=args.raw_policy,
                ),
                f"crawl partition {name}",
            )
            plan.append(
                {
                    "index": index,
                    "name": name,
                    "suffix": suffix,
                    "source_url_public": payload.get("source_url_public", url),
                    "query_fingerprint": payload.get("query_fingerprint"),
                    "expected_pages": payload.get("expected_pages"),
                    "rows": payload.get("rows"),
                    "collection_complete": payload.get("collection_complete"),
                    "requested_range_complete": payload.get("requested_range_complete"),
                    "exit_code": payload["exit_code"],
                }
            )
            atomic_json(
                vintage_root / "run_manifest.json",
                {
                    "generated_at": now_iso(),
                    "vintage": args.vintage,
                    "mode": "executing",
                    "storage": storage,
                    "execution_started": True,
                    "partitions_total": len(PARTITIONS),
                    "partitions_attempted": len(plan),
                    "partitions_completed": completed_count(plan),
                    "partitions": plan,
                },
            )

    selected_complete = bool(args.execute) and len(plan) == len(partitions) and all(
        partition_is_complete(partition) for partition in plan
    )
    report = {
        "generated_at": now_iso(),
        "vintage": args.vintage,
        "mode": "plan" if not args.execute else "executed",
        "terminal_status": "planned" if not args.execute else ("complete" if selected_complete else "partial"),
        "storage": storage,
        "execution_started": bool(args.execute),
        "partitions_total": len(PARTITIONS),
        "partitions_selected": [
            {"index": idx, "name": name, "suffix": suffix}
            for idx, (name, suffix) in enumerate(partitions, start=args.start_at)
        ],
        "partitions_attempted": len(plan),
        "partitions_completed": completed_count(plan),
        "partitions": plan,
    }
    atomic_json(progress_path, report)
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
    return 0 if not args.execute or selected_complete else 2


if __name__ == "__main__":
    raise SystemExit(main())
