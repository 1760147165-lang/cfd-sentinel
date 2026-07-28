"""Command-line interface for CFD Sentinel."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional, Sequence

from .fluent import audit_journal, harden_journal, verify_checkpoint_pairs
from .monitor import run_and_monitor, watch_log
from .notify import Notifier


def _print_audit(report) -> None:
    print("Journal: {}".format(report.journal))
    print("Total iterations: {}".format(report.total_iterations))
    print("Initialization checkpoint: {}".format("yes" if report.initialization_checkpoint else "NO"))
    print(
        "Periodic checkpoints: {}".format(
            ", ".join(str(value) for value in report.periodic_checkpoints) or "none"
        )
    )
    print(
        "Missing periodic checkpoints: {}".format(
            ", ".join(str(value) for value in report.missing_periodic_checkpoints)
            or "none"
        )
    )
    print("Final checkpoint: {}".format("yes" if report.final_checkpoint else "NO"))
    print("Safe automatic rewrite: {}".format("yes" if report.supported_for_hardening else "NO"))
    print("Result: {}".format("PASS" if report.passed else "FAIL"))
    for finding in report.findings:
        location = " line {}".format(finding.line) if finding.line else ""
        print("[{}] {}{}: {}".format(finding.severity.upper(), finding.code, location, finding.message))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cfd-sentinel",
        description="Audit, harden, and monitor CFD automation workflows.",
    )
    parser.add_argument("--version", action="version", version="CFD Sentinel 0.1.0")
    subparsers = parser.add_subparsers(dest="command_name", required=True)

    audit = subparsers.add_parser("audit", help="Audit a Fluent journal checkpoint policy.")
    audit.add_argument("journal", type=Path)
    audit.add_argument("--interval", type=int, default=1000)
    audit.add_argument("--json", action="store_true", dest="json_output")

    harden = subparsers.add_parser(
        "harden", help="Write a hardened copy with initialization and periodic saves."
    )
    harden.add_argument("journal", type=Path)
    harden.add_argument("--output", type=Path, required=True)
    harden.add_argument("--checkpoint-dir", required=True)
    harden.add_argument("--prefix")
    harden.add_argument("--interval", type=int, default=1000)
    harden.add_argument("--force", action="store_true")

    verify = subparsers.add_parser("verify", help="Verify non-empty case/data checkpoint pairs.")
    verify.add_argument("checkpoint_dir", type=Path)
    verify.add_argument("--prefix", default="")
    verify.add_argument("--json", action="store_true", dest="json_output")

    run = subparsers.add_parser("run", help="Launch and monitor a solver command.")
    run.add_argument("--log", type=Path, required=True)
    run.add_argument("--email")
    run.add_argument("--dry-run-email", action="store_true")
    run.add_argument("--stale-seconds", type=int, default=1800)
    run.add_argument("--checkpoint-dir", type=Path)
    run.add_argument("--checkpoint-prefix", default="")
    run.add_argument("solver_command", nargs=argparse.REMAINDER)

    watch = subparsers.add_parser("watch", help="Monitor a log written by an existing workflow.")
    watch.add_argument("log", type=Path)
    watch.add_argument("--email")
    watch.add_argument("--dry-run-email", action="store_true")
    watch.add_argument("--stale-seconds", type=int, default=1800)
    watch.add_argument("--poll-seconds", type=float, default=2.0)
    watch.add_argument("--from-start", action="store_true")
    watch.add_argument("--completion-marker")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command_name == "audit":
            report = audit_journal(args.journal, args.interval)
            if args.json_output:
                print(report.to_json())
            else:
                _print_audit(report)
            return 0 if report.passed else 2

        if args.command_name == "harden":
            path = harden_journal(
                args.journal,
                args.output,
                checkpoint_dir=args.checkpoint_dir,
                prefix=args.prefix,
                interval=args.interval,
                force=args.force,
            )
            report = audit_journal(path, args.interval)
            print("Wrote hardened journal: {}".format(path))
            _print_audit(report)
            return 0 if report.passed else 2

        if args.command_name == "verify":
            result = verify_checkpoint_pairs(args.checkpoint_dir, args.prefix)
            if args.json_output:
                print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
            else:
                print("Checkpoint directory: {}".format(result.directory))
                print("Complete pairs: {}".format(", ".join(result.pairs) or "none"))
                print("Missing case: {}".format(", ".join(result.missing_case) or "none"))
                print("Missing data: {}".format(", ".join(result.missing_data) or "none"))
                print("Empty files: {}".format(", ".join(result.empty_files) or "none"))
                print("Result: {}".format("PASS" if result.passed else "FAIL"))
            return 0 if result.passed else 2

        notifier = Notifier(args.email, dry_run=args.dry_run_email)
        if args.command_name == "run":
            command = list(args.solver_command)
            if command and command[0] == "--":
                command = command[1:]
            if not command:
                parser.error("run requires a solver command after --")
            result = run_and_monitor(
                command,
                args.log,
                notifier,
                stale_seconds=args.stale_seconds,
                checkpoint_dir=args.checkpoint_dir,
                checkpoint_prefix=args.checkpoint_prefix,
            )
            return 0 if result.passed else 2

        if args.command_name == "watch":
            watch_log(
                args.log,
                notifier,
                stale_seconds=args.stale_seconds,
                poll_seconds=args.poll_seconds,
                from_start=args.from_start,
                completion_marker=args.completion_marker,
            )
            return 0
    except KeyboardInterrupt:
        print("\nMonitoring stopped by user.", file=sys.stderr)
        return 130
    except Exception as exc:
        print("CFD Sentinel error: {}".format(exc), file=sys.stderr)
        return 1
    return 1
