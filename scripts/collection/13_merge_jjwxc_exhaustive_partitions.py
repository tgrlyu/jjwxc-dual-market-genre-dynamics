#!/usr/bin/env python3
"""Merge exhaustive JJWXC crawl partitions into a deduplicated master shard set.

The exhaustive crawl uses overlapping filter partitions so that every leaf
stays under the 10k-page wall. This merger consolidates all completed
partition databases into one deduplicated SQLite store while preserving the
source partition for auditability.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


MASTER_FILENAME = "records.sqlite"
SEEN_FILENAME = ".merge_seen.sqlite"


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def fallback_key(row: sqlite3.Row) -> str:
    payload = "\x1f".join(
        str(row[key] or "")
        for key in ("work_title", "author", "publish_time", "genre_full", "work_url")
    )
    return "fallback:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def setup_master(path: Path) -> sqlite3.Connection:
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
            source_partition TEXT NOT NULL,
            source_page INTEGER NOT NULL,
            source_row INTEGER NOT NULL,
            retrieved_at TEXT NOT NULL,
            page_sha256 TEXT NOT NULL
        );
        CREATE TABLE duplicates (
            duplicate_id INTEGER PRIMARY KEY AUTOINCREMENT,
            record_key TEXT NOT NULL,
            work_id TEXT,
            source_partition TEXT NOT NULL,
            source_page INTEGER NOT NULL,
            source_row INTEGER NOT NULL,
            prior_partition TEXT NOT NULL,
            reason TEXT NOT NULL
        );
        CREATE TABLE provenance (
            source_partition TEXT PRIMARY KEY,
            source_db TEXT NOT NULL,
            manifest TEXT NOT NULL,
            page_count INTEGER NOT NULL,
            source_row_count INTEGER NOT NULL,
            routed_row_count INTEGER NOT NULL,
            duplicate_row_count INTEGER NOT NULL,
            collection_complete INTEGER NOT NULL
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
            source_partition TEXT
        )
        """
    )
    return connection


def remove_sqlite_family(path: Path) -> None:
    for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
        candidate.unlink(missing_ok=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge JJWXC exhaustive crawl partitions.")
    parser.add_argument("--partition-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def partition_dbs(partition_root: Path) -> list[Path]:
    return sorted(partition_root.glob("partitions/*/crawl.sqlite"))


def main() -> int:
    args = parse_args()
    dbs = partition_dbs(args.partition_root)
    if not dbs:
        raise SystemExit("no partition databases found")
    if args.output_root.exists():
        if not args.rebuild:
            raise SystemExit("output root exists; use --rebuild")
        shutil.rmtree(args.output_root)
    args.output_root.mkdir(parents=True)

    master_path = args.output_root / MASTER_FILENAME
    seen_path = args.output_root / SEEN_FILENAME
    master = setup_master(master_path)
    seen = setup_seen(seen_path)

    partition_summaries: list[dict[str, object]] = []
    source_rows_total = 0
    routed_total = 0
    duplicate_total = 0
    cross_partition_duplicates = 0

    try:
        for source_db in dbs:
            partition_dir = source_db.parent
            partition_name = partition_dir.name
            manifest_path = partition_dir / "manifest.json"
            if not manifest_path.exists():
                raise RuntimeError(f"missing manifest for partition {partition_name}")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if not manifest.get("collection_complete") and not args.allow_partial:
                raise RuntimeError(f"partition {partition_name} is not collection-complete")

            source = sqlite3.connect(source_db)
            source.row_factory = sqlite3.Row
            source_rows = int(source.execute("SELECT COUNT(*) FROM works").fetchone()[0])
            source_pages = int(source.execute("SELECT COUNT(*) FROM pages WHERE status='ok'").fetchone()[0])
            routed_rows = 0
            duplicate_rows = 0

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
                    record_key = f"work:{row['work_id']}" if row["work_id"] else fallback_key(row)
                    prior = seen.execute(
                        "SELECT source_partition FROM seen WHERE record_key = ?",
                        (record_key,),
                    ).fetchone()
                    if prior is not None:
                        prior_partition = str(prior[0])
                        duplicate_rows += 1
                        if prior_partition != partition_name:
                            cross_partition_duplicates += 1
                        master.execute(
                            """
                            INSERT INTO duplicates(
                                record_key, work_id, source_partition, source_page,
                                source_row, prior_partition, reason
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                record_key,
                                row["work_id"],
                                partition_name,
                                row["page_number"],
                                row["row_position"],
                                prior_partition,
                                "duplicate-record-key-across-partitions",
                            ),
                        )
                        continue

                    seen.execute(
                        "INSERT INTO seen(record_key, work_id, source_partition) VALUES (?, ?, ?)",
                        (record_key, row["work_id"], partition_name),
                    )
                    master.execute(
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
                            partition_name,
                            row["page_number"],
                            row["row_position"],
                            row["retrieved_at"],
                            row["page_sha256"],
                        ),
                    )
                    routed_rows += 1

                master.execute(
                    """
                    INSERT INTO provenance VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        partition_name,
                        source_db.as_posix(),
                        manifest_path.as_posix(),
                        source_pages,
                        source_rows,
                        routed_rows,
                        duplicate_rows,
                        1 if manifest.get("collection_complete") else 0,
                    ),
                )
                master.commit()
                seen.commit()
            finally:
                source.close()

            partition_summaries.append(
                {
                    "partition": partition_name,
                    "pages": source_pages,
                    "source_rows": source_rows,
                    "routed_rows": routed_rows,
                    "duplicate_rows": duplicate_rows,
                    "collection_complete": bool(manifest.get("collection_complete")),
                }
            )
            source_rows_total += source_rows
            routed_total += routed_rows
            duplicate_total += duplicate_rows
    finally:
        seen.close()
        remove_sqlite_family(seen_path)
        master.close()

    report = {
        "generated_at": now_iso(),
        "partition_count": len(partition_summaries),
        "source_rows": source_rows_total,
        "routed_rows": routed_total,
        "duplicate_rows": duplicate_total,
        "cross_partition_duplicates": cross_partition_duplicates,
        "row_reconciliation": source_rows_total == routed_total + duplicate_total,
        "partitions": partition_summaries,
        "output_master": master_path.as_posix(),
        "catalog_completeness": "unproven-partition-scope",
    }
    (args.output_root / "merge_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else report)
    if not report["row_reconciliation"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
