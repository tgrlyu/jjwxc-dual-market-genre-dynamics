#!/usr/bin/env python3
"""Isolate and profile the year-partition completeness gap.

After the exhaustive (non-year) crawl is merged, this compares its distinct work_ids
against the year-partition crawl's work_ids. Works present in the exhaustive catalog but
absent from every fbsjYYYY year partition are the ~6,158-page (~616k-work) "yearless" gap
that motivated the follow-up study. Profiles the gap by 原创性 / 性向 / 类型 / publish_time
so we can say what these works actually are.

Run after: scripts/13_merge_jjwxc_exhaustive_partitions.py
Inputs (defaults; override with flags):
  --year-root  data/jjwxc_partitioned_2026-07-11-cookie        (year crawl, merged shards)
  --exhaustive-root data/jjwxc_exhaustive_2026-07-18           (this run)
Outputs:
  outputs/v2_gap_workid_isolation_summary.json
  outputs/v2_gap_profile_by_originality.csv
  outputs/v2_gap_profile_by_orientation.csv
  outputs/v2_gap_profile_by_genre.csv
  outputs/v2_gap_publish_time_diagnostic.csv
"""
import argparse, json, sqlite3, glob, csv, collections, re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROJ = HERE.parent
OUT = PROJ / "outputs"


def load_ids(root: Path) -> dict:
    """Return {work_id: {'genre_full':..., 'publish_time':...}} across all sqlite under root."""
    recs = {}
    for db in glob.glob(str(root / "**" / "*.sqlite"), recursive=True):
        try:
            c = sqlite3.connect(db)
            tbls = [r[0] for r in c.execute("select name from sqlite_master where type='table'")]
            for t in tbls:
                cols = [r[1] for r in c.execute(f"pragma table_info({t})")]
                if "work_id" not in cols:
                    continue
                gsel = "genre_full" if "genre_full" in cols else ("genre" if "genre" in cols else "NULL")
                psel = "publish_time" if "publish_time" in cols else ("publish_date" if "publish_date" in cols else "NULL")
                for wid, g, p in c.execute(f"select work_id,{gsel},{psel} from {t}"):
                    if wid in (None, "", "0"):
                        continue
                    recs.setdefault(str(wid), {"genre_full": g or "", "publish_time": p or ""})
            c.close()
        except Exception as e:
            print("skip", db, e)
    return recs


def originality_of(genre_full: str) -> str:
    if genre_full.startswith("原创"):
        return "原创"
    if genre_full.startswith("衍生"):
        return "衍生"
    return "unclassified"


def token(genre_full: str, idx: int) -> str:
    parts = genre_full.split("-")
    return parts[idx] if len(parts) > idx else ""


def has_year(publish_time: str) -> bool:
    return bool(re.search(r"(19|20)\d{2}", publish_time or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year-root", type=Path, default=PROJ / "data" / "jjwxc_partitioned_2026-07-11-cookie")
    ap.add_argument("--exhaustive-root", type=Path, default=PROJ / "data" / "jjwxc_exhaustive_2026-07-18")
    args = ap.parse_args()

    year = load_ids(args.year_root)
    exh = load_ids(args.exhaustive_root)
    year_ids = set(year)
    exh_ids = set(exh)
    gap_ids = exh_ids - year_ids           # in exhaustive catalog, missing from every year filter
    common = exh_ids & year_ids
    exh_only_reverse = year_ids - exh_ids  # sanity: in year crawl but not exhaustive (should be small)

    summary = {
        "year_distinct": len(year_ids),
        "exhaustive_distinct": len(exh_ids),
        "intersection": len(common),
        "gap_exhaustive_minus_year": len(gap_ids),
        "reverse_year_minus_exhaustive": len(exh_only_reverse),
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "v2_gap_workid_isolation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    by_o = collections.Counter(); by_or = collections.Counter(); by_g = collections.Counter()
    yearless_in_gap = 0
    for wid in gap_ids:
        gf = exh[wid]["genre_full"]
        by_o[originality_of(gf)] += 1
        by_or[token(gf, 1)] += 1
        by_g[token(gf, 3)] += 1
        if not has_year(exh[wid]["publish_time"]):
            yearless_in_gap += 1
    summary["gap_with_unparseable_publish_time"] = yearless_in_gap
    (OUT / "v2_gap_workid_isolation_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))

    for name, ctr in [("originality", by_o), ("orientation", by_or), ("genre", by_g)]:
        with open(OUT / f"v2_gap_profile_by_{name}.csv", "w", newline="") as f:
            w = csv.writer(f); w.writerow([name, "gap_work_count"])
            for k, v in ctr.most_common():
                w.writerow([k or "(blank)", v])

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
