"""Audit and harden ANSYS Fluent journal files.

The transformer deliberately supports only explicit, standalone Fluent TUI
commands. Dynamic Scheme-generated iteration loops are reported as unsupported
instead of being rewritten speculatively.
"""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple


INITIALIZE_RE = re.compile(r"^\s*/solve/initialize/initialize-flow\s*$", re.IGNORECASE)
ITERATE_RE = re.compile(r"^(\s*)/solve/iterate\s+(\d+)\s*$", re.IGNORECASE)
ANY_ITERATE_RE = re.compile(r"/solve/iterate", re.IGNORECASE)
WRITE_CASE_RE = re.compile(r"^\s*/file/write-case(?:\s+|$)", re.IGNORECASE)
WRITE_DATA_RE = re.compile(r"^\s*/file/write-data(?:\s+|$)", re.IGNORECASE)
WRITE_CASE_DATA_RE = re.compile(r"^\s*/file/write-case-data(?:\s+|$)", re.IGNORECASE)
RESPONSE_RE = re.compile(r"^\s*(?:ok|yes|y)\s*$", re.IGNORECASE)
SENTINEL_BEGIN = "; CFD_SENTINEL_CHECKPOINT_BEGIN"
SENTINEL_END = "; CFD_SENTINEL_CHECKPOINT_END"


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str
    line: Optional[int] = None


@dataclass
class AuditReport:
    journal: str
    interval: int
    total_iterations: int
    initialization_count: int
    explicit_iteration_commands: int
    initialization_checkpoint: bool
    periodic_checkpoints: List[int] = field(default_factory=list)
    missing_periodic_checkpoints: List[int] = field(default_factory=list)
    final_checkpoint: bool = False
    supported_for_hardening: bool = True
    findings: List[Finding] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(item.severity == "error" for item in self.findings)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["passed"] = self.passed
        return data

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, ensure_ascii=False)


@dataclass(frozen=True)
class CheckpointVerification:
    directory: str
    prefix: str
    pairs: Tuple[str, ...]
    missing_case: Tuple[str, ...]
    missing_data: Tuple[str, ...]
    empty_files: Tuple[str, ...]

    @property
    def passed(self) -> bool:
        return bool(self.pairs) and not (
            self.missing_case or self.missing_data or self.empty_files
        )

    def to_dict(self) -> dict:
        data = asdict(self)
        data["passed"] = self.passed
        return data


def _events_between(lines: Sequence[str], start: int, end: int) -> Tuple[bool, bool]:
    has_case = False
    has_data = False
    for line in lines[start:end]:
        if WRITE_CASE_DATA_RE.match(line):
            has_case = True
            has_data = True
        elif WRITE_CASE_RE.match(line):
            has_case = True
        elif WRITE_DATA_RE.match(line):
            has_data = True
    return has_case, has_data


def _strip_generated_blocks(lines: Iterable[str]) -> List[str]:
    cleaned: List[str] = []
    inside = False
    for line in lines:
        marker = line.strip()
        if marker == SENTINEL_BEGIN:
            inside = True
            continue
        if marker == SENTINEL_END:
            inside = False
            continue
        if not inside:
            cleaned.append(line)
    if inside:
        raise ValueError("unterminated CFD Sentinel checkpoint block")
    return cleaned


