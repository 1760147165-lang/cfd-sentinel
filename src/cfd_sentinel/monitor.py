"""Runtime log monitoring for CFD solver processes."""

from __future__ import annotations

import queue
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from .fluent import CheckpointVerification, verify_checkpoint_pairs
from .notify import Notifier


ITERATION_PATTERNS = (
    re.compile(r"^\s*(\d+)\s+(?:[-+0-9.eE]+\s+){2,}"),
    re.compile(r"iterations?-completed\s*=\s*(\d+)", re.IGNORECASE),
    re.compile(r"\biteration\s+(\d+)\b", re.IGNORECASE),
)
FATAL_PATTERNS = (
    re.compile(r"\bFATAL\b", re.IGNORECASE),
    re.compile(r"uninitialized flow field", re.IGNORECASE),
    re.compile(r"No journal response to dialog box", re.IGNORECASE),
    re.compile(r"floating point exception", re.IGNORECASE),
    re.compile(r"segmentation fault", re.IGNORECASE),
    re.compile(r"license.*(?:fail|error|denied)", re.IGNORECASE),
    re.compile(r"Error Object:", re.IGNORECASE),
)


@dataclass
class LogState:
    last_iteration: Optional[int] = None
    fatal_lines: List[str] = field(default_factory=list)
    last_progress_time: float = field(default_factory=time.monotonic)

    def consume(self, line: str) -> None:
        for pattern in ITERATION_PATTERNS:
            match = pattern.search(line)
            if match:
                self.last_iteration = int(match.group(1))
                self.last_progress_time = time.monotonic()
                break
        if any(pattern.search(line) for pattern in FATAL_PATTERNS):
            compact = line.strip()
            if compact and compact not in self.fatal_lines:
                self.fatal_lines.append(compact)


@dataclass(frozen=True)
class RunResult:
    return_code: int
    last_iteration: Optional[int]
    fatal_lines: tuple
    checkpoint_verification: Optional[CheckpointVerification]

    @property
    def passed(self) -> bool:
        checkpoint_ok = (
            self.checkpoint_verification is None or self.checkpoint_verification.passed
        )
        return self.return_code == 0 and not self.fatal_lines and checkpoint_ok


def _reader(stream, output_queue: "queue.Queue[Optional[str]]") -> None:
    try:
        for line in iter(stream.readline, ""):
            output_queue.put(line)
    finally:
        output_queue.put(None)


def _checkpoint_summary(result: Optional[CheckpointVerification]) -> str:
    if result is None:
        return "Checkpoint verification: not requested"
    return (
        "Checkpoint verification: {status}\n"
        "Complete pairs: {pairs}\n"
        "Missing case: {missing_case}\n"
        "Missing data: {missing_data}\n"
        "Empty files: {empty}"
    ).format(
        status="PASS" if result.passed else "FAIL",
        pairs=", ".join(result.pairs) or "none",
        missing_case=", ".join(result.missing_case) or "none",
        missing_data=", ".join(result.missing_data) or "none",
        empty=", ".join(result.empty_files) or "none",
    )


