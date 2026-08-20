from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AUDIT_FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "continuous-distillation"


def copy_repo(destination: Path) -> None:
    shutil.copytree(
        PROJECT_ROOT,
        destination,
        ignore=shutil.ignore_patterns(".git", "dist", "__pycache__", ".venv"),
    )


class RepositoryStructureTests(unittest.TestCase):
    def test_public_demo_templates_and_workspace_are_separate(self) -> None:
        self.assertFalse((PROJECT_ROOT / "canonical").exists())
        self.assertFalse((PROJECT_ROOT / "input").exists())
        self.assertFalse((PROJECT_ROOT / "inbox").exists())
        self.assertTrue((PROJECT_ROOT / "examples" / "demo-profile" / "canonical" / "01-l1-contract.md").is_file())
        self.assertTrue((PROJECT_ROOT / "templates" / "profile" / "01-l1-contract.md").is_file())
        self.assertTrue((PROJECT_ROOT / "workspace" / "canonical" / ".gitkeep").is_file())
        # Published install paths remain stable during this non-breaking cleanup.
        self.assertTrue((PROJECT_ROOT / "dsh" / "package.json").is_file())
        self.assertTrue((PROJECT_ROOT / "workbuddy" / "skills" / "selfdistill" / "SKILL.md").is_file())

    def test_build_uses_demo_when_workspace_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            copy_repo(repo)
            run = subprocess.run(
                [sys.executable, "build.py"], cwd=repo, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
            self.assertIn("正在使用虚构 Demo 构建", run.stdout)
            self.assertTrue((repo / "dist" / "index.html").is_file())
            self.assertIn('"source_mode": "demo"', (repo / "dist" / ".selfdistill-build.json").read_text(encoding="utf-8"))

            install_home = Path(td) / "install-home"
            install_home.mkdir()
            for target in ("codex", "hermes", "dsh", "workbuddy"):
                install = subprocess.run(
                    [sys.executable, "install.py", "--target", target, "--yes"], cwd=repo,
                    env={**os.environ, "HOME": str(install_home), "DSH_HOME": str(install_home / ".dsh")},
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(install.returncode, 1, install.stdout + install.stderr)
                self.assertIn("仅可预览，禁止写回", install.stderr)
            self.assertEqual(list(install_home.iterdir()), [])

    def test_build_prefers_workspace_profile_and_allows_install(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            copy_repo(repo)
            demo = repo / "examples" / "demo-profile" / "canonical"
            workspace_canonical = repo / "workspace" / "canonical"
            shutil.copytree(demo, workspace_canonical, dirs_exist_ok=True)
            marker = "[SIMULATED] workspace-profile-marker"
            l1 = workspace_canonical / "01-l1-contract.md"
            l1.write_text(l1.read_text(encoding="utf-8") + "\n\n" + marker + "\n", encoding="utf-8")
            run = subprocess.run(
                [sys.executable, "build.py"], cwd=repo, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(run.returncode, 0, run.stderr or run.stdout)
            self.assertNotIn("正在使用虚构 Demo 构建", run.stdout)
            self.assertIn("workspace-profile-marker", (repo / "dist" / "l1-raw.html").read_text(encoding="utf-8"))
            self.assertIn('"source_mode": "workspace"', (repo / "dist" / ".selfdistill-build.json").read_text(encoding="utf-8"))
            install_home = Path(td) / "workspace-install-home"
            install_home.mkdir()
            install = subprocess.run(
                [sys.executable, "install.py", "--target", "codex", "--yes"], cwd=repo,
                env={**os.environ, "HOME": str(install_home)},
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            self.assertTrue((install_home / ".codex" / "AGENTS.md").is_file())

    def test_release_scan_rejects_tracked_workspace_private_data(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            private = repo / "workspace" / "canonical" / "private.md"
            private.parent.mkdir(parents=True)
            private.write_text("personal fact\n", encoding="utf-8")
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "workspace/canonical/private.md"], cwd=repo, check=True)
            scan = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "scripts" / "scan_before_release.py"), str(repo)],
                cwd=repo, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(scan.returncode, 1, scan.stdout + scan.stderr)
            self.assertIn("受保护目录中的跟踪文件", scan.stdout)

    def test_audit_defaults_to_workspace_and_accepts_both_report_spellings(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "repo"
            repo.mkdir()
            shutil.copy2(PROJECT_ROOT / "distill_audit.py", repo / "distill_audit.py")
            shutil.copytree(AUDIT_FIXTURE, repo / "workspace")
            canonical = repo / "workspace" / "canonical"
            (canonical / "02-l2-decision-logic.md").write_text("# Decisions\n\n## Tradeoff\nPrefer evidence.\n", encoding="utf-8")
            (canonical / "03-l3-user-profile.md").write_text("# Profile\n\n## Work\nShips products.\n", encoding="utf-8")

            audit = subprocess.run(
                [sys.executable, "distill_audit.py", "audit"], cwd=repo,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            )
            self.assertEqual(audit.returncode, 0, audit.stderr or audit.stdout)
            self.assertTrue((repo / "workspace" / "reports" / "latest").is_dir())
            self.assertFalse((repo / "reports").exists())
            coverage = (repo / "workspace" / "reports" / "latest" / "coverage.md").read_text(encoding="utf-8")
            d1_section = coverage.split("## D1 ·", 1)[1].split("## D2 ·", 1)[0]
            self.assertIn("状态：available", d1_section)
            evidence = (repo / "workspace" / "reports" / "latest" / "evidence.md").read_text(encoding="utf-8")
            self.assertIn("`canonical/03-l3-user-profile.md`", evidence)

            for report_arg in ("reports/latest", "workspace/reports/latest"):
                verify = subprocess.run(
                    [sys.executable, "distill_audit.py", "verify", report_arg], cwd=repo,
                    text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
                )
                self.assertEqual(verify.returncode, 0, verify.stderr or verify.stdout)
                self.assertIn("verify: OK", verify.stdout)


if __name__ == "__main__":
    unittest.main()
