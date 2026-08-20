from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from distill_audit import (  # noqa: E402
    AuditError,
    audit_project,
    validate_v2_candidate,
    verify_report,
)


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "continuous-distillation"


def tree_hashes(root: Path, excluded: tuple[str, ...] = ("reports/",)) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        if any(relative.startswith(prefix) for prefix in excluded):
            continue
        result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


class DistillAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "project"
        shutil.copytree(FIXTURE_ROOT, self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_valid_candidate_and_schema_failures(self) -> None:
        candidate = json.loads((self.root / "inbox" / "conversation.json").read_text(encoding="utf-8"))
        validate_v2_candidate(candidate)

        missing = copy.deepcopy(candidate)
        del missing["change"]["correct"]
        with self.assertRaisesRegex(AuditError, "change.correct"):
            validate_v2_candidate(missing)

        illegal = copy.deepcopy(candidate)
        illegal["status"] = "maybe"
        with self.assertRaisesRegex(AuditError, "status"):
            validate_v2_candidate(illegal)

    def test_rediscovery_candidate_must_reference_evidence(self) -> None:
        candidate = json.loads((self.root / "inbox" / "conversation.json").read_text(encoding="utf-8"))
        candidate["id"] = "rediscovery-example-01"
        candidate["source"]["type"] = "rediscovery"
        with self.assertRaisesRegex(AuditError, "rediscovery candidate"):
            validate_v2_candidate(candidate)

    def test_inventory_covers_all_inputs_and_excludes_readme_from_evidence(self) -> None:
        before = tree_hashes(self.root)
        report = audit_project(self.root)
        after = tree_hashes(self.root)
        self.assertEqual(before, after)

        inventory = json.loads((report / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(inventory["summary"]["canonical_files"], 2)
        self.assertEqual(inventory["summary"]["inbox_files"], 2)
        self.assertEqual(inventory["summary"]["candidate_units"], 2)
        self.assertEqual(inventory["summary"]["content_files"], 4)
        self.assertEqual(inventory["summary"]["instruction_files"], 1)
        self.assertEqual(len(inventory["files"]), 5)
        self.assertEqual(inventory["summary"]["evidence_records"], 6)
        self.assertEqual(
            {p.name for p in report.iterdir()},
            {"inventory.json", "evidence.jsonl", "evidence.md", "coverage.md"},
        )
        evidence = [json.loads(line) for line in (report / "evidence.jsonl").read_text().splitlines()]
        self.assertFalse(any(record["source_path"].endswith("inbox/README.md") for record in evidence))
        self.assertTrue(any(record["title"] == "[SIMULATED] Notes" for record in evidence))

    def test_empty_inbox_still_audits(self) -> None:
        for path in (self.root / "inbox").glob("*.json"):
            path.unlink()
        report = audit_project(self.root)
        inventory = json.loads((report / "inventory.json").read_text(encoding="utf-8"))
        self.assertEqual(inventory["summary"]["candidate_units"], 0)
        self.assertEqual(inventory["summary"]["inbox_files"], 0)
        self.assertEqual(verify_report(self.root, report)["references"], 0)

    def test_cli_uses_copied_project_root_from_external_cwd(self) -> None:
        copied_root = Path(self.temp.name) / "copied-project"
        copied_root.mkdir()
        shutil.copytree(FIXTURE_ROOT, copied_root / "workspace")
        script = copied_root / "distill_audit.py"
        shutil.copy2(PROJECT_ROOT / "distill_audit.py", script)
        caller = Path(self.temp.name) / "external-caller"
        caller.mkdir()

        result = subprocess.run(
            [sys.executable, str(script), "audit"],
            cwd=caller,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        self.assertIn("audit: OK", result.stdout)
        self.assertTrue((copied_root / "workspace" / "reports" / "latest").is_dir())
        self.assertFalse((caller / "reports").exists())

    def test_heading_ids_stay_stable_when_body_changes(self) -> None:
        path = self.root / "canonical" / "01-l1-contract.md"
        from distill_audit import _canonical_sections

        ids_before = [record["evidence_id"] for record in _canonical_sections(path, self.root)]
        path.write_text(path.read_text(encoding="utf-8").replace("Keep the evidence local", "Keep the fixture evidence local"), encoding="utf-8")
        ids_after = [record["evidence_id"] for record in _canonical_sections(path, self.root)]
        self.assertEqual(ids_before, ids_after)

    def test_verify_rejects_source_drift(self) -> None:
        report = audit_project(self.root)
        verify_report(self.root, report)
        path = self.root / "canonical" / "notes.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n[SIMULATED] changed\n", encoding="utf-8")
        with self.assertRaisesRegex(AuditError, "source drift"):
            verify_report(self.root, report)

    def test_verify_rejects_unknown_reference_and_empty_rediscovery_candidate(self) -> None:
        report = audit_project(self.root)
        (report / "discoveries.md").write_text(
            "# [SIMULATED] discoveries\n\nEvidence: [ev-ffffffffffffffff]\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(AuditError, "unknown evidence ID"):
            verify_report(self.root, report)

        (report / "discoveries.md").unlink()
        candidate = json.loads((self.root / "inbox" / "conversation.json").read_text(encoding="utf-8"))
        candidate["id"] = "rediscovery-example-02"
        candidate["source"]["type"] = "rediscovery"
        candidates = report / "candidates"
        candidates.mkdir()
        (candidates / "empty.json").write_text(json.dumps(candidate), encoding="utf-8")
        with self.assertRaisesRegex(AuditError, "rediscovery candidate"):
            verify_report(self.root, report)

    def test_report_permissions_are_private(self) -> None:
        report = audit_project(self.root)
        self.assertEqual(report.stat().st_mode & 0o777, 0o700)
        for path in report.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
