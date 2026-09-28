from __future__ import annotations

import hashlib
import html
import os
import sqlite3
import stat
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Iterator


Progress = Callable[[int, int, str], None]
SCHEMA_VERSION = 1


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _normalized(path: os.PathLike[str] | str) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def _contains(parent: os.PathLike[str] | str, child: os.PathLike[str] | str) -> bool:
    try:
        return os.path.commonpath((_normalized(parent), _normalized(child))) == _normalized(parent)
    except ValueError:  # Different Windows drives.
        return False


def _validate_roots(roots: list[tuple[str, str]], db_path: Path) -> None:
    if not roots:
        raise ValueError("Select at least one folder.")
    labels = set()
    paths: list[str] = []
    for label, raw_path in roots:
        label = label.strip()
        path = Path(raw_path).expanduser().resolve()
        if not label or label in labels:
            raise ValueError("Each folder needs a distinct, nonempty label.")
        if not path.is_dir():
            raise ValueError(f"Folder is unavailable: {path}")
        if _contains(path, db_path):
            raise ValueError("Save the project database outside every scanned folder.")
        labels.add(label)
        paths.append(str(path))
    for index, first in enumerate(paths):
        for second in paths[index + 1 :]:
            if _contains(first, second) or _contains(second, first):
                raise ValueError("Selected folders must not overlap.")


def _connect(db_path: os.PathLike[str] | str) -> sqlite3.Connection:
    path = Path(db_path)
    if not path.is_file():
        raise ValueError(f"Project database does not exist: {path}")
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version != SCHEMA_VERSION:
        conn.close()
        raise ValueError(f"Unsupported project format version: {version}")
    return conn


