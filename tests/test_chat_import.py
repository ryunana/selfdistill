from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import import_chats as ic  # noqa: E402

FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "chat-import"


def run_import(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "import_chats.py", *args],
                          capture_output=True, text=True, cwd=str(PROJECT_ROOT))


class ParserTests(unittest.TestCase):
    def test_chatgpt_branch_excluded(self) -> None:
        convs, skipped, total = ic.parse_chatgpt(FIXTURE / "chatgpt")
        self.assertEqual(total, 1)
        self.assertEqual(len(convs), 1)
        _src, cid, title, _exp, msgs = convs[0]
        self.assertEqual((cid, title), ("chatgpt-conv-001", "虚构聊天：咖啡豆选择"))
        self.assertEqual(len(msgs), 3)  # m1/m2/m3；重写分支 m3b 被忽略
        self.assertIn("手冲咖啡", msgs[0][3])
        self.assertIn("滤杯", msgs[2][3])
        self.assertFalse(any("重写分支" in m[3] for m in msgs))

    def test_chatgpt_empty_conversation_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "conversations-000.json"
            p.write_text(json.dumps([{"id": "x", "title": "空会话", "mapping": {"root": {"id": "root", "message": None}}}]),
                         encoding="utf-8")
            convs, skipped, total = ic.parse_chatgpt(p)
            self.assertEqual(convs, [])
            self.assertEqual(total, 1)
            self.assertEqual(skipped[0][1], ic.SKIP_EMPTY)

    def test_deepseek_thinking_default_excluded(self) -> None:
        ic._INCLUDE_THINKING = False
        try:
            convs, skipped, total = ic.parse_deepseek(FIXTURE / "deepseek" / "conversations.json")
            self.assertEqual(total, 1)
            self.assertEqual(len(convs), 1)
            msgs = convs[0][4]
            self.assertNotIn("<!-- thinking -->", msgs[1][3])
            self.assertIn("[附件: trail-map.png]", msgs[1][3])
        finally:
            ic._INCLUDE_THINKING = False

    def test_deepseek_thinking_with_flag(self) -> None:
        ic._INCLUDE_THINKING = True
        try:
            convs, _s, _t = ic.parse_deepseek(FIXTURE / "deepseek" / "conversations.json")
            self.assertIn("<!-- thinking -->", convs[0][4][1][3])
        finally:
            ic._INCLUDE_THINKING = False

    def test_deepseek_tool_fragments_aggregated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "conversations.json"
            data = [{"id": "c1", "title": "带搜索", "mapping": {
                "1": {"id": "1", "message": {"inserted_at": "2026-08-01T09:00:00+08:00",
                                             "fragments": [{"type": "REQUEST", "content": "你好"}]}, "parent": None, "children": []},
                "2": {"id": "2", "message": {"inserted_at": "2026-08-01T09:00:01+08:00",
                                             "fragments": [{"type": "TOOL_SEARCH"}, {"type": "SEARCH", "content": "结果"}]}, "parent": "1", "children": []},
            }}]
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            convs, skipped, total = ic.parse_deepseek(p)
            self.assertEqual(len(convs), 1)
            self.assertIn("工具片段 2 条", skipped[0][1])

    def test_codex_cleans_system_blocks(self) -> None:
        convs = ic.parse_codex(FIXTURE / "codex" / "sessions" / "2026" / "08" / "01"
                               / "rollout-2026-08-01T10-00-00-fake-session-001.jsonl")
        self.assertIsNotNone(convs)
        _src, cid, title, _exp, msgs = convs[0]
        self.assertEqual(cid, "fake-session-001")
        self.assertIn("帮我写个 Python 脚本", title)
        self.assertNotIn("environment_context", msgs[0][3])
        self.assertEqual(msgs[0][2], "u1")  # 真实 payload id 保留

    def test_codex_adversarial_cleaning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-x.jsonl"
            lines = [
                '{"timestamp": "2026-08-01T10:00:00Z", "type": "session_meta", "payload": {"id": "adv"}}',
                '{"timestamp": "2026-08-01T10:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "id": "u1", "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /\n<INSTRUCTIONS>平台规则</INSTRUCTIONS><environment_context><cwd>/x</cwd></environment_context>"}]}}',
                '{"timestamp": "2026-08-01T10:00:02Z", "type": "response_item", "payload": {"type": "message", "role": "user", "id": "u2", "content": [{"type": "input_text", "text": "Automation: Personal context daily observer\n<root>...</root>"}]}}',
                '{"timestamp": "2026-08-01T10:00:03Z", "type": "response_item", "payload": {"type": "message", "role": "user", "id": "u3", "content": [{"type": "input_text", "text": "<image name=[Image #1] path=/tmp/a.png></image>真的用户提问"}]}}',
                '{"timestamp": "2026-08-01T10:00:04Z", "type": "response_item", "payload": {"type": "message", "role": "assistant", "id": "a1", "content": [{"type": "output_text", "text": "回答"}]}}',
            ]
            p.write_text("\n".join(lines), encoding="utf-8")
            convs = ic.parse_codex(p)
            self.assertIsNotNone(convs)
            msgs = convs[0][4]
            texts = [m[3] for m in msgs if m[0] == "user"]
            self.assertEqual(len(texts), 1)  # u1 被清空、u2 Automation 被丢弃，仅 u3 保留
            self.assertIn("真的用户提问", texts[0])
            self.assertIn("[图片]", texts[0])

    def test_claude_skips_cli_lines(self) -> None:
        convs = ic.parse_claude(FIXTURE / "claude" / "projects" / "-tmp"
                                / "fake-claude-session-001.jsonl")
        self.assertIsNotNone(convs)
        _src, cid, _title, _exp, msgs = convs[0]
        self.assertEqual(cid, "fake-claude-session-001")
        self.assertEqual(len(msgs), 2)  # claude --resume 行被跳过
        self.assertEqual(msgs[0][2], "cu1")

    def test_gemini_real_structure(self) -> None:
        convs, skipped, total = ic.parse_gemini(FIXTURE / "gemini" / "takeout")
        self.assertEqual(len(convs), 1)
        _src, _cid, _title, _exp, msgs = convs[0]
        self.assertEqual([m[0] for m in msgs], ["user", "assistant"])
        self.assertEqual(msgs[0][1], "2026-08-02 15:00")
        self.assertIn("东京待三天", msgs[0][3])


