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
    def test_path_helper_rejects_cycles_and_parent_child_mismatch(self) -> None:
        with self.assertRaises(ic.ImportError_):
            ic._root_to_leaf_paths({
                "a": {"parent": "b", "children": ["b"]},
                "b": {"parent": "a", "children": ["a"]},
            })
        with self.assertRaises(ic.ImportError_):
            ic._root_to_leaf_paths({
                "root": {"parent": None, "children": ["a"]},
                "a": {"parent": None, "children": []},
            })
        with self.assertRaises(ic.ImportError_):
            ic._root_to_leaf_paths({
                "root": {"parent": None, "children": []},
                "a": {"parent": "root", "children": []},
            })

    def test_chatgpt_missing_current_node_splits_leaf_paths_and_redacts_parts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "conversations-000.json"
            conv = {"id": "cg", "title": "分支", "current_node": "missing", "mapping": {
                "root": {"id": "root", "parent": None, "children": ["u"]},
                "u": {"id": "u", "parent": "root", "children": ["a", "b"], "message": {
                    "id": "u", "author": {"role": "user"}, "create_time": 1,
                    "content": {"parts": ["正文", {"asset_pointer": "private://asset", "width": 9}, {"opaque": "no"}]}}},
                "a": {"id": "a", "parent": "u", "children": [], "message": {"id": "a", "author": {"role": "assistant"}, "create_time": 2, "content": {"parts": ["A"]}}},
                "b": {"id": "b", "parent": "u", "children": [], "message": {"id": "b", "author": {"role": "assistant"}, "create_time": 3, "content": {"parts": ["B"]}}},
            }}
            p.write_text(json.dumps([conv], ensure_ascii=False), encoding="utf-8")
            convs, skipped, _total = ic.parse_chatgpt(p)
            self.assertEqual(len(convs), 2)
            self.assertEqual(len({c[1] for c in convs}), 2)
            self.assertEqual({c[1] for c in convs}, {"cg--branch-" + c[1].split("--branch-")[1] for c in convs})
            user_text = convs[0][4][0][3]
            self.assertIn("[图片]", user_text)
            self.assertIn("[未识别附件]", user_text)
            self.assertNotIn("asset_pointer", user_text)
            self.assertNotIn("{'", user_text)
            self.assertTrue(any("未识别附件" in reason for _ref, reason in skipped))

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
                                             "fragments": [{"type": "REQUEST", "content": "你好"}]}, "parent": None, "children": ["2"]},
                "2": {"id": "2", "message": {"inserted_at": "2026-08-01T09:00:01+08:00",
                                             "fragments": [{"type": "TOOL_SEARCH"}, {"type": "SEARCH", "content": "结果"}]}, "parent": "1", "children": []},
            }}]
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            convs, skipped, total = ic.parse_deepseek(p)
            self.assertEqual(len(convs), 1)
            self.assertIn("工具片段 2 条", skipped[0][1])

    def test_deepseek_branches_are_separate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "conversations.json"
            data = [{"id": "d", "title": "分支", "mapping": {
                "root": {"id": "root", "parent": None, "children": ["u"], "message": None},
                "u": {"id": "u", "parent": "root", "children": ["a", "tool"], "message": {"fragments": [{"type": "REQUEST", "content": "问题"}]}},
                "a": {"id": "a", "parent": "u", "children": [], "message": {"fragments": [{"type": "RESPONSE", "content": "回答 A"}]}},
                "tool": {"id": "tool", "parent": "u", "children": ["b"], "message": {"fragments": [{"type": "TOOL_SEARCH", "content": "x"}]}},
                "b": {"id": "b", "parent": "tool", "children": [], "message": {"fragments": [{"type": "RESPONSE", "content": "回答 B"}]}},
            }}]
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            convs, _skipped, _total = ic.parse_deepseek(p)
            self.assertEqual(len(convs), 2)
            bodies = ["\n".join(m[3] for m in c[4]) for c in convs]
            self.assertTrue(any("回答 A" in b and "回答 B" not in b for b in bodies))
            self.assertTrue(any("回答 B" in b and "回答 A" not in b for b in bodies))
            self.assertTrue(all("--branch-" in c[1] for c in convs))

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

    def test_codex_preserves_user_xml_but_removes_known_envelopes(self) -> None:
        user = ("<name>Ada</name><path>/safe</path><string>keep</string><prompt>keep too</prompt>\n"
                "<environment_context><cwd>/private</cwd></environment_context>\n"
                "真实正文")
        cleaned = ic._clean_codex_user(user)
        self.assertIn("<name>Ada</name>", cleaned)
        self.assertIn("<path>/safe</path>", cleaned)
        self.assertIn("<string>keep</string>", cleaned)
        self.assertIn("<prompt>keep too</prompt>", cleaned)
        self.assertNotIn("environment_context", cleaned)

    def test_codex_repeated_leading_wrappers_and_prefix_records_are_dropped(self) -> None:
        nested = ("<environment_context><cwd>/one</cwd></environment_context>\n"
                  "# AGENTS.md instructions for /\n<INSTRUCTIONS>internal</INSTRUCTIONS>\n"
                  "<recommended_plugins><plugin>x</plugin></recommended_plugins>\n"
                  "<environment_context><cwd>/two</cwd></environment_context>")
        self.assertEqual(ic._clean_codex_user(nested), "")
        self.assertEqual(ic._clean_codex_user("# Files mentioned by the user:\n<path>/x</path>"), "")
        self.assertEqual(ic._clean_codex_user("# In app browser:\n<url>http://x</url>"), "")
        ordinary = "用户说：# Files mentioned by the user: 只是一个字符串"
        self.assertEqual(ic._clean_codex_user(ordinary), ordinary)

    def test_claude_excludes_internal_records_not_marker_mentions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            records = [
                {"type": "user", "uuid": "meta", "isMeta": True, "message": {"role": "user", "content": "meta"}},
                {"type": "assistant", "uuid": "side", "isSidechain": True, "message": {"role": "assistant", "content": "side"}},
                {"type": "user", "uuid": "cmd", "message": {"role": "user", "content": "<command-name>build</command-name>"}},
                {"type": "user", "uuid": "real", "message": {"role": "user", "content": "代码提到了 command-name，别删除。"}},
            ]
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
            convs = ic.parse_claude(p)
            self.assertEqual([m[2] for m in convs[0][4]], ["real"])

    def test_claude_excludes_complete_internal_wrapper_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            records = [
                {"type": "user", "uuid": "commands", "message": {"role": "user", "content": (
                    "<command-name>build</command-name>\n<command-message>run</command-message>\n<command-args>--fast</command-args>")}},
                {"type": "user", "uuid": "task", "message": {"role": "user", "content": (
                    "<task-notification><task-id>x</task-id><tool-use-id>y</tool-use-id><output-file>/tmp/z</output-file><status>done</status><summary>ok</summary></task-notification>")}},
                {"type": "user", "uuid": "real", "message": {"role": "user", "content": "我提到了 command-args，但这是真实问题。"}},
            ]
            p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in records), encoding="utf-8")
            convs = ic.parse_claude(p)
            self.assertEqual([m[2] for m in convs[0][4]], ["real"])

    def test_local_parsers_report_internal_exclusions_and_unknown_records(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex = root / "rollout-report.jsonl"
            codex.write_text("\n".join([
                json.dumps({"type": "session_meta", "payload": {"id": "report"}}),
                "{ bad json",
                json.dumps({"timestamp": "2026-08-01T10:00:00Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# Files mentioned by the user:\n<path>/x</path>"}]}}),
                json.dumps({"timestamp": "2026-08-01T10:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "普通文字提到 # Files mentioned by the user:"}]}}),
            ]), encoding="utf-8")
            codex_events = []
            codex_convs = ic.parse_codex(codex, codex_events)
            self.assertIn("普通文字提到", codex_convs[0][4][0][3])
            self.assertTrue(any(reason.startswith("内部内容已排除") for reason in codex_events))
            self.assertTrue(any(reason.startswith("损坏 JSONL 行") for reason in codex_events))

            claude = root / "claude-report.jsonl"
            claude.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in [
                {"type": "user", "isMeta": True, "message": {"role": "user", "content": "meta"}},
                {"type": "assistant", "isSidechain": True, "message": {"role": "assistant", "content": "side"}},
                {"type": "user", "message": {"role": "user", "content": "claude --resume x"}},
                {"type": "user", "message": {"role": "user", "content": "<command-name>x</command-name>"}},
                {"type": "future-internal", "payload": {"x": 1}},
                {"type": "user", "uuid": "real", "message": {"role": "user", "content": "普通文本提到 command-name"}},
            ]), encoding="utf-8")
            claude_events = []
            claude_convs = ic.parse_claude(claude, claude_events)
            self.assertEqual([m[2] for m in claude_convs[0][4]], ["real"])
            self.assertGreaterEqual(sum(reason.startswith("内部内容已排除") for reason in claude_events), 4)
            self.assertTrue(any(reason.startswith("未知内部记录告警") for reason in claude_events))

    def test_claude_known_top_level_internal_types_are_expected_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "known-types.jsonl"
            known_types = [
                "system", "mode", "permission-mode", "file-history-snapshot",
                "ai-title", "last-prompt", "attachment", "queue-operation",
            ]
            records = [{"type": record_type, "payload": {}} for record_type in known_types]
            records += [
                {"type": "future-internal", "payload": {}},
                {"type": "user", "uuid": "real", "message": {"role": "user", "content": "真实内容"}},
            ]
            p.write_text("\n".join(json.dumps(record) for record in records), encoding="utf-8")
            events = []
            convs = ic.parse_claude(p, events)
            self.assertEqual([m[2] for m in convs[0][4]], ["real"])
            expected = [reason for reason in events if reason.startswith("内部内容已排除")]
            unknown = [reason for reason in events if reason.startswith("未知内部记录告警")]
            self.assertEqual(len(expected), len(known_types))
            self.assertEqual(len(unknown), 1)
            self.assertIn("future-internal", unknown[0])

    def test_claude_known_content_blocks_are_expected_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "content-blocks.jsonl"
            records = [
                {"type": "user", "message": {"role": "user", "content": [{"type": "tool_use", "id": "x"}]}},
                {"type": "assistant", "uuid": "mixed", "message": {"role": "assistant", "content": [
                    {"type": "text", "text": "可见回答"}, {"type": "thinking", "thinking": "内部"},
                    {"type": "tool_result", "content": "内部结果"},
                ]}},
                {"type": "user", "message": {"role": "user", "content": [{"type": "future-block", "x": 1}]}},
                {"type": "user", "uuid": "real", "message": {"role": "user", "content": "真实问题"}},
            ]
            p.write_text("\n".join(json.dumps(record, ensure_ascii=False) for record in records), encoding="utf-8")
            events = []
            convs = ic.parse_claude(p, events)
            self.assertEqual([m[2] for m in convs[0][4]], ["mixed", "real"])
            self.assertEqual(convs[0][4][0][3], "可见回答")
            self.assertEqual(sum(reason.startswith("内部内容已排除") for reason in events), 3)
            self.assertEqual(sum(reason.startswith("未知内部记录告警") for reason in events), 1)

    def test_claude_image_content_block_uses_safe_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "images.jsonl"
            p.write_text(json.dumps({"type": "user", "uuid": "image", "message": {"role": "user", "content": [
                {"type": "text", "text": "请看图片"},
                {"type": "image", "source": {"type": "base64", "data": "private-image-bytes"}},
            ]}}, ensure_ascii=False), encoding="utf-8")
            events = []
            convs = ic.parse_claude(p, events)
            text = convs[0][4][0][3]
            self.assertIn("请看图片", text)
            self.assertIn("[图片]", text)
            self.assertNotIn("source", text)
            self.assertNotIn("private-image-bytes", text)
            self.assertFalse(any(reason.startswith("未知内部记录告警") for reason in events))

    def test_missing_local_ids_are_occurrence_unique_and_stable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex = root / "rollout-no-ids.jsonl"
            codex.write_text("\n".join([
                json.dumps({"type": "session_meta", "payload": {"id": "codex-no-ids"}}),
                json.dumps({"timestamp": "2026-08-01T10:00:00Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "repeat"}]}}),
                json.dumps({"timestamp": "2026-08-01T10:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "repeat"}]}}),
            ]), encoding="utf-8")
            first = ic.parse_codex(codex)[0]
            second = ic.parse_codex(codex)[0]
            self.assertEqual([m[2] for m in first[4]], [m[2] for m in second[4]])
            self.assertEqual(len({m[2] for m in first[4]}), 2)
            out = root / "out"
            imported = {}
            self.assertEqual(ic.write_conversation(first, imported, out), "new")
            self.assertEqual(ic.write_conversation(second, imported, out), "dup")

            claude = root / "claude-no-ids.jsonl"
            claude.write_text("\n".join(json.dumps(r) for r in [
                {"type": "user", "timestamp": "2026-08-01T11:00:00Z", "message": {"role": "user", "content": "repeat"}},
                {"type": "user", "timestamp": "2026-08-01T11:00:01Z", "message": {"role": "user", "content": "repeat"}},
            ]), encoding="utf-8")
            claude_first = ic.parse_claude(claude)[0]
            claude_second = ic.parse_claude(claude)[0]
            self.assertEqual([m[2] for m in claude_first[4]], [m[2] for m in claude_second[4]])
            self.assertEqual(len({m[2] for m in claude_first[4]}), 2)
            self.assertEqual(ic.write_conversation(claude_first, imported, out), "new")
            self.assertEqual(ic.write_conversation(claude_second, imported, out), "dup")

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

    def test_gemini_activity_container_keeps_data_nodes_separate(self) -> None:
        convs, _skipped, total = ic.parse_gemini(FIXTURE / "gemini" / "activity-container.html")
        self.assertEqual((total, len(convs)), (1, 1))
        msgs = convs[0][4]
        self.assertEqual([m[0] for m in msgs], ["user", "assistant"])
        self.assertEqual({m[1] for m in msgs}, {"2026-08-03 16:05"})
        self.assertIn("[附件: map.pdf]", msgs[0][3])
        self.assertIn("第一天先去博物馆", msgs[1][3])
        self.assertNotIn("Gemini Apps", "\n".join(m[3] for m in msgs))

    def test_gemini_prompt_date_lines_are_not_activity_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<html><body><div class='outer-cell'>
<div>Gemini Apps</div><div>Prompted：</div>
<div>2026年8月1日 上午9:00</div><div>2026年8月2日 下午3:00</div>
<div>请比较这两个时间安排。</div><div>2026年8月3日 下午4:05</div>
<div>可以先处理第一项。</div></div></body></html>""", encoding="utf-8")
            convs, _skipped, total = ic.parse_gemini(p)
            self.assertEqual((total, len(convs)), (1, 1))
            msgs = convs[0][4]
            self.assertEqual({m[1] for m in msgs}, {"2026-08-03 16:05"})
            self.assertIn("2026年8月1日 上午9:00", msgs[0][3])
            self.assertIn("2026年8月2日 下午3:00", msgs[0][3])
            self.assertIn("可以先处理第一项", msgs[1][3])

    def test_gemini_splits_prompted_activities_with_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<html><body>
<div class='outer-cell'><div>2026年8月1日 下午3:00</div><div>Prompted：重复问题</div></div>
<div class='outer-cell'><div>2026年8月1日 下午3:01</div><div>Gemini：第一个回答</div></div>
<div class='outer-cell'><div>2026年8月2日 下午3:00</div><div>Prompted：重复问题</div><div>Attached 1 files.</div><div>a.pdf</div></div>
<div class='outer-cell'><div>2026年8月2日 下午3:01</div><div>Gemini：第二个回答</div></div>
</body></html>""", encoding="utf-8")
            convs, _skipped, total = ic.parse_gemini(p)
            self.assertEqual((total, len(convs)), (2, 2))
            self.assertNotEqual(convs[0][1], convs[1][1])
            self.assertEqual(convs[0][4][0][1], "2026-08-01 15:00")
            self.assertIn("[附件: a.pdf]", convs[1][4][0][3])

    def test_gemini_identical_activity_keys_get_stable_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            block = "<div class='outer-cell'><div>Gemini Apps</div><div>Prompted：同一个问题</div><div>2026年8月3日 下午4:05</div><div>同一个回答</div></div>"
            p.write_text(f"<html><body>{block}{block}</body></html>", encoding="utf-8")
            first, _skipped, total = ic.parse_gemini(p)
            second, _skipped, _total = ic.parse_gemini(p)
            self.assertEqual((total, len(first)), (2, 2))
            self.assertEqual([c[1] for c in first], [c[1] for c in second])
            self.assertEqual(len({c[1] for c in first}), 2)


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

    def test_crlf_message_is_rendered_once_and_then_duplicate(self) -> None:
        out = self._tmp()
        conv = ("chatgpt", "crlf", "标题", "2026-08-01", [
            ("user", "2026-08-01 10:00", "u", "第一行\r\n第二行"),
        ])
        imported = {}
        self.assertEqual(ic.write_conversation(conv, imported, out), "new")
        self.assertEqual(ic.write_conversation(conv, imported, out), "dup")
        raw = (out / "chatgpt-crlf.md").read_bytes()
        self.assertNotIn(b"\r", raw)
        self.assertIn("第一行\n第二行".encode("utf-8"), raw)

    def test_filename_sanitization_collision_fails_closed_in_batch_and_without_state(self) -> None:
        out = self._tmp()
        first = ("chatgpt", "a/b", "第一", "2026-08-01", [("user", None, "u1", "第一条")])
        second = ("chatgpt", "a?b", "第二", "2026-08-01", [("user", None, "u2", "第二条")])
        total, _outputs, new, updated, dup, skipped = ic.import_convs(
            [first, second], [], 2, {}, out, dry_run=False)
        self.assertEqual((total, new, updated, dup), (2, 1, 0, 0))
        self.assertEqual(len(skipped), 1)
        self.assertIn("文件名冲突", skipped[0][1])
        path = out / "chatgpt-a-b.md"
        self.assertIn("第一条", path.read_text(encoding="utf-8"))
        self.assertNotIn("第二条", path.read_text(encoding="utf-8"))

        dry_out = out.parent / "dry-out"
        _total, _outputs, dry_new, _updated, _dup, dry_skipped = ic.import_convs(
            [first, second], [], 2, {}, dry_out, dry_run=True)
        self.assertEqual(dry_new, 1)
        self.assertEqual(len(dry_skipped), 1)
        self.assertFalse(dry_out.exists())

        # Interrupted state writes must not let a colliding header be overwritten.
        with self.assertRaisesRegex(ic.ImportError_, "文件名冲突"):
            ic.write_conversation(second, {}, out)
        self.assertIn("第一条", path.read_text(encoding="utf-8"))

        # A managed block alone does not establish ownership and must not be overwritten.
        unowned = out.parent / "unowned"
        unowned.mkdir()
        unowned_path = unowned / "chatgpt-a-b.md"
        original = "<!-- distill-messages:begin -->\n旧正文\n<!-- distill-messages:end -->\n"
        unowned_path.write_text(original, encoding="utf-8")
        with self.assertRaisesRegex(ic.ImportError_, "所有权元数据"):
            ic.write_conversation(first, {}, unowned)
        self.assertEqual(unowned_path.read_text(encoding="utf-8"), original)

    def test_duplicate_restores_permissions_but_dry_run_is_write_free(self) -> None:
        out = self._tmp()
        conv = ("chatgpt", "private", "标题", "2026-08-01", [("user", None, "u", "正文")])
        imported = {}
        self.assertEqual(ic.write_conversation(conv, imported, out), "new")
        path = out / "chatgpt-private.md"
        os.chmod(out, 0o755)
        os.chmod(path, 0o644)
        self.assertEqual(ic.write_conversation(conv, imported, out), "dup")
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o700)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
        os.chmod(out, 0o755)
        os.chmod(path, 0o644)
        self.assertEqual(ic.write_conversation(conv, imported, out, dry_run=True), "dup")
        self.assertEqual(os.stat(out).st_mode & 0o777, 0o755)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o644)

    def test_atomic_write_forces_tmp_permissions_before_replace(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "private.md"
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text("old", encoding="utf-8")
            os.chmod(tmp, 0o777)
            with unittest.mock.patch("os.fchmod", wraps=os.fchmod) as fchmod:
                ic._atomic_write(path, "new")
            self.assertTrue(any(call.args[1] == 0o600 for call in fchmod.call_args_list))
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)

    def test_writer_rebuilds_changed_branch_and_recovers_state_from_markdown(self) -> None:
        out = self._tmp()
        first = ("chatgpt", "branch", "标题", "2026-08-01", [
            ("user", "2026-08-01 10:00", "u", "问题"),
            ("assistant", "2026-08-01 10:01", "a", "旧回答"),
        ])
        imported = {}
        self.assertEqual(ic.write_conversation(first, imported, out), "new")
        path = out / "chatgpt-branch.md"
        path.write_text("手工前言\n" + path.read_text(encoding="utf-8") + "\n手工尾注\n", encoding="utf-8")
        changed = ("chatgpt", "branch", "标题", "2026-08-01", [
            ("user", "2026-08-01 10:00", "u", "问题"),
            ("assistant", "2026-08-01 10:01", "b", "新回答"),
        ])
        recovered = {}
        self.assertEqual(ic.write_conversation(changed, recovered, out), "update")
        content = path.read_text(encoding="utf-8")
        self.assertIn("手工前言", content)
        self.assertIn("手工尾注", content)
        self.assertNotIn("旧回答", content)
        self.assertEqual(recovered["chatgpt:branch"]["message_ids"], ["u", "b"])

    def test_writer_rejects_corrupt_markers_and_duplicate_ids(self) -> None:
        out = self._tmp()
        out.mkdir()
        p = out / "chatgpt-x.md"
        p.write_text("<!-- distill-messages:begin -->\n坏文件", encoding="utf-8")
        conv = ("chatgpt", "x", "标题", "2026-08-01", [("user", None, "same", "一")])
        with self.assertRaises(ic.ImportError_):
            ic.write_conversation(conv, {}, out)
        duplicate = ("chatgpt", "dup", "标题", "2026-08-01", [
            ("user", None, "same", "一"), ("assistant", None, "same", "二")])
        with self.assertRaises(ic.ImportError_):
            ic.write_conversation(duplicate, {}, out)

    def test_corrupt_imported_state_fails_closed(self) -> None:
        out = self._tmp()
        out.mkdir()
        ic.imported_path(out).write_text("{bad", encoding="utf-8")
        r = run_import("--source", "chatgpt", "--path", str(FIXTURE / "chatgpt"),
                       "--root", str(out), "--yes")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(ic.imported_path(out).read_text(encoding="utf-8"), "{bad")

    def test_imported_state_rejects_malformed_entries_without_rewriting(self) -> None:
        cases = [
            {"broken": 1},
            {":cid": {"path": "x.md", "imported_at": "2026-08-01", "title": "x", "message_ids": []}},
            {"chatgpt:": {"path": "x.md", "imported_at": "2026-08-01", "title": "x", "message_ids": []}},
            {"chatgpt:x": {"path": 3, "imported_at": "2026-08-01", "title": "x", "message_ids": []}},
            {"chatgpt:x": {"path": "x.md", "imported_at": "2026-08-01", "title": "x", "message_ids": ["m", "m"]}},
        ]
        for data in cases:
            with self.subTest(data=data), tempfile.TemporaryDirectory() as td:
                out = Path(td)
                raw = json.dumps(data, ensure_ascii=False)
                ic.imported_path(out).write_text(raw, encoding="utf-8")
                with self.assertRaises(ic.ImportError_):
                    ic.load_imported(out)
                self.assertEqual(ic.imported_path(out).read_text(encoding="utf-8"), raw)

    def test_next_run_rebuilds_missing_state_from_existing_markdown(self) -> None:
        out = self._tmp()
        args = ["--source", "chatgpt", "--path", str(FIXTURE / "chatgpt"),
                "--root", str(out), "--yes"]
        self.assertEqual(run_import(*args).returncode, 0)
        ic.imported_path(out).unlink()  # simulate interruption after Markdown replacement
        rerun = run_import(*args)
        self.assertEqual(rerun.returncode, 0, rerun.stderr)
        self.assertIn("重复 1", rerun.stdout)
        restored = ic.load_imported(out)
        self.assertIn("chatgpt:chatgpt-conv-001", restored)

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
        self.assertEqual(r.returncode, 1)
        self.assertIn("损坏", r.stdout)  # 诚实报告：坏文件计入跳过，不静默

    def test_empty_chatgpt_and_deepseek_exports_fail_with_no_messages(self) -> None:
        for source, filename in (("chatgpt", "conversations-000.json"),
                                 ("deepseek", "conversations.json")):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as td:
                export = Path(td) / filename
                export.write_text("[]", encoding="utf-8")
                r = run_import("--source", source, "--path", str(export),
                               "--root", str(self._tmp()), "--yes")
                self.assertEqual(r.returncode, 1, r.stderr)
                self.assertIn("无消息", r.stdout)

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
            ident, outputs, new, updated, dup, bad = ic.run_local(found, unittest.mock.Mock(yes=False, dry_run=False),
                                                                    {}, out)
        self.assertEqual(new + updated, 0)
        self.assertFalse(out.exists())

    def test_local_path_auto_classifies_once_and_dry_run_counts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sessions"
            root.mkdir()
            codex = root / "rollout-c.jsonl"
            codex.write_text("\n".join([
                json.dumps({"type": "session_meta", "payload": {"id": "c"}}),
                json.dumps({"timestamp": "2026-08-01T10:00:00Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}}),
            ]), encoding="utf-8")
            claude = root / "claude.jsonl"
            claude.write_text(json.dumps({"type": "user", "uuid": "u", "message": {"role": "user", "content": "hello"}}), encoding="utf-8")
            unknown = root / "unknown.jsonl"
            unknown.write_text(json.dumps({"what": "ever"}), encoding="utf-8")
            out = Path(td) / "out"
            r = run_import("--source", "local", "--path", str(root), "--root", str(out), "--dry-run")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("预计新导入 2", r.stdout)
            self.assertIn("解析/写入失败 1", r.stdout)
            self.assertFalse(out.exists())

    def test_local_report_separates_expected_exclusions_from_bad_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sessions"
            root.mkdir()
            session = root / "rollout-report.jsonl"
            session.write_text("\n".join([
                json.dumps({"type": "session_meta", "payload": {"id": "report"}}),
                "{ malformed",
                json.dumps({"timestamp": "2026-08-01T10:00:00Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "# Files mentioned by the user:\n<path>/x</path>"}]}}),
                json.dumps({"timestamp": "2026-08-01T10:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "真实问题"}]}}),
            ]), encoding="utf-8")
            out = Path(td) / "out"
            r = run_import("--source", "local", "--path", str(root), "--local-format", "codex",
                           "--root", str(out), "--dry-run")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("预期内部内容排除 1 个片段", r.stdout)
            self.assertIn("解析/写入失败 1", r.stdout)
            self.assertFalse(out.exists())


if __name__ == "__main__":
    unittest.main()
