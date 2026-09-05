#!/usr/bin/env python3
"""Checkpointed crawler for JJWXC public catalog metadata.

The crawler collects only the seven fields shown in the public work-catalog
table. It never requests novel text, account pages, comments, or private data.
Raw HTML, SQLite state, and manifests are written below the project's ignored
``data/`` directory. Authentication cookies, when institutionally authorized,
must be supplied as an external Netscape cookie file and are never copied or
logged.

This is a crawl-window vintage, not a transactional snapshot: the live catalog
can change while 45k+ pages are being collected. Work-ID duplicates and page
reconciliation therefore remain first-class audit outputs.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import http.client
import gzip
import hashlib
import http.cookiejar
import json
import os
import random
import re
import ssl
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from lxml import html


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = PROJECT_ROOT / "data"
EXPECTED_HEADERS = ["作者", "作品", "类型", "进度", "字数", "作品积分", "发表时间"]
DYNAMIC_QUERY_KEYS = {"sign", "time", "jsver", "m_p", "page"}
AUTH_WALL_MARKERS = ("登入后再访问此页面", "登录后再访问此页面")
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; LyuAcademicMetadataAudit/1.0)"
# Allow live-catalog underfill on non-final pages; only empty pages are invalid.
MIN_NONFINAL_ROWS = 1
RETRYABLE_FETCH_EXCEPTIONS = (urllib.error.URLError, TimeoutError, http.client.IncompleteRead)


class CrawlError(RuntimeError):
    """Base class for explicit crawler failures."""


class AuthenticationRequired(CrawlError):
    """The site returned an authentication wall instead of catalog rows."""


class LayoutChanged(CrawlError):
    """The expected public metadata table was not present."""


class PageCountMismatch(CrawlError):
    """A non-final catalog page did not contain exactly 100 rows."""


RETRYABLE_CRAWL_EXCEPTIONS = RETRYABLE_FETCH_EXCEPTIONS + (LayoutChanged, PageCountMismatch)


@dataclass(frozen=True)
class ParsedPage:
    rows: list[dict[str, object]]
    declared_last_page: int | None
    last_page_url: str | None


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def normalized_integer(value: str) -> str:
    compact = value.replace(",", "").strip()
    match = re.search(r"-?\d+", compact)
    return match.group(0) if match else ""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def decode_html(raw: bytes) -> str:
    for encoding in ("gb18030", "utf-8"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("gb18030", errors="replace")


def stable_query(url: str) -> dict[str, list[str]]:
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qs(
        parsed.query,
        keep_blank_values=True,
        encoding="gb18030",
        errors="replace",
    )
    return {key: query[key] for key in sorted(query) if key not in DYNAMIC_QUERY_KEYS}


def query_fingerprint(url: str) -> str:
    payload = {
        "scheme": urllib.parse.urlsplit(url).scheme,
        "host": urllib.parse.urlsplit(url).netloc,
        "path": urllib.parse.urlsplit(url).path,
        "query": stable_query(url),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256_bytes(encoded)


def public_url(url: str) -> str:
    """Return a reproducible URL without ephemeral signature/session values."""
    parsed = urllib.parse.urlsplit(url)
    kept = []
    for segment in parsed.query.split("&"):
        raw_key = segment.split("=", 1)[0]
        key = urllib.parse.unquote_plus(raw_key, encoding="ascii", errors="replace")
        if key not in DYNAMIC_QUERY_KEYS:
            kept.append(segment)
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "&".join(kept), "")
    )


def replace_page(url: str, page: int, total_pages: int) -> str:
    parsed = urllib.parse.urlsplit(url)
    segments = []
    for segment in parsed.query.split("&"):
        raw_key = segment.split("=", 1)[0]
        key = urllib.parse.unquote_plus(raw_key, encoding="ascii", errors="replace")
        if key not in {"m_p", "page"}:
            segments.append(segment)
    segments.extend((f"m_p={total_pages}", f"page={page}"))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, "&".join(segments), "")
    )


def first_link(cell, page_url: str) -> str:
    hrefs = cell.xpath(".//a[1]/@href")
    return urllib.parse.urljoin(page_url, hrefs[0]) if hrefs else ""


def id_from_url(url: str, keys: Iterable[str]) -> str:
    if not url:
        return ""
    query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    for key in keys:
        values = query.get(key)
        if values:
            return values[0]
    match = re.search(r"/(\d+)(?:/|$)", urllib.parse.urlsplit(url).path)
    return match.group(1) if match else ""


def parse_catalog_page(raw: bytes, page_url: str) -> ParsedPage:
    try:
        document = html.fromstring(decode_html(raw))
    except Exception as exc:  # pragma: no cover - lxml defensive path
        raise LayoutChanged(f"HTML parse failed: {exc}") from exc
    page_text = clean_text(document.text_content())
    if any(marker in page_text for marker in AUTH_WALL_MARKERS):
        raise AuthenticationRequired("authentication-required")

    catalog_table = None
    catalog_rows = []
    for table in document.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        headers = [clean_text(cell.text_content()) for cell in rows[0].xpath("./th|./td")]
        if headers == EXPECTED_HEADERS:
            catalog_table = table
            catalog_rows = rows[1:]
            break
    if catalog_table is None:
        raise LayoutChanged("expected seven-column catalog table not found")

    parsed_rows: list[dict[str, object]] = []
    for position, row in enumerate(catalog_rows, start=1):
        cells = row.xpath("./td")
        if len(cells) != len(EXPECTED_HEADERS):
            raise LayoutChanged(
                f"row {position} has {len(cells)} cells; expected {len(EXPECTED_HEADERS)}"
            )
        values = [clean_text(cell.text_content()) for cell in cells]
        author_url = first_link(cells[0], page_url)
        work_url = first_link(cells[1], page_url)
        parsed_rows.append(
            {
                "row_position": position,
                "author": values[0],
                "work_title": values[1],
                "genre_full": values[2],
                "progress": values[3],
                "word_count_raw": values[4],
                "word_count": normalized_integer(values[4]),
                "score_raw": values[5],
                "score": normalized_integer(values[5]),
                "publish_time": values[6],
                "author_url": author_url,
                "author_id": id_from_url(author_url, ("authorid", "author_id")),
                "work_url": work_url,
                "work_id": id_from_url(work_url, ("novelid", "id")),
            }
        )

    last_links = [
        urllib.parse.urljoin(page_url, href)
        for link in document.xpath("//a")
        if clean_text(link.text_content()) == "末页"
        for href in link.xpath("./@href")
    ]
    last_url = last_links[0] if last_links else None
    declared_last = None
    if last_url:
        page_values = urllib.parse.parse_qs(urllib.parse.urlsplit(last_url).query).get("page")
        if page_values and page_values[0].isdigit():
            declared_last = int(page_values[0])
    return ParsedPage(parsed_rows, declared_last, last_url)


def build_opener(
    cookie_file: Path | None,
    user_agent: str,
    ca_file: Path | None,
) -> urllib.request.OpenerDirector:
    handlers: list[object] = []
    if ca_file:
        context = ssl.create_default_context(cafile=ca_file.as_posix())
        handlers.append(urllib.request.HTTPSHandler(context=context))
    if cookie_file:
        jar = http.cookiejar.MozillaCookieJar(cookie_file.as_posix())
        jar.load(ignore_discard=True, ignore_expires=True)
        handlers.append(urllib.request.HTTPCookieProcessor(jar))
    opener = urllib.request.build_opener(*handlers)
    opener.addheaders = [
        ("User-Agent", user_agent),
        ("Accept", "text/html,application/xhtml+xml"),
        ("Accept-Language", "zh-CN,zh;q=0.9,en;q=0.5"),
        ("Accept-Encoding", "identity"),
    ]
    return opener


def fetch(opener: urllib.request.OpenerDirector, url: str, timeout: float) -> tuple[bytes, int]:
    request = urllib.request.Request(url)
    with opener.open(request, timeout=timeout) as response:
        return response.read(), int(response.status)


def setup_database(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA synchronous=NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS run_config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pages (
            page_number INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            row_count INTEGER NOT NULL DEFAULT 0,
            retrieved_at TEXT,
            page_sha256 TEXT,
            response_bytes INTEGER,
            raw_relpath TEXT,
            request_url_sha256 TEXT,
            request_url_public TEXT,
            http_status INTEGER,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            error_type TEXT,
            error_message TEXT
        );
        CREATE TABLE IF NOT EXISTS works (
            page_number INTEGER NOT NULL,
            row_position INTEGER NOT NULL,
            author TEXT,
            author_id TEXT,
            author_url TEXT,
            work_title TEXT,
            work_id TEXT,
            work_url TEXT,
            genre_full TEXT,
            progress TEXT,
            word_count_raw TEXT,
            word_count TEXT,
            score_raw TEXT,
            score TEXT,
            publish_time TEXT,
            retrieved_at TEXT NOT NULL,
            page_sha256 TEXT NOT NULL,
            PRIMARY KEY (page_number, row_position)
        );
        CREATE INDEX IF NOT EXISTS idx_works_work_id ON works(work_id);
        CREATE INDEX IF NOT EXISTS idx_works_author_id ON works(author_id);
        CREATE INDEX IF NOT EXISTS idx_works_publish_time ON works(publish_time);
        CREATE TABLE IF NOT EXISTS events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            page_number INTEGER,
            event_type TEXT NOT NULL,
            detail TEXT
        );
        """
    )
    connection.commit()
    return connection


