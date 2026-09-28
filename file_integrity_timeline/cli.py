from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

from . import __version__
from .core import (
    create_project,
    current_baseline_id,
    export_html,
    list_changes,
    list_roots,
    list_scans,
    remap_root,
    scan_project,
    trust_scan,
)


def default_report_path(project: str | Path, scan_id: int) -> Path:
    path = Path(project).resolve()
    return path.with_name(f"{path.stem}-report-{scan_id}.html")


def _root_arg(value: str) -> tuple[str, str]:
    label, separator, path = value.partition("=")
    if not separator or not label.strip() or not path.strip():
        raise argparse.ArgumentTypeError("Use LABEL=FOLDER, for example Photos=D:\\Photos")
    return label.strip(), path.strip()


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="fit-self-test-") as temporary:
        base = Path(temporary)
        first = base / "first"
        second = base / "second"
        first.mkdir()
        second.mkdir()
        (first / "changed.txt").write_text("original", encoding="utf-8")
        (first / "removed.txt").write_text("removed", encoding="utf-8")
        (second / "stable.txt").write_text("stable", encoding="utf-8")
        project = base / "test.fit"
        create_project(project, [("First", str(first)), ("Second", str(second))])
        baseline = scan_project(project)
        assert baseline["status"] == "complete" and baseline["kind"] == "baseline"
        (first / "changed.txt").write_text("different", encoding="utf-8")
        (first / "removed.txt").unlink()
        (second / "new.txt").write_text("new", encoding="utf-8")
        check = scan_project(project)
        assert (check["status"], check["added"], check["missing"], check["changed"]) == (
            "complete", 1, 1, 1
        )
        assert len(list_changes(project, check["id"])) == 3
        report = export_html(project, check["id"], base / "report.html")
        assert "changed.txt" in report.read_text(encoding="utf-8")
        assert (second / "stable.txt").read_text(encoding="utf-8") == "stable"
    print("Self-test passed: baseline, changes, report, and read-only source files.")


def main(argv: list[str] | None = None) -> int:
    args_list = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        prog="FileIntegrityTimeline", description="Read-only SHA-256 snapshots of local folders."
    )
    parser.add_argument("--version", action="version", version=f"FileIntegrityTimeline {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a project outside the folders you will scan")
    init.add_argument("project")
    init.add_argument("--root", type=_root_arg, action="append", required=True, metavar="LABEL=FOLDER")
    scan = commands.add_parser("scan", help="Hash every file and compare against the trusted baseline")
    scan.add_argument("project")
    scan.add_argument("--report", help="HTML report path (defaults beside the project database)")
    history = commands.add_parser("history", help="Show previous checks")
    history.add_argument("project")
    roots = commands.add_parser("roots", help="Show folder IDs and locations")
    roots.add_argument("project")
    remap = commands.add_parser("remap", help="Update a folder location after a drive letter changes")
    remap.add_argument("project")
    remap.add_argument("root_id", type=int)
    remap.add_argument("folder")
    trust = commands.add_parser("trust", help="Explicitly make a complete scan the future reference")
    trust.add_argument("project")
    trust.add_argument("scan_id", type=int)
    report = commands.add_parser("report", help="Export a previous scan as HTML")
    report.add_argument("project")
    report.add_argument("scan_id", type=int)
    report.add_argument("output")
    commands.add_parser("self-test", help="Exercise the built-in reproducible scan scenario")
    if not args_list:
        parser.print_help()
        return 0
    args = parser.parse_args(args_list)
    try:
        if args.command == "init":
            create_project(args.project, args.root)
            print(f"Created {Path(args.project).resolve()}. Run 'scan' to create the first baseline.")
        elif args.command == "scan":
            result = scan_project(args.project)
            output = args.report or default_report_path(args.project, result["id"])
            export_html(args.project, result["id"], output)
            print(f"Scan {result['id']}: {result['status']}; {result['file_count']} files; "
                  f"{result['added']} added, {result['missing']} missing, {result['changed']} changed; "
                  f"{result['error_count']} errors, {result['skipped_links']} links skipped.")
            print(f"Report: {Path(output).resolve()}")
            if result["status"] != "complete":
                return 2
            if result["added"] or result["missing"] or result["changed"]:
                return 1
        elif args.command == "history":
            print(f"Trusted scan: {current_baseline_id(args.project) or 'none'}")
            for row in list_scans(args.project):
                print(f"{row['id']:>4}  {row['started_utc']}  {row['status']:<10}  "
                      f"files={row['file_count']}  +{row['added']} -{row['missing']} ~{row['changed']}")
        elif args.command == "roots":
            for row in list_roots(args.project):
                print(f"{row['id']:>4}  {row['label']}  {row['path']}")
        elif args.command == "remap":
            remap_root(args.project, args.root_id, args.folder)
            print("Folder path updated; historical hashes remain unchanged.")
        elif args.command == "trust":
            trust_scan(args.project, args.scan_id)
            print(f"Scan {args.scan_id} is now the trusted reference for future checks.")
        elif args.command == "report":
            path = export_html(args.project, args.scan_id, args.output)
            print(f"Report: {path}")
        elif args.command == "self-test":
            self_test()
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    return 0
