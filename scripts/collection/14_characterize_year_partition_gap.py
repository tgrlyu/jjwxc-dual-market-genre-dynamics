#!/usr/bin/env python3
"""Characterize the year-partition completeness gap (unauthenticated, page-1 headers only).

Reads only live 末页(declared_last_page) totals — all within the 10-page unauthenticated
wall — and decomposes the ~6,158-page "yearless" gap by the 原创性 axis so we can see how
many of the works that appear in the unfiltered catalog but in NO fbsjYYYY year filter are
原创 / 衍生 / originality-less. No deep-offset access, no login required.
"""
import importlib.util, sys, time, subprocess, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("jjc", HERE / "07_crawl_jjwxc_public_metadata.py")
m = importlib.util.module_from_spec(spec); sys.modules["jjc"] = m; spec.loader.exec_module(m)

UA = "Mozilla/5.0 (research metadata; tgrlyu@korea.ac.kr)"
BASE = "https://www.jjwxc.net/bookbase.php"
OUT = HERE.parent / "outputs" / "v2_gap_originality_decomposition.json"


def total_pages(url: str):
    for _ in range(4):
        raw = subprocess.run(["curl", "-sS", "-A", UA, "--max-time", "30", url],
                             capture_output=True).stdout
        try:
            return m.parse_catalog_page(url=url, raw=raw).declared_last_page or 0
        except Exception:
            time.sleep(3)
    return None


def year_sum(prefix: str):
    s = 0
    for y in range(2003, 2027):
        p = total_pages(f"{BASE}?{prefix}fbsj{y}={y}")
        s += p or 0
        time.sleep(1.1)
    return s


def main():
    res = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "unit": "pages(declared_last)"}
    res["unfiltered"] = total_pages(f"{BASE}?yc=0"); time.sleep(1.2)
    for yc, name in [(1, "original"), (2, "derivative")]:
        axis = total_pages(f"{BASE}?yc={yc}"); time.sleep(1.2)
        ys = year_sum(f"yc={yc}&")
        res[name] = {"axis_total_pages": axis, "year_sum_pages": ys,
                     "yearless_pages": (axis or 0) - ys}
        OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2))  # checkpoint
    u = res["unfiltered"]; o = res["original"]; d = res["derivative"]
    res["originality_less_pages"] = u - o["axis_total_pages"] - d["axis_total_pages"]
    res["yearless_gap_total_pages"] = u - o["year_sum_pages"] - d["year_sum_pages"]
    res["approx_works_per_page"] = 98.5
    OUT.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
