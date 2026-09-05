#!/usr/bin/env python3
"""Adaptive shallow partition planner (respects the platform's ~100-page depth limit).

2026-07-20: jjwxc globally restricted deep pagination (page>~100 -> HTTP 404). Instead of
requesting deep offsets, we split the catalog into filter combinations small enough that each
one fits inside the pages the site serves normally. Non-year axes are used on purpose: works
with no parseable 发表时间 (the "gap") never appear under fbsjYYYY, so a year-based scheme
cannot reach them.

Recursion: start coarse, measure declared_last_page for a combo; if it exceeds MAX_PAGES,
split on the next axis and recurse. Leaves are combos that fit (or are marked oversize when
axes run out).

Only one request per combo is made, at 1 page each, with a polite delay.
"""
import argparse, json, subprocess, sys, time, importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("jjc", HERE / "07_crawl_jjwxc_public_metadata.py")
m = importlib.util.module_from_spec(spec); sys.modules["jjc"] = m; spec.loader.exec_module(m)

BASE = "https://www.jjwxc.net/bookbase.php"
UA = "Mozilla/5.0 (research metadata; tgrlyu@korea.ac.kr)"
MAX_PAGES = 100

# axis name -> list of (param_fragment, label); applied in this order when splitting
AXES = [
    ("isfinish", [("isfinish=2", "완결"), ("isfinish=1", "연재")]),
    ("originality", [("yc1=1", "原创"), ("yc2=2", "衍生")]),
    ("orientation", [("xx1=1", "言情"), ("xx2=2", "纯爱"), ("xx3=3", "百合"),
                     ("xx4=4", "无CP"), ("xx6=6", "多元")]),
    ("era", [("sd1=1", "近代现代"), ("sd2=2", "古色古香"), ("sd4=4", "架空历史"),
             ("sd5=5", "幻想未来")]),
    ("genre", [(f"lx{i}={i}", f"lx{i}") for i in
               [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21]]),
    ("mainview", [(f"mainview{i}={i}", f"mv{i}") for i in [1, 2, 3, 4, 5, 8, 9, 12, 13]]),
    ("favcount", [(f"novelbefavoritedcount{i}={i}", f"fav{i}") for i in [1, 2, 3, 4, 5, 6]]),
]


def declared_last(query: str, retries: int = 3):
    url = f"{BASE}?{query}" if query else BASE
    for _ in range(retries):
        raw = subprocess.run(["curl", "-sS", "-A", UA, "--max-time", "30", url],
                             capture_output=True).stdout
        try:
            return m.parse_catalog_page(raw, url).declared_last_page or 0
        except Exception:
            time.sleep(2)
    return None


ALL_LEAVES = []  # global accumulator so incremental writes reflect true progress


def record(out, stats, leaf):
    ALL_LEAVES.append(leaf)
    if len(ALL_LEAVES) % 10 == 0:
        fits = [l for l in ALL_LEAVES if l["status"] == "fits"]
        stats["leaves"] = len(ALL_LEAVES)
        stats["fit"] = len(fits)
        stats["fit_pages"] = sum(l["pages"] for l in fits)
        stats["oversize"] = sum(1 for l in ALL_LEAVES if l["status"].startswith("oversize"))
        stats["oversize_pages"] = sum(l["pages"] or 0 for l in ALL_LEAVES
                                      if l["status"].startswith("oversize"))
        out.write_text(json.dumps({"stats": stats, "leaves": ALL_LEAVES},
                                  ensure_ascii=False, indent=2))
    return leaf


def plan(prefix_parts, depth, delay, out, stats):
    """Walk the axis tree, recording leaves into ALL_LEAVES."""
    query = "&".join(prefix_parts)
    pages = declared_last(query)
    stats["requests"] += 1
    time.sleep(delay)
    if pages is None:
        return [record(out, stats, {"query": query, "pages": None,
                                    "status": "probe-failed", "depth": depth})]
    if pages == 0:
        return [record(out, stats, {"query": query, "pages": 0,
                                    "status": "fits", "depth": depth})]
    if pages <= MAX_PAGES:
        return [record(out, stats, {"query": query, "pages": pages,
                                    "status": "fits", "depth": depth})]
    if depth >= len(AXES):
        return [record(out, stats, {"query": query, "pages": pages,
                                    "status": "oversize-axes-exhausted", "depth": depth})]
    leaves = []
    _, values = AXES[depth]
    for frag, _label in values:
        leaves.extend(plan(prefix_parts + [frag], depth + 1, delay, out, stats))
    return leaves


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--root", default="", help="fixed prefix, e.g. 'isfinish=1'")
    ap.add_argument("--start-depth", type=int, default=0,
                    help="axis index to begin splitting at (skip axes already in --root)")
    ap.add_argument("--output", type=Path,
                    default=HERE.parent / "outputs" / "v2_shallow_partition_plan.json")
    args = ap.parse_args()
    stats = {"requests": 0, "started": time.strftime("%Y-%m-%dT%H:%M:%S")}
    root = [args.root] if args.root else []
    leaves = plan(root, args.start_depth, args.delay, args.output, stats)
    fits = [l for l in leaves if l["status"] == "fits"]
    over = [l for l in leaves if l["status"].startswith("oversize")]
    total_pages = sum(l["pages"] for l in fits)
    summary = {
        "leaves_total": len(leaves), "leaves_fit": len(fits), "leaves_oversize": len(over),
        "planned_pages": total_pages, "probe_requests": stats["requests"],
        "max_pages_per_leaf": MAX_PAGES,
    }
    args.output.write_text(json.dumps({"summary": summary, "leaves": leaves},
                                      ensure_ascii=False, indent=2))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
