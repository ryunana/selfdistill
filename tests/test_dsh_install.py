from __future__ import annotations

import contextlib
import io
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
END = inst.END


def wrapped_persona(text: str) -> str:
    return f"{BEGIN}\n{text}\n{END}\n"


class PersonaMergeTests(unittest.TestCase):
    def test_fresh_install_returns_full_row(self) -> None:
        out = inst.merge_persona_patch("", wrapped_persona("# L1 契约"))
        self.assertTrue(out.startswith("- id: system-prompt"))
        self.assertIn(inst.DEFAULT_PERSONA_OPENER, out)
        self.assertIn("# L1 契约", out)
        self.assertIn("      <!-- distill:begin -->", out)
        self.assertIn("      <!-- distill:end -->", out)

    def test_empty_list_template_replaced(self) -> None:
        out = inst.merge_persona_patch("[]\n", wrapped_persona("L1"))
        self.assertTrue(out.startswith("- id: system-prompt"))

    def test_marker_region_replaced_preserving_opener(self) -> None:
        existing = (
            "- id: system-prompt\n"
            "  config:\n"
            "    persona: |-\n"
            "      opener {{model}}\n"
            "\n"
            "      <!-- distill:begin -->\n"
            "      old L1\n"
            "      <!-- distill:end -->\n"
        )
        out = inst.merge_persona_patch(existing, wrapped_persona("new L1"))
        self.assertIn("opener {{model}}", out)
        self.assertNotIn("old L1", out)
        self.assertIn("new L1", out)
        self.assertIn("      <!-- distill:begin -->", out)

    def test_user_extra_and_other_rows_preserved(self) -> None:
        existing = (
            "- id: timer\n"
            "  name: 'x'\n"
            "- id: system-prompt\n"
            "  config:\n"
            "    persona: |-\n"
            "      opener\n"
            "\n"
            "      # USER\n"
            "      <!-- distill:begin -->\n"
            "      old\n"
            "      <!-- distill:end -->\n"
        )
        out = inst.merge_persona_patch(existing, wrapped_persona("new"))
        self.assertIn("- id: timer", out)
        self.assertIn("# USER", out)
        self.assertIn("new", out)
        self.assertLess(out.find("- id: timer"), out.find("- id: system-prompt"))

    def test_custom_persona_without_markers_refused(self) -> None:
        existing = "- id: system-prompt\n  config:\n    persona: |-\n      custom\n"
        with self.assertRaises(inst.InstallError):
            inst.merge_persona_patch(existing, wrapped_persona("x"))

    def test_incomplete_markers_refused(self) -> None:
        existing = (
            "- id: system-prompt\n"
            "  config:\n"
            "    persona: |-\n"
            "      <!-- distill:begin -->\n"
            "      no end marker\n"
        )
        with self.assertRaises(inst.InstallError):
            inst.merge_persona_patch(existing, wrapped_persona("x"))

    def test_append_when_no_system_prompt_row(self) -> None:
        existing = "- id: timer\n  name: 'x'\n"
        out = inst.merge_persona_patch(existing, wrapped_persona("L1"))
        self.assertTrue(out.startswith("- id: timer"))
        self.assertIn("- id: system-prompt", out)

    def test_flow_style_refused(self) -> None:
        with self.assertRaises(inst.InstallError):
            inst.merge_persona_patch("[{id: a}]\n", wrapped_persona("x"))

    def test_brace_template_warning(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            inst.build_persona_block(wrapped_persona("含 {{ 花括号 }} 的内容"))
        self.assertIn("{{", buf.getvalue())


class SkillMergeTests(unittest.TestCase):
    def test_new_skill(self) -> None:
        incoming = "---\nname: x\n---\n\nbody\n"
        self.assertEqual(inst.merge_skill("", incoming), incoming)

    def test_owned_skill_replaced_whole_file(self) -> None:
        existing = "---\nname: x\n---\n\n<!-- distill:begin -->\nold\n<!-- distill:end -->\n"
        incoming = "---\nname: x\ndescription: \"new desc\"\n---\n\n<!-- distill:begin -->\nnew\n<!-- distill:end -->\n"
        self.assertEqual(inst.merge_skill(existing, incoming), incoming)

    def test_foreign_skill_refused(self) -> None:
        with self.assertRaises(inst.InstallError):
            inst.merge_skill("# user file\n", "---\nname: x\n---\n\nbody\n")


class CollectPlansTests(unittest.TestCase):
    def test_dsh_mapping_persona_and_skills(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "dist" / "dsh"
            (src / "skills" / "selfstill-x").mkdir(parents=True)
            (src / "persona.md").write_text(wrapped_persona("L1"), encoding="utf-8")
            (src / "skills" / "selfstill-x" / "SKILL.md").write_text(
                "---\nname: selfstill-x\n---\n\nbody\n", encoding="utf-8")
            with unittest.mock.patch.object(inst, "DIST", root / "dist"), \
                 unittest.mock.patch.object(inst, "DSH_HOME", root / "dsh-home"):
                plans = inst.collect_plans("dsh")
            dests = {str(d) for _r, d, _e, _n in plans}
            self.assertIn(str(root / "dsh-home" / "cordis.patch.yml"), dests)
            self.assertIn(str(root / "dsh-home" / "skills" / "selfstill-x" / "SKILL.md"), dests)


class EndToEndTests(unittest.TestCase):
    def test_dsh_target_end_to_end_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            shutil.copytree(PROJECT_ROOT, repo,
                            ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
            dsh_home = Path(tmp) / "dshhome"
            env = dict(os.environ, DSH_HOME=str(dsh_home))
            build = subprocess.run([sys.executable, "build.py"], cwd=str(repo),
                                   capture_output=True, text=True, env=env)
            self.assertEqual(build.returncode, 0, build.stderr)
            run = subprocess.run([sys.executable, "install.py", "--target", "dsh", "--yes"],
                                 cwd=str(repo), capture_output=True, text=True, env=env)
            self.assertEqual(run.returncode, 0, run.stderr)
            patch = (dsh_home / "cordis.patch.yml").read_text(encoding="utf-8")
            self.assertIn("- id: system-prompt", patch)
            self.assertIn("# L1 协作契约", patch)
            self.assertTrue((dsh_home / "skills" / "selfstill-decision-logic" / "SKILL.md").exists())
            self.assertTrue((dsh_home / "skills" / "selfstill-agent-work" / "SKILL.md").exists())
            self.assertTrue((dsh_home / "skills" / "selfstill-user-profile" / "SKILL.md").exists())
            rerun = subprocess.run([sys.executable, "install.py", "--target", "dsh", "--yes"],
                                   cwd=str(repo), capture_output=True, text=True, env=env)
            self.assertEqual(rerun.returncode, 0, rerun.stderr)
            self.assertIn("无需变更", rerun.stdout)


if __name__ == "__main__":
    unittest.main()
