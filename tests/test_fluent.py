import tempfile
import unittest
from pathlib import Path

from cfd_sentinel.fluent import (
    audit_lines,
    harden_lines,
    harden_journal,
    verify_checkpoint_pairs,
)


MISSING = [
    '/file/set-tui-version "23.1"',
    "/solve/initialize/initialize-flow",
    "ok",
    "/solve/iterate 5000",
    "/exit",
    "yes",
]


class FluentAuditTests(unittest.TestCase):
    def test_missing_policy_is_detected(self):
        report = audit_lines(MISSING, "missing.jou", interval=1000)
        self.assertFalse(report.passed)
        self.assertFalse(report.initialization_checkpoint)
        self.assertEqual(report.missing_periodic_checkpoints, [1000, 2000, 3000, 4000, 5000])
        self.assertFalse(report.final_checkpoint)

    def test_hardening_splits_iterations_and_passes_audit(self):
        hardened = harden_lines(
            MISSING,
            checkpoint_dir="D:/work/case/checkpoints",
            prefix="case01",
            interval=1000,
        )
        self.assertEqual(hardened.count("/solve/iterate 1000"), 5)
        report = audit_lines(hardened, "hardened.jou", interval=1000)
        self.assertTrue(report.passed, report.to_json())
        self.assertTrue(report.initialization_checkpoint)
        self.assertEqual(report.periodic_checkpoints, [1000, 2000, 3000, 4000, 5000])
        self.assertTrue(report.final_checkpoint)

    def test_dynamic_scheme_iteration_is_refused(self):
        lines = [
            "/solve/initialize/initialize-flow",
            '(ti-menu-load-string "/solve/iterate 5000")',
        ]
        report = audit_lines(lines, "dynamic.jou")
        self.assertFalse(report.supported_for_hardening)
        with self.assertRaises(ValueError):
            harden_lines(lines, "D:/checkpoints", "case")

    def test_source_journal_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "run.jou"
            source.write_text("\n".join(MISSING), encoding="utf-8")
            with self.assertRaises(ValueError):
                harden_journal(source, source, "D:/checkpoints")

    def test_force_replacement_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "run.jou"
            output = Path(directory) / "run.sentinel.jou"
            source.write_text("\n".join(MISSING), encoding="utf-8")
            output.write_text("user-owned old output\n", encoding="utf-8")
            harden_journal(source, output, "D:/checkpoints", force=True)
            backups = list(Path(directory).glob("run.sentinel.jou.backup_*"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(encoding="utf-8"), "user-owned old output\n")


class CheckpointVerificationTests(unittest.TestCase):
    def test_complete_nonempty_pair_passes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case_iter_001000.cas.h5").write_bytes(b"case")
            (root / "case_iter_001000.dat.h5").write_bytes(b"data")
            result = verify_checkpoint_pairs(root, "case_")
            self.assertTrue(result.passed)
            self.assertEqual(result.pairs, ("case_iter_001000",))

    def test_orphan_and_empty_files_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "case_iter_001000.cas.h5").write_bytes(b"")
            (root / "case_iter_002000.dat.h5").write_bytes(b"data")
            result = verify_checkpoint_pairs(root, "case_")
            self.assertFalse(result.passed)
            self.assertEqual(result.missing_data, ("case_iter_001000",))
            self.assertEqual(result.missing_case, ("case_iter_002000",))
            self.assertEqual(result.empty_files, ("case_iter_001000.cas.h5",))


if __name__ == "__main__":
    unittest.main()