def audit_lines(lines: Sequence[str], journal: str, interval: int = 1000) -> AuditReport:
    if interval <= 0:
        raise ValueError("checkpoint interval must be positive")

    init_indices = [index for index, line in enumerate(lines) if INITIALIZE_RE.match(line)]
    iterate_events: List[Tuple[int, int]] = []
    dynamic_iteration_lines: List[int] = []
    for index, line in enumerate(lines):
        match = ITERATE_RE.match(line)
        if match:
            iterate_events.append((index, int(match.group(2))))
        elif ANY_ITERATE_RE.search(line) and not line.lstrip().startswith(";"):
            dynamic_iteration_lines.append(index + 1)

    total = sum(count for _, count in iterate_events)
    report = AuditReport(
        journal=journal,
        interval=interval,
        total_iterations=total,
        initialization_count=len(init_indices),
        explicit_iteration_commands=len(iterate_events),
        initialization_checkpoint=False,
    )

    if not init_indices:
        report.findings.append(
            Finding("error", "missing-initialization", "No explicit Fluent initialization command found.")
        )
    elif len(init_indices) > 1:
        report.supported_for_hardening = False
        report.findings.append(
            Finding(
                "error",
                "multiple-initializations",
                "Multiple initialization commands require manual review.",
                init_indices[1] + 1,
            )
        )

    if dynamic_iteration_lines:
        report.supported_for_hardening = False
        for line_number in dynamic_iteration_lines:
            report.findings.append(
                Finding(
                    "error",
                    "dynamic-iteration",
                    "Iteration command is embedded in Scheme or another unsupported construct.",
                    line_number,
                )
            )

    if not iterate_events:
        report.findings.append(
            Finding("error", "missing-iterations", "No explicit /solve/iterate command found.")
        )

    if init_indices and iterate_events:
        init_end = init_indices[0] + 1
        if init_end < len(lines) and RESPONSE_RE.match(lines[init_end]):
            init_end += 1
        first_iterate_index = iterate_events[0][0]
        has_case, has_data = _events_between(lines, init_end, first_iterate_index)
        report.initialization_checkpoint = has_case and has_data
        if not report.initialization_checkpoint:
            report.findings.append(
                Finding(
                    "error",
                    "missing-initialization-checkpoint",
                    "Initialization is not followed by a complete case/data checkpoint before iteration.",
                    init_indices[0] + 1,
                )
            )

    cumulative = 0
    for event_index, (line_index, count) in enumerate(iterate_events):
        cumulative += count
        next_index = (
            iterate_events[event_index + 1][0]
            if event_index + 1 < len(iterate_events)
            else len(lines)
        )
        has_case, has_data = _events_between(lines, line_index + 1, next_index)
        if cumulative % interval == 0 and has_case and has_data:
            report.periodic_checkpoints.append(cumulative)

    expected = list(range(interval, total + 1, interval))
    report.missing_periodic_checkpoints = [
        iteration for iteration in expected if iteration not in report.periodic_checkpoints
    ]
    for iteration in report.missing_periodic_checkpoints:
        report.findings.append(
            Finding(
                "error",
                "missing-periodic-checkpoint",
                "Missing complete case/data checkpoint at iteration {}.".format(iteration),
            )
        )

    if iterate_events:
        last_line, _ = iterate_events[-1]
        has_case, has_data = _events_between(lines, last_line + 1, len(lines))
        report.final_checkpoint = has_case and has_data
        if not report.final_checkpoint:
            report.findings.append(
                Finding(
                    "error",
                    "missing-final-checkpoint",
                    "No complete final case/data save follows the last iteration command.",
                    last_line + 1,
                )
            )

    if report.passed:
        report.findings.append(
            Finding("info", "audit-passed", "Journal satisfies the configured checkpoint policy.")
        )
    return report


def audit_journal(path: Path | str, interval: int = 1000) -> AuditReport:
    journal_path = Path(path)
    lines = journal_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    return audit_lines(lines, str(journal_path), interval)


def _fluent_path(value: str) -> str:
    return value.replace("\\", "/").rstrip("/")


