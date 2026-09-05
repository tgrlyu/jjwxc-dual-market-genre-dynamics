#!/usr/bin/env python3
"""Route completed JJWXC year partitions into route/year SQLite shards."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


ROUTES = ("original", "derivative", "unclassified")
SHARD_FILENAME = "records.sqlite"
SEEN_FILENAME = ".merge_seen.sqlite"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def route_for(genre_full: str) -> str:
    if genre_full.startswith("原创-"):
        return "original"
    if genre_full.startswith("衍生-"):
        return "derivative"
    return "unclassified"


def fallback_key(row: sqlite3.Row) -> str:
    payload = "\x1f".join(
        str(row[key] or "")
        for key in ("work_title", "author", "publish_time", "genre_full", "work_url")
    )
    return "fallback:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def shard_path(output_root: Path, route: str, year: int) -> Path:
    return output_root / f"route={route}" / f"year={year}" / SHARD_FILENAME


def setup_shard(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE records (
            record_key TEXT PRIMARY KEY,
            work_id TEXT,
            work_title TEXT,
            author_id TEXT,
            author TEXT,
            genre_full TEXT,
            progress TEXT,
            word_count TEXT,
            score TEXT,
            publish_time TEXT,
            work_url TEXT,
            author_url TEXT,
            partition_year INTEGER NOT NULL,
            source_page INTEGER NOT NULL,
            source_row INTEGER NOT NULL,
            retrieved_at TEXT NOT NULL,
            page_sha256 TEXT NOT NULL
        );
        CREATE TABLE duplicates (
            duplicate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_key TEXT NOT NULL,
            work_id TEXT,
            partition_year INTEGER NOT NULL,
            source_page INTEGER NOT NULL,
            source_row INTEGER NOT NULL,
            prior_route TEXT NOT NULL,
            prior_partition_year INTEGER NOT NULL,
            reason TEXT NOT NULL
        );
        CREATE TABLE provenance (
            partition_year INTEGER PRIMARY KEY,
            source_db TEXT NOT NULL,
            source_manifest TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            source_row_count INTEGER NOT NULL,
            routed_row_count INTEGER NOT NULL,
            duplicate_row_count INTEGER NOT NULL
        );
        """
    )
    return connection