def config_get(connection: sqlite3.Connection, key: str) -> str | None:
    row = connection.execute("SELECT value FROM run_config WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def config_set(connection: sqlite3.Connection, key: str, value: object) -> None:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
    connection.execute(
        "INSERT INTO run_config(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, rendered),
    )


def event(connection: sqlite3.Connection, page: int | None, kind: str, detail: str) -> None:
    connection.execute(
        "INSERT INTO events(occurred_at, page_number, event_type, detail) VALUES (?, ?, ?, ?)",
        (now_iso(), page, kind, detail[:1000]),
    )
    connection.commit()


def atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_raw(raw_dir: Path, page: int, raw: bytes, policy: str) -> str:
    if policy == "none":
        return ""
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"page-{page:06d}.html.gz"
    temporary = path.with_suffix(path.suffix + ".tmp")
    with gzip.open(temporary, "wb", compresslevel=6) as handle:
        handle.write(raw)
    temporary.replace(path)
    return path.relative_to(raw_dir.parent).as_posix()


def page_is_complete(connection: sqlite3.Connection, page: int, total: int) -> bool:
    row = connection.execute(
        "SELECT status, row_count FROM pages WHERE page_number = ?", (page,)
    ).fetchone()
    if not row or row[0] != "ok":
        return False
    row_count = int(row[1])
    if page == total:
        return 1 <= row_count <= 100
    return MIN_NONFINAL_ROWS <= row_count <= 100


def store_success(
    connection: sqlite3.Connection,
    *,
    page: int,
    parsed: ParsedPage,
    raw: bytes,
    raw_relpath: str,
    url: str,
    http_status: int,
    attempt_count: int,
) -> None:
    retrieved_at = now_iso()
    digest = sha256_bytes(raw)
    with connection:
        connection.execute("DELETE FROM works WHERE page_number = ?", (page,))
        for item in parsed.rows:
            connection.execute(
                """
                INSERT INTO works(
                    page_number, row_position, author, author_id, author_url,
                    work_title, work_id, work_url, genre_full, progress,
                    word_count_raw, word_count, score_raw, score, publish_time,
                    retrieved_at, page_sha256
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    page,
                    item["row_position"],
                    item["author"],
                    item["author_id"],
                    item["author_url"],
                    item["work_title"],
                    item["work_id"],
                    item["work_url"],
                    item["genre_full"],
                    item["progress"],
                    item["word_count_raw"],
                    item["word_count"],
                    item["score_raw"],
                    item["score"],
                    item["publish_time"],
                    retrieved_at,
                    digest,
                ),
            )
        connection.execute(
            """
            INSERT INTO pages(
                page_number, status, row_count, retrieved_at, page_sha256,
                response_bytes, raw_relpath, request_url_sha256,
                request_url_public, http_status, attempt_count,
                error_type, error_message
            ) VALUES (?, 'ok', ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(page_number) DO UPDATE SET
                status='ok', row_count=excluded.row_count,
                retrieved_at=excluded.retrieved_at,
                page_sha256=excluded.page_sha256,
                response_bytes=excluded.response_bytes,
                raw_relpath=excluded.raw_relpath,
                request_url_sha256=excluded.request_url_sha256,
                request_url_public=excluded.request_url_public,
                http_status=excluded.http_status,
                attempt_count=excluded.attempt_count,
                error_type=NULL, error_message=NULL
            """,
            (
                page,
                len(parsed.rows),
                retrieved_at,
                digest,
                len(raw),
                raw_relpath,
                sha256_bytes(url.encode("utf-8")),
                public_url(url),
                http_status,
                attempt_count,
            ),
        )


def store_failure(
    connection: sqlite3.Connection,
    *,
    page: int,
    url: str,
    attempt_count: int,
    error: Exception,
    http_status: int | None = None,
) -> None:
    with connection:
        connection.execute(
            """
            INSERT INTO pages(
                page_number, status, request_url_sha256, request_url_public,
                http_status, attempt_count, error_type, error_message
            ) VALUES (?, 'failed', ?, ?, ?, ?, ?, ?)
            ON CONFLICT(page_number) DO UPDATE SET
                status='failed', request_url_sha256=excluded.request_url_sha256,
                request_url_public=excluded.request_url_public,
                http_status=excluded.http_status,
                attempt_count=excluded.attempt_count,
                error_type=excluded.error_type,
                error_message=excluded.error_message
            """,
            (
                page,
                sha256_bytes(url.encode("utf-8")),
                public_url(url),
                http_status,
                attempt_count,
                type(error).__name__,
                str(error)[:1000],
            ),
        )


def reconciliation(connection: sqlite3.Connection, expected_pages: int) -> dict[str, object]:
    status_counts = dict(connection.execute("SELECT status, COUNT(*) FROM pages GROUP BY status"))
    ok_pages = int(status_counts.get("ok", 0))
    row_count = int(connection.execute("SELECT COUNT(*) FROM works").fetchone()[0])
    distinct_work_ids = int(
        connection.execute(
            "SELECT COUNT(DISTINCT work_id) FROM works WHERE work_id <> ''"
        ).fetchone()[0]
    )
    rows_with_work_id = int(
        connection.execute("SELECT COUNT(*) FROM works WHERE work_id <> ''").fetchone()[0]
    )
    duplicate_work_id_rows = rows_with_work_id - distinct_work_ids
    warning_nonfinal_pages = int(
        connection.execute(
            "SELECT COUNT(*) FROM pages WHERE status='ok' AND page_number < ? AND row_count <> 100",
            (expected_pages,),
        ).fetchone()[0]
    )
    severe_nonfinal_pages = int(
        connection.execute(
            "SELECT COUNT(*) FROM pages WHERE status='ok' AND page_number < ? AND row_count < ?",
            (expected_pages, MIN_NONFINAL_ROWS),
        ).fetchone()[0]
    )
    last_page_rows_row = connection.execute(
        "SELECT row_count FROM pages WHERE status='ok' AND page_number = ?",
        (expected_pages,),
    ).fetchone()
    last_page_rows = int(last_page_rows_row[0]) if last_page_rows_row else 0
    all_pages_ok = ok_pages == expected_pages and severe_nonfinal_pages == 0 and 1 <= last_page_rows <= 100
    return {
        "generated_at": now_iso(),
        "expected_pages": expected_pages,
        "page_status_counts": status_counts,
        "ok_pages": ok_pages,
        "missing_or_failed_pages": expected_pages - ok_pages,
        "rows": row_count,
        "rows_with_work_id": rows_with_work_id,
        "distinct_work_ids": distinct_work_ids,
        "duplicate_work_id_rows": duplicate_work_id_rows,
        "page_count_warning_pages": warning_nonfinal_pages,
        "invalid_nonfinal_page_count": severe_nonfinal_pages,
        "last_page_rows": last_page_rows,
        "collection_complete": all_pages_ok,
        "catalog_omission_free": "unproven-live-catalog",
    }


def discover_catalog(
    opener: urllib.request.OpenerDirector,
    base_url: str,
    timeout: float,
) -> tuple[int, str, ParsedPage, bytes, int]:
    raw, status = fetch(opener, base_url, timeout)
    parsed = parse_catalog_page(raw, base_url)
    if not parsed.declared_last_page or not parsed.last_page_url:
        raise LayoutChanged("last-page link and declared page count were not found")
    return parsed.declared_last_page, parsed.last_page_url, parsed, raw, status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawl JJWXC public catalog metadata safely.")
    parser.add_argument("--base-url", help="Filtered JJWXC bookbase URL; dynamic token is runtime-only")
    parser.add_argument("--vintage", default=dt.date.today().isoformat())
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--cookie-file", type=Path)
    parser.add_argument("--ca-file", type=Path)
    parser.add_argument("--start-page", type=int, default=1)
    parser.add_argument("--end-page", type=int)
    parser.add_argument("--max-pages", type=int)
    parser.add_argument("--expected-pages", type=int)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--jitter-seconds", type=float, default=0.5)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument(
        "--page-failure-policy",
        choices=("stop", "continue"),
        default="stop",
        help="Whether to stop at a page failure or keep crawling and leave the page as failed.",
    )
    parser.add_argument("--raw-policy", choices=("all", "none"), default="all")
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    parser.add_argument("--parse-fixture", type=Path)
    parser.add_argument("--fixture-url", default="https://www.jjwxc.net/bookbase.php?page=1")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.parse_fixture:
        try:
            parsed = parse_catalog_page(args.parse_fixture.read_bytes(), args.fixture_url)
        except CrawlError as exc:
            payload = {"error_type": type(exc).__name__, "error": str(exc)}
            print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload)
            return 3 if isinstance(exc, AuthenticationRequired) else 2
        payload = {
            "row_count": len(parsed.rows),
            "declared_last_page": parsed.declared_last_page,
            "headers": EXPECTED_HEADERS,
            "required_field_complete": all(
                item["author"] and item["work_title"] and item["genre_full"] and item["publish_time"]
                for item in parsed.rows
            ),
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else payload)
        return 0

    if not args.base_url:
        raise SystemExit("--base-url is required unless --parse-fixture is used")
    if args.start_page < 1 or args.retries < 1 or args.delay_seconds < 0 or args.jitter_seconds < 0:
        raise SystemExit("invalid crawl bounds or retry/delay setting")
    if args.max_pages is not None and args.max_pages < 1:
        raise SystemExit("--max-pages must be at least 1")

    cookie_file = args.cookie_file or (
        Path(os.environ["JJWXC_COOKIE_FILE"]) if os.environ.get("JJWXC_COOKIE_FILE") else None
    )
    if cookie_file and not cookie_file.exists():
        raise SystemExit("cookie file does not exist")
    ca_file = args.ca_file
    if ca_file is None and os.environ.get("SSL_CERT_FILE"):
        ca_file = Path(os.environ["SSL_CERT_FILE"])
    if ca_file is None and Path("/etc/ssl/cert.pem").exists():
        ca_file = Path("/etc/ssl/cert.pem")
    if ca_file and not ca_file.exists():
        raise SystemExit("CA file does not exist")
    opener = build_opener(cookie_file, args.user_agent, ca_file)
    vintage_root = args.output_root or (DATA_ROOT / f"jjwxc_vintage_{args.vintage}")
    vintage_root.mkdir(parents=True, exist_ok=True)
    raw_dir = vintage_root / "raw"
    connection = setup_database(vintage_root / "crawl.sqlite")

    try:
        total_pages, last_url, first_page, first_raw, first_status = discover_catalog(
            opener, args.base_url, args.timeout_seconds
        )
        if args.expected_pages and total_pages != args.expected_pages:
            raise CrawlError(
                f"declared pages changed: expected {args.expected_pages}, observed {total_pages}"
            )
        fingerprint = query_fingerprint(args.base_url)
        prior_fingerprint_raw = config_get(connection, "query_fingerprint")
        if prior_fingerprint_raw:
            prior_fingerprint = json.loads(prior_fingerprint_raw)
            if prior_fingerprint != fingerprint:
                raise CrawlError("query fingerprint differs from the existing vintage")

        config_set(connection, "query_fingerprint", fingerprint)
        config_set(connection, "stable_query", stable_query(args.base_url))
        config_set(connection, "source_url_public", public_url(args.base_url))
        config_set(connection, "expected_pages", total_pages)
        config_set(connection, "vintage", args.vintage)
        config_set(connection, "crawl_started_or_resumed_at", now_iso())
        config_set(connection, "raw_policy", args.raw_policy)
        config_set(connection, "page_failure_policy", args.page_failure_policy)
        config_set(connection, "delay_seconds", args.delay_seconds)
        config_set(connection, "jitter_seconds", args.jitter_seconds)
        config_set(connection, "cookie_supplied", bool(cookie_file))
        config_set(connection, "tls_ca_file", ca_file.as_posix() if ca_file else "system-default")
        connection.commit()

        if args.start_page <= 1 and not page_is_complete(connection, 1, total_pages):
            if len(first_page.rows) != 100 and total_pages > 1:
                raise PageCountMismatch(f"page 1 returned {len(first_page.rows)} rows")
            raw_relpath = write_raw(raw_dir, 1, first_raw, args.raw_policy)
            store_success(
                connection,
                page=1,
                parsed=first_page,
                raw=first_raw,
                raw_relpath=raw_relpath,
                url=args.base_url,
                http_status=first_status,
                attempt_count=1,
            )

        end_page = min(args.end_page or total_pages, total_pages)
        if end_page < args.start_page:
            raise CrawlError("end page precedes start page")
        pages = list(range(max(args.start_page, 2), end_page + 1))
        if args.max_pages is not None:
            pages = pages[: max(0, args.max_pages - (1 if args.start_page <= 1 else 0))]
        requested_pages = ([1] if args.start_page <= 1 <= end_page else []) + pages

        for page in pages:
            if page_is_complete(connection, page, total_pages):
                continue
            url = replace_page(last_url, page, total_pages)
            last_error: Exception | None = None
            for attempt in range(1, args.retries + 1):
                http_status = None
                try:
                    raw, http_status = fetch(opener, url, args.timeout_seconds)
                    parsed = parse_catalog_page(raw, url)
                    if page < total_pages:
                        if len(parsed.rows) < MIN_NONFINAL_ROWS or len(parsed.rows) > 100:
                            raise PageCountMismatch(
                                f"page {page} returned {len(parsed.rows)} rows; expected between {MIN_NONFINAL_ROWS} and 100"
                            )
                        if len(parsed.rows) != 100:
                            event(
                                connection,
                                page,
                                "page-count-anomaly",
                                f"page {page} returned {len(parsed.rows)} rows; expected 100",
                            )
                    if page == total_pages and not (1 <= len(parsed.rows) <= 100):
                        raise PageCountMismatch(
                            f"last page {page} returned {len(parsed.rows)} rows"
                        )
                    raw_relpath = write_raw(raw_dir, page, raw, args.raw_policy)
                    store_success(
                        connection,
                        page=page,
                        parsed=parsed,
                        raw=raw,
                        raw_relpath=raw_relpath,
                        url=url,
                        http_status=http_status,
                        attempt_count=attempt,
                    )
                    last_error = None
                    break
                except AuthenticationRequired as exc:
                    store_failure(
                        connection,
                        page=page,
                        url=url,
                        attempt_count=attempt,
                        error=exc,
                        http_status=http_status,
                    )
                    event(connection, page, "authentication-required", "crawl stopped; refresh authorized session")
                    raise
                except RETRYABLE_CRAWL_EXCEPTIONS as exc:
                    last_error = exc
                    store_failure(
                        connection,
                        page=page,
                        url=url,
                        attempt_count=attempt,
                        error=exc,
                        http_status=http_status,
                    )
                    if attempt < args.retries:
                        time.sleep(min(60.0, 2 ** (attempt - 1)) + random.random())
            if last_error is not None:
                event(connection, page, "page-failed", str(last_error))
                if args.page_failure_policy == "stop":
                    raise CrawlError(f"page {page} failed after {args.retries} attempts: {last_error}")

            summary = reconciliation(connection, total_pages)
            summary["page_failure_policy"] = args.page_failure_policy
            atomic_write_json(vintage_root / "manifest.json", summary)
            delay = args.delay_seconds + random.random() * args.jitter_seconds
            if delay:
                time.sleep(delay)

        summary = reconciliation(connection, total_pages)
        requested_range_complete = all(
            page_is_complete(connection, page, total_pages) for page in requested_pages
        )
        summary.update(
            {
                "source_url_public": public_url(args.base_url),
                "query_fingerprint": fingerprint,
                "stable_query": stable_query(args.base_url),
                "page_failure_policy": args.page_failure_policy,
                "crawl_window_finished_at": now_iso(),
                "cookie_supplied": bool(cookie_file),
                "raw_policy": args.raw_policy,
                "requested_pages": {
                    "start": requested_pages[0],
                    "end": requested_pages[-1],
                    "count": len(requested_pages),
                },
                "requested_range_complete": requested_range_complete,
            }
        )
        atomic_write_json(vintage_root / "manifest.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2) if args.json else summary)
        return 0 if requested_range_complete else 2
    except AuthenticationRequired:
        summary = reconciliation(connection, int(json.loads(config_get(connection, "expected_pages") or "0")))
        summary["terminal_status"] = "authentication-required"
        atomic_write_json(vintage_root / "manifest.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2), file=sys.stderr)
        return 3
    finally:
        with contextlib.suppress(Exception):
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