class FmtTimeTests(unittest.TestCase):
    def test_formats(self) -> None:
        self.assertEqual(ic.fmt_time(1750000001),
                         datetime.fromtimestamp(1750000001).strftime("%Y-%m-%d %H:%M"))
        self.assertEqual(ic.fmt_time("2026-08-02T15:00:00+08:00"), "2026-08-02 15:00")
        self.assertEqual(ic.fmt_time("2026年8月2日 下午3:00"), "2026-08-02 15:00")
        self.assertEqual(ic.fmt_time("2026年6月3日 21:52:40 CST"), "2026-06-03 21:52")
        self.assertEqual(ic.fmt_time("Aug 2, 2026, 3:00 PM"), "2026-08-02 15:00")
        self.assertIsNone(ic.fmt_time("not a date"))
        self.assertIsNone(ic.fmt_time(None))


class CliTests(unittest.TestCase):
    def _tmp(self) -> Path:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        return Path(td.name) / "out"

    def test_import_all_sources_and_perms(self) -> None:
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
        # 权限：目录 0700、文件 0600
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o700)
        for f in out.glob("*.md"):
            self.assertEqual(os.stat(f).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(ic.imported_path(out)).st_mode & 0o777, 0o600)

    def test_incremental_dedup_appends_new_messages(self) -> None:
        out = self._tmp()
        src = Path(tempfile.mkdtemp()) / "conversations-000.json"
        conv = {"id": "inc", "title": "增量", "current_node": "m2", "mapping": {
            "root": {"id": "root", "message": None, "parent": None, "children": ["m1"]},
            "m1": {"id": "m1", "message": {"id": "m1", "author": {"role": "user"}, "content": {"parts": ["[SIMULATED] 你好"]}, "create_time": 1750000001}, "parent": "root", "children": ["m2"]},
            "m2": {"id": "m2", "message": {"id": "m2", "author": {"role": "assistant"}, "content": {"parts": ["[SIMULATED] 你好！"]}, "create_time": 1750000002}, "parent": "m1", "children": []},
        }}
        src.write_text(json.dumps([conv], ensure_ascii=False), encoding="utf-8")
        r1 = run_import("--source", "chatgpt", "--path", str(src), "--root", str(out), "--yes")
        self.assertIn("导入 1", r1.stdout)
        conv["mapping"]["m3"] = {"id": "m3", "message": {"id": "m3", "author": {"role": "user"}, "content": {"parts": ["[SIMULATED] 新问题"]}, "create_time": 1750000003}, "parent": "m2", "children": []}
        conv["mapping"]["m2"]["children"] = ["m3"]
        conv["current_node"] = "m3"
        src.write_text(json.dumps([conv], ensure_ascii=False), encoding="utf-8")
        r2 = run_import("--source", "chatgpt", "--path", str(src), "--root", str(out), "--yes")
        content = (out / "chatgpt-inc.md").read_text(encoding="utf-8")
        self.assertIn("新问题", content)
        self.assertEqual(content.count("**user**"), 2)  # m1 + m3，旧消息未重复
        self.assertEqual(content.count("**assistant**"), 1)  # m2

    def test_dedup_no_new_messages(self) -> None:
        out = self._tmp()
        args = ["--source", "chatgpt", "--path", str(FIXTURE / "chatgpt"),
                "--root", str(out), "--yes"]
        run_import(*args)
        r2 = run_import(*args)
        self.assertIn("已导入过", r2.stdout)

    def test_dry_run_semantics(self) -> None:
        out = self._tmp()
        r = run_import("--source", "chatgpt", "--path", str(FIXTURE / "chatgpt"),
                       "--root", str(out), "--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("dry-run", r.stdout)
        self.assertFalse(out.exists())

    def test_bad_input_reports_error(self) -> None:
        bad = Path(tempfile.mkdtemp()) / "conversations-000.json"
        bad.write_text("{ not json", encoding="utf-8")
        r = run_import("--source", "chatgpt", "--path", str(bad), "--root", str(self._tmp()))
        self.assertEqual(r.returncode, 0)
        self.assertIn("损坏", r.stdout)  # 诚实报告：坏文件计入跳过，不静默

    def test_local_dry_run_fixture_roots(self) -> None:
        codex_root = FIXTURE / "codex" / "sessions"
        found = ic.discover_local(roots=(("codex", str(codex_root), "rollout-*.jsonl"),))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][1], "fake-session-001")

    def test_confirmation_cancels_without_yes(self) -> None:
        out = self._tmp()
        codex_file = (FIXTURE / "codex" / "sessions" / "2026" / "08" / "01"
                      / "rollout-2026-08-01T10-00-00-fake-session-001.jsonl")
        found = [("codex", "fake-session-001", "标题", "2026-08-01 10:00",
                  "2026-08-01 10:00", 100, str(codex_file))]
        with unittest.mock.patch("builtins.input", return_value="n"):
            ident, ok, dup, bad = ic.run_local(found, unittest.mock.Mock(yes=False, dry_run=False),
                                                  {}, out)
        self.assertEqual(ok, 0)
        self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
