from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import install as inst  # noqa: E402

BEGIN = inst.BEGIN


def wrapped(text: str) -> str:
    return f"{BEGIN}\n{text}\n{inst.END}\n"


class ClaudeCollectPlansTests(unittest.TestCase):
    def test_claude_mapping_memory_and_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "dist" / "claude"
            (src / "skills" / "selfdistill-x").mkdir(parents=True)
            (src / "CLAUDE.md").write_text(wrapped("L1"), encoding="utf-8")
            (src / "skills" / "selfdistill-x" / "SKILL.md").write_text(
                "---\nname: selfdistill-x\n---\n\nbody\n", encoding="utf-8")
            with unittest.mock.patch.object(inst, "DIST", root / "dist"), \
                 unittest.mock.patch.object(inst, "CLAUDE_HOME", root / "claude-home"):
                plans = inst.collect_plans("claude")
            dests = {str(d) for _r, d, _e, _n in plans}
            self.assertIn(str(root / "claude-home" / "CLAUDE.md"), dests)
            self.assertIn(str(root / "claude-home" / "skills" / "selfdistill-x" / "SKILL.md"), dests)

    def test_existing_claude_md_content_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "dist" / "claude"
            src.mkdir(parents=True)
            (src / "CLAUDE.md").write_text(wrapped("L1"), encoding="utf-8")
            home = root / "claude-home"
            home.mkdir()
            (home / "CLAUDE.md").write_text("# 我自己的规则\n\n- 别删我\n", encoding="utf-8")
            with unittest.mock.patch.object(inst, "DIST", root / "dist"), \
                 unittest.mock.patch.object(inst, "CLAUDE_HOME", home):
                plans = inst.collect_plans("claude")
            merged = plans[0][3]
            self.assertIn("别删我", merged)
            self.assertIn(BEGIN, merged)


class ClaudeEndToEndTests(unittest.TestCase):
    def test_claude_target_end_to_end_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(PROJECT_ROOT, repo,
                            ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
            shutil.copytree(repo / "examples" / "demo-profile" / "canonical",
                            repo / "workspace" / "canonical", dirs_exist_ok=True)
            home = Path(tmp) / "home"
            home.mkdir()
            env = dict(os.environ, HOME=str(home))
            build = subprocess.run([sys.executable, "build.py"], cwd=str(repo),
                                   capture_output=True, text=True, env=env)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([sys.executable, "install.py", "--target", "claude", "--yes"],
                                 cwd=str(repo), capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            memory = (home / ".claude" / "CLAUDE.md").read_text(encoding="utf-8")
            self.assertIn(BEGIN, memory)
            self.assertIn("# [SIMULATED] Demo 协作契约", memory)
            skills = home / ".claude" / "skills"
            self.assertTrue((skills / "selfdistill-decision-logic" / "SKILL.md").exists())
            self.assertTrue((skills / "selfdistill-user-profile" / "SKILL.md").exists())
            rerun = subprocess.run([sys.executable, "install.py", "--target", "claude", "--yes"],
                                   cwd=str(repo), capture_output=True, text=True, env=env)
            self.assertEqual(rerun.returncode, 0, rerun.stderr)
            self.assertIn("无需变更", rerun.stdout)


if __name__ == "__main__":
    unittest.main()
