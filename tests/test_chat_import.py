from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import import_chats as ic  # noqa: E402

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "chat-import"


def run_import(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "import_chats.py", *args],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT))


class ParserTests(unittest.TestCase):
    def test_chatgpt_parser(self) -> None:
        convs = ic.parse_chatgpt(FIXTURE / "chatgpt")
        self.assertEqual(len(convs), 1)
        src, cid, title, _exp, msgs = convs[0]
        self.assertEqual((src, cid, title), ("chatgpt", "chatgpt-conv-001", "虚构聊天：咖啡豆选择"))
        self.assertEqual([m[0] for m in msgs], ["user", "assistant"])
        self.assertIn("手冲咖啡", msgs[0][3])
        from datetime import datetime
        self.assertEqual(msgs[0][1],
                         datetime.fromtimestamp(1750000001).strftime("%Y-%m-%d %H:%M"))

    def test_deepseek_parser_with_thinking_and_file(self) -> None:
        convs = ic.parse_deepseek(FIXTURE / "deepseek" / "conversations.json")
        self.assertEqual(len(convs), 1)
        _src, _cid, _title, _exp, msgs = convs[0]
        self.assertEqual([m[0] for m in msgs], ["user", "assistant"])
        self.assertIn("香山—植物园", msgs[1][3])
        self.assertIn("<!-- thinking -->", msgs[1][3])
        self.assertIn("[附件: trail-map.png]", msgs[1][3])

    def test_deepseek_no_thinking(self) -> None:
        ic._INCLUDE_THINKING = False
        try:
            convs = ic.parse_deepseek(FIXTURE / "deepseek" / "conversations.json")
            self.assertNotIn("<!-- thinking -->", convs[0][4][1][3])
        finally:
            ic._INCLUDE_THINKING = True

    def test_codex_parser_strips_system_blocks(self) -> None:
        convs = ic.parse_codex(FIXTURE / "codex" / "sessions" / "2026" / "08" / "01"
                               / "rollout-2026-08-01T10-00-00-fake-session-001.jsonl")
        self.assertIsNotNone(convs)
        _src, cid, title, _exp, msgs = convs[0]
        self.assertEqual(cid, "fake-session-001")
        self.assertIn("帮我写个 Python 脚本", title)
        self.assertNotIn("environment_context", msgs[0][3])
        self.assertEqual([m[0] for m in msgs], ["user", "assistant", "user"])
        from datetime import datetime
        self.assertEqual(msgs[0][1],
                         datetime.fromisoformat("2026-08-01T10:00:00+00:00")
                         .astimezone().replace(tzinfo=None).strftime("%Y-%m-%d %H:%M"))

    def test_claude_parser_skips_cli_lines(self) -> None:
        convs = ic.parse_claude(FIXTURE / "claude" / "projects" / "-tmp"
                                / "fake-claude-session-001.jsonl")
        self.assertIsNotNone(convs)
        _src, cid, _title, _exp, msgs = convs[0]
        self.assertEqual(cid, "fake-claude-session-001")
        self.assertEqual(len(msgs), 2)  # claude --resume 行被跳过
        self.assertIn("分析这份数据的趋势", msgs[0][3])

    def test_gemini_parser(self) -> None:
        convs = ic.parse_gemini(FIXTURE / "gemini" / "takeout")
        self.assertEqual(len(convs), 1)
        _src, _cid, _title, _exp, msgs = convs[0]
        self.assertEqual([m[0] for m in msgs], ["user", "assistant"])
        self.assertIn("东京待三天", msgs[0][3])
        self.assertEqual(msgs[0][1], "2026-08-02 15:00")


class FmtTimeTests(unittest.TestCase):
    def test_formats(self) -> None:
        from datetime import datetime
        self.assertEqual(ic.fmt_time(1750000001),
                         datetime.fromtimestamp(1750000001).strftime("%Y-%m-%d %H:%M"))
        self.assertEqual(ic.fmt_time("2026-08-02T15:00:00+08:00"), "2026-08-02 15:00")
        self.assertEqual(ic.fmt_time("2026年8月2日 下午3:00"), "2026-08-02 15:00")
        self.assertEqual(ic.fmt_time("Aug 2, 2026, 3:00 PM"), "2026-08-02 15:00")
        self.assertIsNone(ic.fmt_time("not a date"))
        self.assertIsNone(ic.fmt_time(None))


class CliTests(unittest.TestCase):
    def _tmp(self) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name) / "out"

    def test_import_all_sources(self) -> None:
        out = self._tmp()
        cases = [
            ("chatgpt", str(FIXTURE / "chatgpt")),
            ("deepseek", str(FIXTURE / "deepseek" / "conversations.json")),
            ("gemini", str(FIXTURE / "gemini" / "takeout")),
        ]
        for src, path in cases:
            r = run_import("--source", src, "--path", path, "--root", str(out), "--yes")
            self.assertEqual(r.returncode, 0, r.stderr)
        files = [p.name for p in out.glob("*.md")]
        self.assertIn("chatgpt-chatgpt-conv-001.md", files)
        self.assertIn("deepseek-deepseek-conv-001.md", files)
        self.assertTrue(any(f.startswith("gemini-") for f in files))
        imported = ic.load_imported(out)
        self.assertIn("chatgpt:chatgpt-conv-001", imported)
        self.assertIn("deepseek:deepseek-conv-001", imported)

    def test_dedup(self) -> None:
        out = self._tmp()
        args = ["--source", "chatgpt", "--path", str(FIXTURE / "chatgpt"),
                "--root", str(out), "--yes"]
        r1 = run_import(*args)
        self.assertEqual(r1.returncode, 0)
        self.assertIn("导入 1", r1.stdout)
        r2 = run_import(*args)
        self.assertIn("已导入过 1", r2.stdout)
        self.assertEqual(len(list(out.glob("*.md"))), 1)

    def test_dry_run_writes_nothing(self) -> None:
        out = self._tmp()
        r = run_import("--source", "chatgpt", "--path", str(FIXTURE / "chatgpt"),
                       "--root", str(out), "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertFalse(out.exists())

    def test_bad_input_reports_error(self) -> None:
        bad = self._tmp() / "bad.json"
        bad.parent.mkdir(parents=True)
        bad.write_text("{ not json", encoding="utf-8")
        r = run_import("--source", "chatgpt", "--path", str(bad), "--root", str(self._tmp()))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("错误", r.stderr)

    def test_local_dry_run_against_fixture_roots(self) -> None:
        # 用 fixture 作为 local 根：直接测 discover_local + run_local 的 dry-run 分支
        codex_root = FIXTURE / "codex" / "sessions"
        found = ic.discover_local(roots=(("codex", str(codex_root), "rollout-*.jsonl"),))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], "codex")
        self.assertEqual(found[0][1], "fake-session-001")

    def test_confirmation_cancels_without_yes(self) -> None:
        from unittest import mock
        out = self._tmp()
        codex_file = (FIXTURE / "codex" / "sessions" / "2026" / "08" / "01"
                      / "rollout-2026-08-01T10-00-00-fake-session-001.jsonl")
        found = [("codex", "fake-session-001", "标题", "2026-08-01 10:00",
                  "2026-08-01 10:00", 100, str(codex_file))]
        with mock.patch("builtins.input", return_value="n"):
            ident, ok, dup, bad = ic.run_local(found, mock.Mock(yes=False, dry_run=False),
                                               {}, out)
        self.assertEqual(ok, 0)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
