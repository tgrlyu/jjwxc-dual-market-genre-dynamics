#!/usr/bin/env python3
"""Preflight categorical partition axes against the unfiltered catalog size."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRAWLER = Path(__file__).with_name("07_crawl_jjwxc_public_metadata.py")
DATA_ROOT = PROJECT_ROOT / "data"
AXES = {
    "genre": {
        "parameter": "lx",
        "values": {
            1: "爱情", 2: "武侠", 3: "奇幻", 4: "仙侠", 5: "游戏",
            6: "传奇", 7: "科幻", 8: "童话", 9: "惊悚", 10: "悬疑",
            16: "剧情", 17: "轻小说", 20: "古典衍生", 18: "东方衍生",
            19: "西方衍生", 21: "其他衍生", 22: "儿歌", 23: "散文",
            24: "寓言", 25: "童谣", 27: "儿童小说",
        },
    },
    "orientation": {
        "parameter": "xx",
        "values": {1: "言情", 2: "纯爱", 3: "百合", 5: "无CP", 6: "多元"},
    },
    "viewpoint": {
        "parameter": "mainview",
        "values": {
            1: "男主", 2: "女主", 3: "主攻", 4: "主受", 5: "互攻",
            8: "不明", 9: "其他", 12: "双视角", 13: "多视角",
        },
    },
    "era": {
        "parameter": "sd",
        "values": {1: "近代现代", 2: "古色古香", 4: "架空历史", 5: "幻想未来"},
    },
    "completion": {
        "parameter": "isfinish",
        "values": {1: "连载", 2: "完结"},
    },
    "originality": {
        "parameter": "yc",
        "values": {1: "原创", 2: "衍生"},
    },
}


def filtered_url(base_url: str, parameter: str, value: int) -> str:
    parsed = urllib.parse.urlsplit(base_url)
    segments = []
    for segment in parsed.query.split("&"):
        raw_key = segment.split("=", 1)[0]
        key = urllib.parse.unquote_plus(raw_key, encoding="ascii", errors="replace")
        if key != parameter:
            segments.append(segment)
    segments.append(f"{parameter}={value}")
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "&".join(segments), "")
    )


def preflight(url: str, output_root: Path, vintage: str) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            CRAWLER.as_posix(),
            "--base-url", url,
            "--vintage", vintage,
            "--output-root", output_root.as_posix(),
            "--max-pages", "1",
            "--delay-seconds", "0",
            "--jitter-seconds", "0",
            "--raw-policy", "none",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        tail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "no detail"
        raise RuntimeError(f"preflight failed: {tail[:500]}")
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit JJWXC filter-axis coverage.")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--axis", choices=tuple(AXES), default="genre")
    parser.add_argument("--vintage", default=dt.date.today().isoformat())
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.output_root or (DATA_ROOT / f"jjwxc_filter_coverage_{args.vintage}")
    baseline = preflight(args.base_url, root / "unfiltered", f"{args.vintage}-unfiltered")
    axis = AXES[args.axis]
    partitions = []
    for value, label in axis["values"].items():
        result = preflight(
            filtered_url(args.base_url, str(axis["parameter"]), int(value)),
            root / args.axis / f"value={value}",
            f"{args.vintage}-{args.axis}-{value}",
        )
        partitions.append(
            {
                "value": value,
                "label": label,
                "pages": int(result["expected_pages"]),
                "first_page_rows": int(result["rows"]),
                "source_url_public": result["source_url_public"],
                "query_fingerprint": result["query_fingerprint"],
            }
        )

    unfiltered_pages = int(baseline["expected_pages"])
    partition_pages = sum(item["pages"] for item in partitions)
    page_delta = partition_pages - unfiltered_pages
    plausible_page_bound = 0 <= page_delta <= len(partitions) - 1
    report = {
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "axis": args.axis,
        "parameter": axis["parameter"],
        "unfiltered_pages": unfiltered_pages,
        "partition_pages": partition_pages,
        "partition_count": len(partitions),
        "page_delta": page_delta,
        "plausibly_exhaustive_by_page_bound": plausible_page_bound,
        "warning": "page-bound plausibility is not row-level proof; final pages and work IDs must reconcile",
        "largest_partitions": sorted(partitions, key=lambda item: item["pages"], reverse=True)[:5],
        "partitions": partitions,
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{args.axis}_coverage_plan.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