def run_and_monitor(
    command: Sequence[str],
    log_path: Path | str,
    notifier: Notifier,
    stale_seconds: int = 1800,
    checkpoint_dir: Optional[Path | str] = None,
    checkpoint_prefix: str = "",
) -> RunResult:
    if not command:
        raise ValueError("solver command is empty")
    if stale_seconds <= 0:
        raise ValueError("stale timeout must be positive")

    log_file = Path(log_path)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    state = LogState()
    output_queue: "queue.Queue[Optional[str]]" = queue.Queue()
    fatal_alert_sent = False
    stale_alert_sent = False

    notifier.send(
        "[CFD Sentinel] Solver started",
        "Command: {}\nLog: {}".format(" ".join(command), log_file),
    )
    with log_file.open("w", encoding="utf-8", buffering=1) as log_stream:
        try:
            process = subprocess.Popen(
                list(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            notifier.send(
                "[CFD Sentinel] Solver failed to start",
                "Command: {}\nError: {}".format(" ".join(command), exc),
            )
            raise
        if process.stdout is None:
            raise RuntimeError("failed to capture solver output")
        thread = threading.Thread(target=_reader, args=(process.stdout, output_queue), daemon=True)
        thread.start()
        reader_finished = False
        while not reader_finished or not output_queue.empty():
            try:
                line = output_queue.get(timeout=1.0)
            except queue.Empty:
                line = ""
            if line is None:
                reader_finished = True
            elif line:
                print(line, end="")
                log_stream.write(line)
                previous_iteration = state.last_iteration
                state.consume(line)
                if state.last_iteration != previous_iteration:
                    stale_alert_sent = False
                if state.fatal_lines and not fatal_alert_sent:
                    notifier.send(
                        "[CFD Sentinel] Fatal log marker detected",
                        "Log: {}\nLast iteration: {}\nMarker: {}".format(
                            log_file,
                            state.last_iteration,
                            state.fatal_lines[-1],
                        ),
                    )
                    fatal_alert_sent = True
            if (
                process.poll() is None
                and time.monotonic() - state.last_progress_time >= stale_seconds
                and not stale_alert_sent
            ):
                notifier.send(
                    "[CFD Sentinel] Solver progress stalled",
                    "No iteration progress for at least {} seconds.\n"
                    "Log: {}\nLast iteration: {}".format(
                        stale_seconds, log_file, state.last_iteration
                    ),
                )
                stale_alert_sent = True
        return_code = process.wait()

    checkpoint_result = (
        verify_checkpoint_pairs(checkpoint_dir, checkpoint_prefix)
        if checkpoint_dir is not None
        else None
    )
    result = RunResult(
        return_code=return_code,
        last_iteration=state.last_iteration,
        fatal_lines=tuple(state.fatal_lines),
        checkpoint_verification=checkpoint_result,
    )
    subject = (
        "[CFD Sentinel] Solver completed"
        if result.passed
        else "[CFD Sentinel] Solver requires attention"
    )
    notifier.send(
        subject,
        "Return code: {}\nLast iteration: {}\nFatal markers: {}\n{}".format(
            result.return_code,
            result.last_iteration,
            "\n".join(result.fatal_lines) or "none",
            _checkpoint_summary(checkpoint_result),
        ),
    )
    return result


def watch_log(
    log_path: Path | str,
    notifier: Notifier,
    stale_seconds: int = 1800,
    poll_seconds: float = 2.0,
    from_start: bool = False,
    completion_marker: Optional[str] = None,
) -> LogState:
    if stale_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("monitor timing values must be positive")
    path = Path(log_path)
    state = LogState()
    fatal_alert_sent = False
    stale_alert_sent = False
    position = 0
    if path.exists() and not from_start:
        position = path.stat().st_size

    while True:
        if path.exists():
            size = path.stat().st_size
            if size < position:
                position = 0
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                stream.seek(position)
                lines = stream.readlines()
                position = stream.tell()
            for line in lines:
                previous_iteration = state.last_iteration
                state.consume(line)
                if state.last_iteration != previous_iteration:
                    stale_alert_sent = False
                if state.fatal_lines and not fatal_alert_sent:
                    notifier.send(
                        "[CFD Sentinel] Fatal log marker detected",
                        "Log: {}\nLast iteration: {}\nMarker: {}".format(
                            path, state.last_iteration, state.fatal_lines[-1]
                        ),
                    )
                    fatal_alert_sent = True
                if completion_marker and completion_marker in line:
                    notifier.send(
                        "[CFD Sentinel] Completion marker detected",
                        "Log: {}\nLast iteration: {}".format(path, state.last_iteration),
                    )
                    return state
        if (
            time.monotonic() - state.last_progress_time >= stale_seconds
            and not stale_alert_sent
        ):
            notifier.send(
                "[CFD Sentinel] Solver progress stalled",
                "No iteration progress for at least {} seconds.\n"
                "Log: {}\nLast iteration: {}".format(
                    stale_seconds, path, state.last_iteration
                ),
            )
            stale_alert_sent = True
        time.sleep(poll_seconds)