def _safe_prefix(prefix: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", prefix).strip("._")
    if not cleaned:
        raise ValueError("checkpoint prefix contains no usable characters")
    return cleaned


def _checkpoint_block(case_path: str, data_path: str, label: str) -> List[str]:
    escaped_case = case_path.replace('"', '\\"')
    escaped_data = data_path.replace('"', '\\"')
    return [
        SENTINEL_BEGIN,
        "; label={}".format(label),
        '(if (file-exists? "{0}") (delete-file "{0}"))'.format(escaped_case),
        '(if (file-exists? "{0}") (delete-file "{0}"))'.format(escaped_data),
        '/file/write-case "{}"'.format(escaped_case),
        '(if (not (file-exists? "{}")) (error "CFD Sentinel: case checkpoint missing after save"))'.format(
            escaped_case
        ),
        '/file/write-data "{}"'.format(escaped_data),
        '(if (not (file-exists? "{}")) (error "CFD Sentinel: data checkpoint missing after save"))'.format(
            escaped_data
        ),
        '(format #t "\\nCFD_SENTINEL_CHECKPOINT_OK>>> {}\\n")'.format(label),
        SENTINEL_END,
    ]


def _paths(checkpoint_dir: str, prefix: str, label: str) -> Tuple[str, str]:
    base = "{}/{}_{}".format(_fluent_path(checkpoint_dir), _safe_prefix(prefix), label)
    return base + ".cas.h5", base + ".dat.h5"


def harden_lines(
    original_lines: Sequence[str],
    checkpoint_dir: str,
    prefix: str,
    interval: int = 1000,
) -> List[str]:
    if interval <= 0:
        raise ValueError("checkpoint interval must be positive")
    lines = _strip_generated_blocks(original_lines)
    report = audit_lines(lines, "<memory>", interval)
    if not report.supported_for_hardening:
        raise ValueError("journal contains constructs that cannot be safely rewritten")
    if report.initialization_count != 1:
        raise ValueError("journal must contain exactly one explicit initialization command")
    if report.explicit_iteration_commands == 0:
        raise ValueError("journal must contain at least one explicit iteration command")

    last_iterate_index = max(index for index, line in enumerate(lines) if ITERATE_RE.match(line))
    existing_periodic = set(report.periodic_checkpoints)
    output: List[str] = [
        "; Hardened by CFD Sentinel. The source journal is left unchanged.",
        "; Checkpoint interval: {} iterations.".format(interval),
    ]
    cumulative = 0
    pending_init_save = False

    for index, line in enumerate(lines):
        if pending_init_save and not RESPONSE_RE.match(line):
            case_path, data_path = _paths(checkpoint_dir, prefix, "initialized")
            output.extend(_checkpoint_block(case_path, data_path, "initialized"))
            pending_init_save = False

        init_match = INITIALIZE_RE.match(line)
        iterate_match = ITERATE_RE.match(line)
        if init_match:
            output.append(line)
            pending_init_save = not report.initialization_checkpoint
            continue
        if iterate_match:
            indentation = iterate_match.group(1)
            remaining = int(iterate_match.group(2))
            while remaining > 0:
                until_boundary = interval - (cumulative % interval)
                chunk = min(remaining, until_boundary)
                output.append("{}{}".format(indentation, "/solve/iterate {}".format(chunk)))
                cumulative += chunk
                remaining -= chunk
                if cumulative % interval == 0 and cumulative not in existing_periodic:
                    label = "iter_{:06d}".format(cumulative)
                    case_path, data_path = _paths(checkpoint_dir, prefix, label)
                    output.extend(_checkpoint_block(case_path, data_path, label))
            if index == last_iterate_index and not report.final_checkpoint:
                case_path, data_path = _paths(checkpoint_dir, prefix, "final")
                output.extend(_checkpoint_block(case_path, data_path, "final"))
            continue
        output.append(line)

    if pending_init_save:
        case_path, data_path = _paths(checkpoint_dir, prefix, "initialized")
        output.extend(_checkpoint_block(case_path, data_path, "initialized"))
    return output


def harden_journal(
    source: Path | str,
    output: Path | str,
    checkpoint_dir: str,
    prefix: Optional[str] = None,
    interval: int = 1000,
    force: bool = False,
) -> Path:
    source_path = Path(source).resolve()
    output_path = Path(output).resolve()
    if source_path == output_path:
        raise ValueError("refusing to overwrite the source journal; choose a separate output")
    if output_path.exists():
        if not force:
            raise FileExistsError("{} already exists; use --force to replace it".format(output_path))
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = output_path.with_name(output_path.name + ".backup_" + timestamp)
        shutil.copy2(output_path, backup)

    original = source_path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    hardened = harden_lines(
        original,
        checkpoint_dir=checkpoint_dir,
        prefix=prefix or source_path.stem,
        interval=interval,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(hardened) + "\n", encoding="utf-8")
    return output_path


def _checkpoint_stem(path: Path) -> Optional[Tuple[str, str]]:
    name = path.name
    if name.endswith(".cas.h5"):
        return name[: -len(".cas.h5")], "case"
    if name.endswith(".dat.h5"):
        return name[: -len(".dat.h5")], "data"
    return None


def verify_checkpoint_pairs(
    directory: Path | str,
    prefix: str = "",
) -> CheckpointVerification:
    root = Path(directory)
    cases = {}
    data = {}
    empty: List[str] = []
    if root.is_dir():
        for path in root.iterdir():
            parsed = _checkpoint_stem(path)
            if parsed is None or (prefix and not path.name.startswith(prefix)):
                continue
            stem, kind = parsed
            if path.stat().st_size <= 0:
                empty.append(path.name)
            if kind == "case":
                cases[stem] = path
            else:
                data[stem] = path
    stems = sorted(set(cases) | set(data))
    pairs = tuple(stem for stem in stems if stem in cases and stem in data)
    missing_case = tuple(stem for stem in stems if stem not in cases)
    missing_data = tuple(stem for stem in stems if stem not in data)
    return CheckpointVerification(
        directory=str(root),
        prefix=prefix,
        pairs=pairs,
        missing_case=missing_case,
        missing_data=missing_data,
        empty_files=tuple(sorted(empty)),
    )