def setup_seen(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.execute(
        """
        CREATE TABLE seen (
            record_key TEXT PRIMARY KEY,
            work_id TEXT,
            route TEXT NOT NULL,
            partition_year INTEGER NOT NULL
        )
        """
    )
    return connection


def remove_sqlite_family(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        candidate.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Shard JJWXC year partitions by originality.")
    parser.add_argument("--partition-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    partition_dbs = sorted(args.partition_root.glob("year=*/crawl.sqlite"))
    if not partition_dbs:
        raise SystemExit("no partition databases found")
    if args.output_root.exists():
        if not args.rebuild:
            raise SystemExit("output root exists; use --rebuild")
        shutil.rmtree(args.output_root)
    args.output_root.mkdir(parents=True)

    seen_path = args.output_root / SEEN_FILENAME
    seen = setup_seen(seen_path)
    route_counts = {route: 0 for route in ROUTES}
    duplicate_counts = {route: 0 for route in ROUTES}
    cross_route_conflicts = 0
    partition_summaries: list[dict[str, object]] = []
    shard_summaries: list[dict[str, object]] = []

    try:
        for source_db in partition_dbs:
            year_match = source_db.parent.name.split("=", 1)
            if len(year_match) != 2 or not year_match[1].isdigit():
                raise RuntimeError(f"invalid partition directory: {source_db.parent.name}")
            year = int(year_match[1])
            manifest_path = source_db.parent / "manifest.json"
            if not manifest_path.exists():
                raise RuntimeError(f"missing manifest for year {year}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not manifest.get("collection_complete") and not args.allow_partial:
                raise RuntimeError(f"year {year} is not collection-complete")

            outputs = {
                route: setup_shard(shard_path(args.output_root, route, year))
                for route in ROUTES
            }
            source = sqlite3.connect(source_db)
            source.row_factory = sqlite3.Row
            source_rows = int(source.execute("SELECT COUNT(*) FROM works").fetchone()[0])
            source_pages = int(
                source.execute("SELECT COUNT(*) FROM pages WHERE status='ok'").fetchone()[0]
            )
            routed = {route: 0 for route in ROUTES}
            duplicates = {route: 0 for route in ROUTES}

            try:
                for row in source.execute(
                    """
                    SELECT page_number, row_position, author, author_id, author_url,
                           work_title, work_id, work_url, genre_full, progress,
                           word_count, score, publish_time, retrieved_at, page_sha256
                      FROM works
                     ORDER BY page_number, row_position
                    """
                ):
                    route = route_for(row["genre_full"] or "")
                    output = outputs[route]
                    record_key = f"work:{row['work_id']}" if row["work_id"] else fallback_key(row)
                    prior = seen.execute(
                        "SELECT route, partition_year FROM seen WHERE record_key=?",
                        (record_key,),
                    ).fetchone()
                    if prior is not None:
                        prior_route, prior_year = str(prior[0]), int(prior[1])
                        reason = (
                            "cross-route-record-key-conflict"
                            if prior_route != route
                            else "duplicate-record-key-across-year-partitions"
                        )
                        if prior_route != route:
                            cross_route_conflicts += 1
                        duplicate_counts[route] += 1
                        duplicates[route] += 1
                        output.execute(
                            """
                            INSERT INTO duplicates(
                                record_key, work_id, partition_year, source_page,
                                source_row, prior_route, prior_partition_year, reason
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record_key,
                                row["work_id"],
                                year,
                                row["page_number"],
                                row["row_position"],
                                prior_route,
                                prior_year,
                                reason,
                            ),
                        )
                        continue

                    seen.execute(
                        "INSERT INTO seen(record_key, work_id, route, partition_year) VALUES (?, ?, ?, ?)",
                        (record_key, row["work_id"], route, year),
                    )
                    output.execute(
                        """
                        INSERT INTO records VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            record_key,
                            row["work_id"],
                            row["work_title"],
                            row["author_id"],
                            row["author"],
                            row["genre_full"],
                            row["progress"],
                            row["word_count"],
                            row["score"],
                            row["publish_time"],
                            row["work_url"],
                            row["author_url"],
                            year,
                            row["page_number"],
                            row["row_position"],
                            row["retrieved_at"],
                            row["page_sha256"],
                        ),
                    )
                    route_counts[route] += 1
                    routed[route] += 1

                for route, output in outputs.items():
                    output.execute(
                        "INSERT INTO provenance VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            year,
                            source_db.as_posix(),
                            manifest_path.as_posix(),
                            source_pages,
                            source_rows,
                            routed[route],
                            duplicates[route],
                        ),
                    )
                    output.execute("CREATE INDEX idx_records_work_id ON records(work_id)")
                    output.execute("CREATE INDEX idx_records_author_id ON records(author_id)")
                    output.execute("CREATE INDEX idx_records_publish_time ON records(publish_time)")
                    output.commit()
                    shard_summaries.append(
                        {
                            "route": route,
                            "year": year,
                            "path": shard_path(args.output_root, route, year).as_posix(),
                            "rows": routed[route],
                            "duplicates": duplicates[route],
                        }
                    )
                seen.commit()
            finally:
                source.close()
                for output in outputs.values():
                    output.close()

            partition_summaries.append(
                {
                    "year": year,
                    "pages": source_pages,
                    "source_rows": source_rows,
                    "routed": routed,
                    "duplicates": duplicates,
                }
            )
    finally:
        seen.close()
        remove_sqlite_family(seen_path)

    source_rows_total = sum(int(item["source_rows"]) for item in partition_summaries)
    routed_total = sum(route_counts.values())
    duplicate_total = sum(duplicate_counts.values())
    row_reconciliation = source_rows_total == routed_total + duplicate_total
    report = {
        "generated_at": now_iso(),
        "layout": "route/year=YYYY/records.sqlite",
        "partition_count": len(partition_summaries),
        "shard_count": len(shard_summaries),
        "source_rows": source_rows_total,
        "route_counts": route_counts,
        "duplicate_counts": duplicate_counts,
        "routed_rows": routed_total,
        "duplicate_rows": duplicate_total,
        "row_reconciliation": row_reconciliation,
        "cross_route_work_id_conflicts": cross_route_conflicts,
        "partitions": partition_summaries,
        "shards": shard_summaries,
        "outputs": {
            route: [item["path"] for item in shard_summaries if item["route"] == route]
            for route in ROUTES
        },
        "partition_merge_complete": (
            not args.allow_partial and row_reconciliation and cross_route_conflicts == 0
        ),
        "catalog_completeness": "unproven-partition-scope",
    }
    (args.output_root / "merge_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
    if not row_reconciliation:
        return 3
    return 0 if cross_route_conflicts == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