@contextmanager
def _open(db_path: os.PathLike[str] | str) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def create_project(db_path: os.PathLike[str] | str, roots: Iterable[tuple[str, str]]) -> None:
    path = Path(db_path).expanduser().resolve()
    roots_list = [(label.strip(), str(Path(folder).expanduser().resolve())) for label, folder in roots]
    _validate_roots(roots_list, path)
    if path.exists():
        raise FileExistsError(f"Will not overwrite an existing project: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            """
            PRAGMA foreign_keys = ON;
            PRAGMA user_version = 1;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE roots (
                id INTEGER PRIMARY KEY,
                label TEXT NOT NULL UNIQUE,
                path TEXT NOT NULL
            );
            CREATE TABLE scans (
                id INTEGER PRIMARY KEY,
                kind TEXT NOT NULL,
                baseline_id INTEGER,
                started_utc TEXT NOT NULL,
                finished_utc TEXT,
                status TEXT NOT NULL,
                file_count INTEGER NOT NULL DEFAULT 0,
                byte_count INTEGER NOT NULL DEFAULT 0,
                skipped_links INTEGER NOT NULL DEFAULT 0,
                error_count INTEGER NOT NULL DEFAULT 0,
                added INTEGER NOT NULL DEFAULT 0,
                missing INTEGER NOT NULL DEFAULT 0,
                changed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE entries (
                scan_id INTEGER NOT NULL REFERENCES scans(id),
                root_id INTEGER NOT NULL REFERENCES roots(id),
                rel_path TEXT NOT NULL,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                sha256 TEXT NOT NULL,
                PRIMARY KEY (scan_id, root_id, rel_path)
            ) WITHOUT ROWID;
            CREATE TABLE scan_errors (
                scan_id INTEGER NOT NULL REFERENCES scans(id),
                root_id INTEGER NOT NULL REFERENCES roots(id),
                rel_path TEXT NOT NULL,
                message TEXT NOT NULL
            );
            CREATE INDEX scan_errors_scan ON scan_errors(scan_id);
            """
        )
        conn.executemany("INSERT INTO roots(label, path) VALUES (?, ?)", roots_list)
        conn.execute("INSERT INTO metadata(key, value) VALUES ('created_utc', ?)", (_now(),))
        conn.commit()
    except Exception:
        conn.close()
        path.unlink(missing_ok=True)
        raise
    finally:
        conn.close()


def list_roots(db_path: os.PathLike[str] | str) -> list[dict]:
    with _open(db_path) as conn:
        return [dict(row) for row in conn.execute("SELECT id, label, path FROM roots ORDER BY id")]


def remap_root(db_path: os.PathLike[str] | str, root_id: int, new_path: os.PathLike[str] | str) -> None:
    path = Path(new_path).expanduser().resolve()
    with _open(db_path) as conn:
        roots = [dict(row) for row in conn.execute("SELECT id, label, path FROM roots ORDER BY id")]
        if not any(root["id"] == root_id for root in roots):
            raise ValueError(f"Unknown folder ID: {root_id}")
        selected = [(root["label"], str(path) if root["id"] == root_id else root["path"]) for root in roots]
        _validate_roots(selected, Path(db_path).resolve())
        conn.execute("UPDATE roots SET path = ? WHERE id = ?", (str(path), root_id))


def _baseline_id(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM metadata WHERE key = 'baseline_id'").fetchone()
    return int(row[0]) if row else None


def list_scans(db_path: os.PathLike[str] | str) -> list[dict]:
    with _open(db_path) as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM scans ORDER BY id DESC")]


def current_baseline_id(db_path: os.PathLike[str] | str) -> int | None:
    with _open(db_path) as conn:
        return _baseline_id(conn)


def _walk_files(root: Path, root_id: int, on_error: Callable[[int, str, str], None],
                on_link: Callable[[], None]) -> Iterator[tuple[str, Path]]:
    stack = [root]
    while stack:
        directory = stack.pop()
        rel_directory = directory.relative_to(root).as_posix()
        try:
            with os.scandir(directory) as iterator:
                children = sorted(iterator, key=lambda item: item.name, reverse=True)
        except OSError as exc:
            on_error(root_id, rel_directory, str(exc))
            continue
        for item in children:
            rel = Path(item.path).relative_to(root).as_posix()
            try:
                if item.is_symlink():
                    on_link()
                elif item.is_dir(follow_symlinks=False):
                    stack.append(Path(item.path))
                elif item.is_file(follow_symlinks=False):
                    yield rel, Path(item.path)
                else:
                    on_error(root_id, rel, "Unsupported file type")
            except OSError as exc:
                on_error(root_id, rel, str(exc))


def _hash_stable(path: Path, cancel: threading.Event | None) -> tuple[int, int, str]:
    before = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise OSError("File is no longer a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            if cancel and cancel.is_set():
                raise _Cancelled()
            digest.update(chunk)
    after = path.stat(follow_symlinks=False)
    if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
        raise OSError("File changed during hashing")
    return after.st_size, after.st_mtime_ns, digest.hexdigest()


class _Cancelled(Exception):
    pass


def _diff_query() -> str:
    return """
        SELECT 'missing' AS change, b.root_id, b.rel_path, b.sha256 AS before_hash,
               NULL AS after_hash FROM entries b
        LEFT JOIN entries c ON c.scan_id = :current AND c.root_id = b.root_id AND c.rel_path = b.rel_path
        WHERE b.scan_id = :baseline AND c.scan_id IS NULL
        UNION ALL
        SELECT 'added', c.root_id, c.rel_path, NULL, c.sha256 FROM entries c
        LEFT JOIN entries b ON b.scan_id = :baseline AND b.root_id = c.root_id AND b.rel_path = c.rel_path
        WHERE c.scan_id = :current AND b.scan_id IS NULL
        UNION ALL
        SELECT 'changed', b.root_id, b.rel_path, b.sha256, c.sha256 FROM entries b
        JOIN entries c ON c.scan_id = :current AND c.root_id = b.root_id AND c.rel_path = b.rel_path
        WHERE b.scan_id = :baseline AND b.sha256 <> c.sha256
        ORDER BY 2, 3
    """


def _comparison_counts(conn: sqlite3.Connection, baseline: int, current: int) -> dict[str, int]:
    counts = {"added": 0, "missing": 0, "changed": 0}
    for row in conn.execute(_diff_query(), {"baseline": baseline, "current": current}):
        counts[row["change"]] += 1
    return counts


def scan_project(db_path: os.PathLike[str] | str, progress: Progress | None = None,
                 cancel: threading.Event | None = None) -> dict:
    """Hash every readable regular file. No prior hash is trusted as a scan shortcut."""
    path = Path(db_path).expanduser().resolve()
    conn = _connect(path)
    try:
        roots = [dict(row) for row in conn.execute("SELECT id, label, path FROM roots ORDER BY id")]
        _validate_roots([(root["label"], root["path"]) for root in roots], path)
        baseline = _baseline_id(conn)
        kind = "baseline" if baseline is None else "check"
        cursor = conn.execute(
            "INSERT INTO scans(kind, baseline_id, started_utc, status) VALUES (?, ?, ?, 'running')",
            (kind, baseline, _now()),
        )
        scan_id = cursor.lastrowid
        conn.commit()
        files = 0
        byte_count = 0
        links = 0
        errors = 0

        def on_error(root_id: int, rel: str, message: str) -> None:
            nonlocal errors
            errors += 1
            conn.execute(
                "INSERT INTO scan_errors(scan_id, root_id, rel_path, message) VALUES (?, ?, ?, ?)",
                (scan_id, root_id, rel, message),
            )

        def on_link() -> None:
            nonlocal links
            links += 1

        status = "complete"
        try:
            for root in roots:
                if cancel and cancel.is_set():
                    raise _Cancelled()
                for rel, file_path in _walk_files(Path(root["path"]), root["id"], on_error, on_link):
                    if cancel and cancel.is_set():
                        raise _Cancelled()
                    try:
                        size, mtime_ns, sha256 = _hash_stable(file_path, cancel)
                    except _Cancelled:
                        raise
                    except OSError as exc:
                        on_error(root["id"], rel, str(exc))
                        continue
                    conn.execute(
                        "INSERT INTO entries(scan_id, root_id, rel_path, size, mtime_ns, sha256) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (scan_id, root["id"], rel, size, mtime_ns, sha256),
                    )
                    files += 1
                    byte_count += size
                    if files % 100 == 0:
                        conn.commit()
                    if progress:
                        progress(files, byte_count, f"{root['label']}/{rel}")
        except _Cancelled:
            status = "cancelled"
        except Exception:
            conn.execute(
                "UPDATE scans SET finished_utc=?, status='failed', file_count=?, byte_count=?, "
                "skipped_links=?, error_count=? WHERE id=?",
                (_now(), files, byte_count, links, errors, scan_id),
            )
            conn.commit()
            raise
        try:
            if status == "complete" and errors:
                status = "incomplete"
            counts = {"added": 0, "missing": 0, "changed": 0}
            if status == "complete":
                if kind == "baseline":
                    conn.execute("INSERT INTO metadata(key, value) VALUES ('baseline_id', ?)", (str(scan_id),))
                else:
                    counts = _comparison_counts(conn, baseline, scan_id)
            conn.execute(
                "UPDATE scans SET finished_utc=?, status=?, file_count=?, byte_count=?, "
                "skipped_links=?, error_count=?, added=?, missing=?, changed=? WHERE id=?",
                (_now(), status, files, byte_count, links, errors, counts["added"],
                 counts["missing"], counts["changed"], scan_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            conn.execute(
                "UPDATE scans SET finished_utc=?, status='failed', file_count=?, byte_count=?, "
                "skipped_links=?, error_count=? WHERE id=?",
                (_now(), files, byte_count, links, errors, scan_id),
            )
            conn.commit()
            raise
        return dict(conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone())
    finally:
        conn.close()


def trust_scan(db_path: os.PathLike[str] | str, scan_id: int) -> None:
    """Explicitly choose a complete scan as the reference for future checks."""
    with _open(db_path) as conn:
        row = conn.execute("SELECT status FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not row or row["status"] != "complete":
            raise ValueError("Only a complete scan can become the trusted baseline.")
        conn.execute(
            "INSERT INTO metadata(key, value) VALUES ('baseline_id', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (str(scan_id),),
        )


def list_changes(db_path: os.PathLike[str] | str, scan_id: int) -> list[dict]:
    with _open(db_path) as conn:
        scan = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not scan or scan["status"] != "complete" or scan["baseline_id"] is None:
            raise ValueError("Choose a complete check scan.")
        return [dict(row) for row in conn.execute(
            _diff_query(), {"baseline": scan["baseline_id"], "current": scan_id}
        )]


def list_errors(db_path: os.PathLike[str] | str, scan_id: int) -> list[dict]:
    with _open(db_path) as conn:
        return [dict(row) for row in conn.execute(
            "SELECT root_id, rel_path, message FROM scan_errors WHERE scan_id=? ORDER BY root_id, rel_path",
            (scan_id,),
        )]


def export_html(db_path: os.PathLike[str] | str, scan_id: int,
                report_path: os.PathLike[str] | str) -> Path:
    path = Path(report_path).expanduser().resolve()
    db = Path(db_path).expanduser().resolve()
    with _open(db) as conn:
        scan = conn.execute("SELECT * FROM scans WHERE id=?", (scan_id,)).fetchone()
        if not scan:
            raise ValueError(f"Unknown scan ID: {scan_id}")
        roots = {row["id"]: dict(row) for row in conn.execute("SELECT id, label, path FROM roots")}
        if any(_contains(root["path"], path) for root in roots.values()):
            raise ValueError("Save the report outside every scanned folder.")
        if path == db:
            raise ValueError("The report path must differ from the project database.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(path.name + ".tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as output:
                output.write("<!doctype html><html lang='en'><meta charset='utf-8'>"
                             "<meta name='viewport' content='width=device-width, initial-scale=1'>"
                             "<title>FileIntegrityTimeline report</title>"
                             "<style>body{font:16px system-ui,sans-serif;max-width:1100px;margin:2rem auto;padding:0 1rem;color:#17202a}"
                             "h1{margin-bottom:.2rem}.muted{color:#56616d}table{border-collapse:collapse;width:100%;margin:1rem 0}"
                             "th,td{border-bottom:1px solid #dce3e8;padding:.6rem;text-align:left;vertical-align:top;overflow-wrap:anywhere}"
                             "th{background:#edf2f5}code{font-size:.85em}.alert{background:#fff1dc;padding:1rem;border-left:4px solid #b05c00}"
                             "</style><body><h1>File integrity report</h1>")
                output.write(f"<p class='muted'>Scan {scan_id} · {html.escape(scan['started_utc'])} · "
                             f"{html.escape(scan['status'])}</p>")
                if scan["status"] != "complete":
                    output.write("<p class='alert'>This scan was incomplete. No missing-file or integrity verdict "
                                 "was calculated. Fix the errors and scan again.</p>")
                elif scan["baseline_id"] is None:
                    output.write("<p>Trusted baseline created. Later checks will compare against this snapshot.</p>")
                else:
                    output.write(f"<p><strong>{scan['added']} added</strong> · <strong>{scan['missing']} missing</strong> "
                                 f"· <strong>{scan['changed']} changed</strong> compared with trusted scan "
                                 f"{scan['baseline_id']}.</p>")
                output.write(f"<p>{scan['file_count']} files hashed · {scan['byte_count']:,} bytes read · "
                             f"{scan['skipped_links']} symbolic links skipped · {scan['error_count']} errors.</p>")
                output.write("<p class='alert'>This report includes full local folder paths. Review it before sharing. "
                             "A changed hash shows different bytes; it does not establish why they changed or restore them.</p>")
                output.write("<h2>Folders</h2><table><tr><th>Label</th><th>Current path</th></tr>")
                for root in roots.values():
                    output.write(f"<tr><td>{html.escape(root['label'])}</td><td><code>{html.escape(root['path'])}</code></td></tr>")
                output.write("</table>")
                if scan["status"] == "complete" and scan["baseline_id"] is not None and (
                    scan["added"] or scan["missing"] or scan["changed"]
                ):
                    output.write("<h2>Differences</h2><table><tr><th>Status</th><th>Folder</th><th>Relative path</th>"
                                 "<th>Baseline SHA-256</th><th>Current SHA-256</th></tr>")
                    for change in conn.execute(
                        _diff_query(), {"baseline": scan["baseline_id"], "current": scan_id}
                    ):
                        label = roots[change["root_id"]]["label"]
                        output.write("<tr>" + "".join(
                            f"<td><code>{html.escape(str(value or ''))}</code></td>" for value in
                            (change["change"], label, change["rel_path"], change["before_hash"],
                             change["after_hash"])
                        ) + "</tr>")
                    output.write("</table>")
                if scan["error_count"]:
                    output.write("<h2>Scan errors</h2><table><tr><th>Folder</th><th>Path</th><th>Error</th></tr>")
                    for error in conn.execute(
                        "SELECT root_id, rel_path, message FROM scan_errors WHERE scan_id=? ORDER BY root_id, rel_path",
                        (scan_id,),
                    ):
                        output.write("<tr>" + "".join(
                            f"<td>{html.escape(str(value))}</td>" for value in
                            (roots[error["root_id"]]["label"], error["rel_path"], error["message"])
                        ) + "</tr>")
                    output.write("</table>")
                output.write("</body></html>")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return path
