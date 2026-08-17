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

    def test_chatgpt_outer_reasoning_content_is_excluded_even_with_text_parts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "conversations-000.json"
            data = [{"id": "reasoning", "title": "x", "current_node": "a", "mapping": {
                "root": {"parent": None, "children": ["r"]},
                "r": {"parent": "root", "children": ["a"], "message": {
                    "id": "r", "author": {"role": "assistant"},
                    "content": {"content_type": "reasoning", "parts": ["不得泄漏的推理"]}}},
                "a": {"parent": "r", "children": [], "message": {
                    "id": "a", "author": {"role": "assistant"},
                    "content": {"parts": ["可见回答"]}}},
            }}]
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            convs, skipped, _total = ic.parse_chatgpt(p)
            self.assertEqual([m[3] for m in convs[0][4]], ["可见回答"])
            self.assertTrue(any(reason.startswith("内部内容已排除：ChatGPT reasoning")
                                for _ref, reason in skipped))

    def test_gemini_container_classes_are_exact_tokens_and_allow_valueless_attrs(self) -> None:
        parser = ic._GeminiActivityExtractor()
        parser.feed("<div class='not-outer-cell'><div>忽略</div></div><div class><div>也忽略</div></div>")
        self.assertEqual(parser.blocks, [])

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

    def test_deepseek_nested_file_metadata_is_not_stringified(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "conversations.json"
            p.write_text(json.dumps([{"id": "x", "mapping": {"n": {"parent": None, "children": [], "message": {
                "fragments": [{"type": "REQUEST", "content": "q"}, {"type": "FILE", "files": [{"file_name": {"secret": 1}}]}]}}}}]), encoding="utf-8")
            convs, skipped, _total = ic.parse_deepseek(p)
            self.assertEqual(convs, [])
            reasons = [reason for _ref, reason in skipped if "附件元数据结构损坏" in reason]
            self.assertTrue(reasons)
            self.assertTrue(all(not ic._is_expected_exclusion(reason) for reason in reasons))

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
        self.assertTrue(title)
        self.assertIn("帮我写个 Python 脚本", msgs[0][3])
        # A one-field fixture is not a proven system envelope and must survive.
        self.assertIn("environment_context", msgs[0][3])
        self.assertEqual(msgs[0][2], "u1")  # 真实 payload id 保留

    def test_codex_adversarial_cleaning(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-x.jsonl"
            lines = [
                '{"timestamp": "2026-08-01T10:00:00Z", "type": "session_meta", "payload": {"id": "adv"}}',
                '{"timestamp": "2026-08-01T10:00:01Z", "type": "response_item", "payload": {"type": "message", "role": "user", "id": "u1", "content": [{"type": "input_text", "text": "# AGENTS.md instructions for /\n<INSTRUCTIONS>平台规则</INSTRUCTIONS><environment_context><cwd>/x</cwd><shell>zsh</shell></environment_context>"}]}}',
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

    def test_codex_structured_images_are_safe_visible_messages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "rollout-images.jsonl"
            p.write_text("\n".join(json.dumps(record) for record in [
                {"type": "session_meta", "payload": {"id": "images"}},
                {"timestamp": "2026-08-01T10:00:00Z", "type": "response_item", "payload": {
                    "type": "message", "role": "user", "content": [
                        {"type": "input_image", "image_url": "https://private.example/image", "data": "secret"},
                    ]}},
                {"timestamp": "2026-08-01T10:00:01Z", "type": "response_item", "payload": {
                    "type": "message", "role": "assistant", "content": [
                        {"type": "output_image", "source": {"data": "secret-output"}},
                    ]}},
            ]), encoding="utf-8")
            events = []
            convs = ic.parse_codex(p, events)
            self.assertEqual([m[3] for m in convs[0][4]], ["[图片]", "[图片]"])
            self.assertNotIn("private.example", "\n".join(m[3] for m in convs[0][4]))
            self.assertFalse(events)

    def test_codex_empty_known_text_block_is_ignored_without_warning(self) -> None:
        events = []
        text = ic._codex_text_with_events([
            {"type": "input_text", "text": "可见文字"},
            {"type": "output_text", "text": ""},
        ], events)
        self.assertEqual(text, "可见文字")
        self.assertEqual(events, [])

    def test_codex_preserves_user_xml_but_removes_known_envelopes(self) -> None:
        user = ("<name>Ada</name><path>/safe</path><string>keep</string><prompt>keep too</prompt>\n"
                "<environment_context><cwd>/private</cwd></environment_context>\n"
                "真实正文")
        cleaned = ic._clean_codex_user(user)
        self.assertIn("<name>Ada</name>", cleaned)
        self.assertIn("<path>/safe</path>", cleaned)
        self.assertIn("<string>keep</string>", cleaned)
        self.assertIn("<prompt>keep too</prompt>", cleaned)
        self.assertIn("<environment_context><cwd>/private</cwd></environment_context>", cleaned)
        self.assertEqual(ic._clean_codex_user("<environment_context>literal code</environment_context>"),
                         "<environment_context>literal code</environment_context>")
        self.assertEqual(ic._clean_codex_user("<image>literal code</image>"),
                         "<image>literal code</image>")

    def test_codex_repeated_leading_wrappers_and_prefix_records_are_dropped(self) -> None:
        nested = ("<environment_context><cwd>/one</cwd><shell>zsh</shell></environment_context>\n"
                  "# AGENTS.md instructions for /\n<INSTRUCTIONS>internal</INSTRUCTIONS>\n"
                  "<recommended_plugins>available but not installed</recommended_plugins>\n"
                  "<environment_context><cwd>/two</cwd><shell>zsh</shell></environment_context>")
        self.assertEqual(ic._clean_codex_user(nested), "")
        self.assertEqual(ic._clean_codex_user("# Files mentioned by the user:\n<path>/x</path>"), "")
        self.assertEqual(ic._clean_codex_user("# In app browser:\n<url>http://x</url>"), "")
        ordinary = "用户说：# Files mentioned by the user: 只是一个字符串"
        self.assertEqual(ic._clean_codex_user(ordinary), ordinary)

    def test_codex_unclosed_known_wrappers_are_excluded_but_generic_xml_survives(self) -> None:
        events = []
        self.assertEqual(ic._clean_codex_user("<environment_context><cwd>/private</cwd>\n<shell>zsh", events), "")
        self.assertEqual(ic._clean_codex_user("# AGENTS.md instructions for /\n<INSTRUCTIONS>partial", events), "")
        self.assertTrue(any("残留未闭合" in event for event in events))
        self.assertEqual(ic._clean_codex_user("<name>Ada</name><path>/safe</path>"),
                         "<name>Ada</name><path>/safe</path>")
        self.assertEqual(ic._clean_codex_user("<imagery>keep</imagery><image-processing>x</image-processing>"),
                         "<imagery>keep</imagery><image-processing>x</image-processing>")
        self.assertIn("<environment_context>example</environment_context>",
                      ic._clean_codex_user("真实代码\n<environment_context>example</environment_context>"))

    def test_codex_real_wrapper_signatures_and_exact_image_placeholders(self) -> None:
        self.assertEqual(ic._clean_codex_user(
            "<environment_context><cwd>/work</cwd><shell>zsh</shell></environment_context>visible"), "visible")
        self.assertEqual(ic._clean_codex_user(
            "<environment_context><cwd>literal</cwd></environment_context>"),
            "<environment_context><cwd>literal</cwd></environment_context>")
        self.assertEqual(ic._clean_codex_user(
            "<heartbeat><automation_id>x</automation_id><current_time_iso>now</current_time_iso>instructions</heartbeat>visible"),
            "visible")
        self.assertEqual(ic._clean_codex_user("<heartbeat>literal heartbeat</heartbeat>"),
                         "<heartbeat>literal heartbeat</heartbeat>")
        for tag, body in (
            ("external_codex_apps_writing_block_edits_part_1_of_3", "block edit writing"),
            ("external_codex_apps_writing_block_edits_part_2_of_3", "block edit writing mcp"),
            ("external_codex_apps_writing_block_edits_part_3_of_3", "block edit writing"),
        ):
            with self.subTest(tag=tag):
                self.assertEqual(ic._clean_codex_user(f"<{tag}>{body}</{tag}>visible"), "visible")
        self.assertEqual(ic._clean_codex_user("<image name=[Image #7]></image>visible"), "[图片]visible")
        self.assertEqual(ic._clean_codex_user("<image name=[Image #8] path=/tmp/x></image>visible"), "[图片]visible")
        self.assertEqual(ic._clean_codex_user('<image name="demo" path="x">literal</image>'),
                         '<image name="demo" path="x">literal</image>')

    def test_codex_multiline_incomplete_wrappers_require_schema_evidence(self) -> None:
        events = []
        self.assertEqual(ic._clean_codex_user(
            "<environment_context>\n<cwd>/work</cwd>\n<shell>zsh", events), "")
        self.assertTrue(any("残留未闭合" in event for event in events))
        self.assertEqual(ic._clean_codex_user("<environment_context>\n<cwd>literal</cwd>"),
                         "<environment_context>\n<cwd>literal</cwd>")

    def test_malformed_json_boundaries_are_reported_without_attribute_errors(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            chatgpt = root / "conversations-000.json"
            for bad_mapping in ([], {"n": {"message": {"content": {"parts": "not-a-list"}}}}):
                chatgpt.write_text(json.dumps([{"id": "x", "mapping": bad_mapping}]), encoding="utf-8")
                _convs, skipped, _total = ic.parse_chatgpt(chatgpt)
                self.assertTrue(any("mapping" in reason or "消息结构" in reason for _ref, reason in skipped))
            deepseek = root / "conversations.json"
            for bad_mapping in ([], {"n": {"parent": None, "children": [], "message": {"fragments": ["bad"]}}},
                                {"n": {"parent": None, "children": [], "message": {"fragments": [{"type": "FILE", "files": "bad"}]}}}):
                deepseek.write_text(json.dumps([{"id": "x", "mapping": bad_mapping}]), encoding="utf-8")
                _convs, skipped, _total = ic.parse_deepseek(deepseek)
                self.assertTrue(any("结构损坏" in reason or "mapping" in reason for _ref, reason in skipped))
            codex = root / "rollout-bad.jsonl"
            codex.write_text("[]\n" + "\n".join(json.dumps({"type": "response_item", "payload": value})
                                                     for value in ([], ["bad"])), encoding="utf-8")
            events = []
            self.assertIsNone(ic.parse_codex(codex, events))
            self.assertTrue(any("结构损坏" in event for event in events))
            claude = root / "bad-claude.jsonl"
            claude.write_text("[]\n" + "\n".join(json.dumps({"type": "user", "message": value})
                                                      for value in ([], ["bad"])), encoding="utf-8")
            events = []
            self.assertIsNone(ic.parse_claude(claude, events))
            self.assertTrue(any("结构损坏" in event for event in events))
            with self.assertRaises(ic.ImportError_):
                ic._classify_local_file(codex, "auto")

    def test_visible_text_types_and_deepseek_fragment_failures_are_not_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            deepseek = root / "conversations.json"
            def export(fragments):
                return [{"id": "bad", "mapping": {
                    "root": {"parent": None, "children": ["m"]},
                    "m": {"parent": "root", "children": [], "message": {"fragments": fragments}},
                }}]
            for fragments, needle in (
                ([{"type": "REQUEST", "content": {"private": "object"}}], "REQUEST content 不是字符串"),
                ([{"type": "FILE", "files": [{"file_name": {"private": "object"}}]}], "附件元数据结构损坏"),
                ([{"type": "FUTURE_FRAGMENT", "content": "opaque"}], "未识别 DeepSeek 片段"),
            ):
                deepseek.write_text(json.dumps(export(fragments), ensure_ascii=False), encoding="utf-8")
                convs, skipped, _total = ic.parse_deepseek(deepseek)
                self.assertEqual(convs, [])
                reasons = [reason for _ref, reason in skipped if needle in reason]
                self.assertTrue(reasons)
                self.assertTrue(all(not ic._is_expected_exclusion(reason) for reason in reasons))

            codex = root / "rollout-types.jsonl"
            codex.write_text(json.dumps({"type": "response_item", "payload": {
                "type": "message", "role": "user", "content": [{"type": "input_text", "text": {"no": "render"}}],
            }}), encoding="utf-8")
            events = []
            self.assertIsNone(ic.parse_codex(codex, events))
            self.assertTrue(any("text 不是字符串" in event and not ic._is_expected_exclusion(event) for event in events))

            claude = root / "claude-types.jsonl"
            claude.write_text(json.dumps({"type": "user", "message": {
                "role": "user", "content": [{"type": "text", "text": ["no", "render"]}],
            }}), encoding="utf-8")
            events = []
            self.assertIsNone(ic.parse_claude(claude, events))
            self.assertTrue(any("text 不是字符串" in event and not ic._is_expected_exclusion(event) for event in events))

    def test_claude_non_string_type_is_structured_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "c.jsonl"
            p.write_text(json.dumps({"type": [], "message": {}}), encoding="utf-8")
            events = []
            self.assertIsNone(ic.parse_claude(p, events))
            self.assertTrue(any("type 不是字符串" in event for event in events))
            with self.assertRaises(ic.ImportError_):
                ic._classify_local_file(p, "auto")

    def test_peek_ignores_non_object_codex_payload_and_claude_message(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            codex = root / "rollout-peek.jsonl"
            codex.write_text(json.dumps({"payload": []}), encoding="utf-8")
            self.assertEqual(ic._peek("codex", codex), (None, None, ""))
            claude = root / "peek-claude.jsonl"
            claude.write_text(json.dumps({"type": "user", "message": []}), encoding="utf-8")
            self.assertEqual(ic._peek("claude", claude), (None, None, ""))

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
<div>请比较这两个时间安排。</div><div class='content-cell mdl-cell--6-col mdl-typography--body-1'>2026年8月3日 下午4:05</div>
<div><br><p>可以先处理第一项。</p></div></div></body></html>""", encoding="utf-8")
            convs, _skipped, total = ic.parse_gemini(p)
            self.assertEqual((total, len(convs)), (1, 1))
            msgs = convs[0][4]
            self.assertEqual({m[1] for m in msgs}, {"2026-08-03 16:05"})
            self.assertIn("2026年8月1日 上午9:00", msgs[0][3])
            self.assertIn("2026年8月2日 下午3:00", msgs[0][3])
            self.assertIn("可以先处理第一项", msgs[1][3])

    def test_gemini_structural_time_preserves_date_in_answer_and_ids_are_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<html><body><div class='outer-cell'>
<div>Gemini Apps</div><div>Prompted：请安排</div>
<div class='content-cell mdl-cell--6-col mdl-typography--body-1'>2026年8月3日 下午4:05</div>
<div><br><p>回答中提到 2026年8月5日 上午9:00。</p></div></div></body></html>""", encoding="utf-8")
            convs, _skipped, total = ic.parse_gemini(p)
            self.assertEqual((total, len(convs)), (1, 1))
            cid = convs[0][1]
            msgs = convs[0][4]
            self.assertEqual({m[1] for m in msgs}, {"2026-08-03 16:05"})
            self.assertIn("2026年8月5日 上午9:00", msgs[1][3])
            self.assertEqual([m[2] for m in msgs], [f"{cid}:user:1", f"{cid}:assistant:2"])

    def test_gemini_unstructured_inline_time_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<html><body><div class='outer-cell'>
<div>Prompted：问题</div><div>2026年8月3日 下午4:05</div><div>回答</div>
</div></body></html>""", encoding="utf-8")
            with self.assertRaisesRegex(ic.ImportError_, "无法可靠绑定"):
                ic.parse_gemini(p)

    def test_gemini_multiple_structural_inline_times_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<html><body><div class='outer-cell'>
<div>Prompted：问题</div>
<div class='content-cell mdl-typography--body-1'>2026年8月3日 下午4:05</div>
<div class='content-cell mdl-typography--body-1'>2026年8月4日 下午4:05</div>
<div><br><p>回答</p></div></div></body></html>""", encoding="utf-8")
            with self.assertRaisesRegex(ic.ImportError_, "多个结构化活动时间"):
                ic.parse_gemini(p)

    def test_gemini_legacy_answer_keeps_date_text(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<div class='outer-cell'><div class='header-cell'>2026年8月1日 下午3:00</div><div>Prompted：问题</div></div>
<div class='outer-cell'><div class='header-cell'>2026年8月1日 下午3:01</div><div>Gemini：回答提到 2026年8月5日 上午9:00</div></div>""", encoding="utf-8")
            convs, _skipped, _total = ic.parse_gemini(p)
            self.assertIn("2026年8月5日 上午9:00", convs[0][4][1][3])

    def test_gemini_only_strips_structural_labels(self) -> None:
        self.assertEqual(ic._gemini_user_text(["Prompted：正文"]), "正文")
        self.assertEqual(ic._gemini_user_text(["Prompted by a person"]), "Prompted by a person")
        self.assertEqual(ic._gemini_answer_text(["Gemini：回答", "Gemini can help"]), "回答\nGemini can help")

    def test_gemini_direct_no_colon_prompted_label_is_structural(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<div class='outer-cell'>
<div class='content-cell mdl-cell--6-col mdl-typography--body-1'>Prompted actual prompt</div>
<div class='content-cell mdl-cell--6-col mdl-typography--body-1'>2026年8月3日 下午4:05</div>
<div><br><p>Gemini can help with this.</p></div></div>""", encoding="utf-8")
            convs, _skipped, total = ic.parse_gemini(p)
            self.assertEqual((total, len(convs)), (1, 1))
            msgs = convs[0][4]
            self.assertEqual(msgs[0][3], "actual prompt")
            self.assertEqual(msgs[1][3], "Gemini can help with this.")

    def test_gemini_removes_chrome_only_from_proven_metadata_nodes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<div class='outer-cell'>
<div class='header-cell'>Gemini Apps</div>
<div class='content-cell mdl-cell--6-col mdl-typography--body-1'>Prompted：<span>Gemini Apps in prompt</span></div>
<div class='content-cell mdl-cell--6-col mdl-typography--body-1'>https://gemini.google.com/ordinary-user-url</div>
<div class='content-cell mdl-cell--6-col mdl-typography--body-1'>2026年8月3日 下午4:05</div>
<div class='mdl-typography--caption'>Gemini Apps</div><div class='mdl-typography--caption'>https://gemini.google.com/activity</div>
<div><p>Gemini Apps in answer</p><p>https://gemini.google.com/ordinary-answer-url</p></div>
</div>""", encoding="utf-8")
            convs, _skipped, total = ic.parse_gemini(p)
            self.assertEqual((total, len(convs)), (1, 1))
            user, answer = (m[3] for m in convs[0][4])
            self.assertIn("Gemini Apps in prompt", user)
            self.assertIn("ordinary-user-url", user)
            self.assertEqual(answer, "Gemini Apps in answer\nhttps://gemini.google.com/ordinary-answer-url")

    def test_gemini_splits_prompted_activities_with_stable_ids(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            p.write_text("""<html><body>
<div class='outer-cell'><div class='header-cell'>2026年8月1日 下午3:00</div><div>Prompted：重复问题</div></div>
<div class='outer-cell'><div class='header-cell'>2026年8月1日 下午3:01</div><div>Gemini：第一个回答</div></div>
<div class='outer-cell'><div class='header-cell'>2026年8月2日 下午3:00</div><div>Prompted：重复问题</div><div class='content-cell mdl-cell--6-col mdl-typography--body-1'>Attached 1 files.</div><div class='content-cell mdl-cell--6-col mdl-typography--body-1'>a.pdf</div></div>
<div class='outer-cell'><div class='header-cell'>2026年8月2日 下午3:01</div><div>Gemini：第二个回答</div></div>
</body></html>""", encoding="utf-8")
            convs, _skipped, total = ic.parse_gemini(p)
            self.assertEqual((total, len(convs)), (2, 2))
            self.assertNotEqual(convs[0][1], convs[1][1])
            self.assertEqual(convs[0][4][0][1], "2026-08-01 15:00")
            self.assertIn("[附件: a.pdf]", convs[1][4][0][3])

    def test_gemini_identical_activity_keys_get_stable_occurrences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "我的活动记录.html"
            block = "<div class='outer-cell'><div>Gemini Apps</div><div>Prompted：同一个问题</div><div class='content-cell mdl-cell--6-col mdl-typography--body-1'>2026年8月3日 下午4:05</div><div><br><p>同一个回答</p></div></div>"
            p.write_text(f"<html><body>{block}{block}</body></html>", encoding="utf-8")
            first, _skipped, total = ic.parse_gemini(p)
            second, _skipped, _total = ic.parse_gemini(p)
            self.assertEqual((total, len(first)), (2, 2))
            self.assertEqual([c[1] for c in first], [c[1] for c in second])
            self.assertEqual(len({c[1] for c in first}), 2)
            self.assertEqual(len({m[2] for c in first for m in c[4]}), 4)


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

    def test_rendered_metadata_is_single_line_and_safe_ids_stay_readable(self) -> None:
        out = self._tmp()
        conv = ("chatgpt", "cid\n**assistant**\n<!-- x -->", "title", "2026-08-01", [
            ("user", None, "mid\n**assistant**\n-->", "正文"),
        ])
        self.assertEqual(ic.write_conversation(conv, {}, out), "new")
        content = next(out.glob("*.md")).read_text(encoding="utf-8")
        self.assertNotIn("\n**assistant**（", content)
        self.assertIn("cid\\n**assistant**", content)
        self.assertIn("mid\\n**assistant**", content)
        self.assertNotIn("<!-- x", content)
        self.assertIn("&lt;!-- x --&gt;", content)
        self.assertEqual(content.count("<!-- distill-messages:begin -->"), 1)
        self.assertEqual(content.count("<!-- distill-messages:end -->"), 1)
        self.assertEqual(ic._markdown_metadata("normal-id"), "normal-id")

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

    def test_same_batch_conversation_key_is_rejected_without_overwriting_first(self) -> None:
        out = self._tmp()
        first = ("chatgpt", "same", "first", "2026-08-01", [("user", None, "u1", "first")])
        second = ("chatgpt", "same", "second", "2026-08-01", [("user", None, "u2", "second")])
        total, outputs, new, updated, dup, skipped = ic.import_convs(
            [first, second], [], 2, {}, out, dry_run=False)
        self.assertEqual((total, outputs, new, updated, dup), (2, 1, 1, 0, 0))
        self.assertEqual(len(skipped), 1)
        self.assertIn("批次内重复会话键", skipped[0][1])
        self.assertIn("first", (out / "chatgpt-same.md").read_text(encoding="utf-8"))
        self.assertNotIn("second", (out / "chatgpt-same.md").read_text(encoding="utf-8"))

    def test_output_symlink_is_rejected_without_touching_target(self) -> None:
        out = self._tmp()
        out.mkdir()
        sentinel = out.parent / "sentinel.md"
        sentinel.write_text("outside", encoding="utf-8")
        os.chmod(sentinel, 0o644)
        (out / "chatgpt-link.md").symlink_to(sentinel)
        conv = ("chatgpt", "link", "title", "2026-08-01", [("user", None, "u", "inside")])
        with self.assertRaisesRegex(ic.ImportError_, "符号链接"):
            ic.write_conversation(conv, {}, out)
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside")
        self.assertEqual(os.stat(sentinel).st_mode & 0o777, 0o644)

    def test_output_root_and_state_symlinks_are_rejected_without_touching_targets(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            external_dir = root / "external-dir"
            external_dir.mkdir()
            os.chmod(external_dir, 0o755)
            linked_root = root / "linked-root"
            linked_root.symlink_to(external_dir, target_is_directory=True)
            with self.assertRaisesRegex(ic.ImportError_, "输出根目录是符号链接"):
                ic.load_imported(linked_root)
            self.assertEqual(os.stat(external_dir).st_mode & 0o777, 0o755)
            out = root / "out"
            out.mkdir()
            sentinel = root / "state-sentinel"
            sentinel.write_text("state", encoding="utf-8")
            os.chmod(sentinel, 0o644)
            ic.imported_path(out).symlink_to(sentinel)
            with self.assertRaisesRegex(ic.ImportError_, "状态文件是符号链接"):
                ic.load_imported(out)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "state")
            self.assertEqual(os.stat(sentinel).st_mode & 0o777, 0o644)

    def test_output_ancestor_symlink_is_rejected_without_touching_external_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            external = base / "external"
            external.mkdir()
            os.chmod(external, 0o755)
            parent = base / "linked-parent"
            parent.symlink_to(external, target_is_directory=True)
            nested = parent / "nested"
            with self.assertRaisesRegex(ic.ImportError_, "祖先是符号链接"):
                ic.load_imported(nested)
            self.assertFalse((external / "nested").exists())
            self.assertEqual(os.stat(external).st_mode & 0o777, 0o755)

    def test_zip_read_runtime_error_becomes_import_error(self) -> None:
        fake = unittest.mock.MagicMock()
        fake.__enter__.return_value = fake
        fake.namelist.return_value = ["conversations.json"]
        fake.read.side_effect = RuntimeError("encrypted")
        with unittest.mock.patch("zipfile.ZipFile", return_value=fake):
            with self.assertRaises(ic.ImportError_):
                ic.parse_deepseek(Path("fake.zip"))

    def test_local_cancellation_exits_without_report_or_writes(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            session = root / "rollout-c.jsonl"
            session.write_text(json.dumps({"type": "session_meta", "payload": {"id": "c"}}), encoding="utf-8")
            out = root / "out"
            r = subprocess.run([sys.executable, "import_chats.py", "--source", "local", "--path", str(session),
                                "--local-format", "codex", "--root", str(out)], input="n\n", text=True,
                               capture_output=True, cwd=str(PROJECT_ROOT))
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("已取消。", r.stdout)
            self.assertNotIn("完成。", r.stdout)
            self.assertNotIn("写入目录", r.stdout)
            self.assertFalse(out.exists())

    def test_collision_cli_reports_only_successful_outputs_and_partial_exit(self) -> None:
        def conversation(cid: str, mid: str) -> dict:
            return {"id": cid, "title": cid, "current_node": mid, "mapping": {
                "root": {"parent": None, "children": [mid]},
                mid: {"parent": "root", "children": [], "message": {
                    "id": mid, "author": {"role": "user"}, "create_time": 1,
                    "content": {"parts": ["正文"]},
                }},
            }}
        with tempfile.TemporaryDirectory() as td:
            export = Path(td) / "conversations-000.json"
            export.write_text(json.dumps([conversation("a/b", "m1"), conversation("a?b", "m2")]),
                              encoding="utf-8")
            r = run_import("--source", "chatgpt", "--path", str(export),
                           "--root", str(Path(td) / "out"), "--yes")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("原始 2 个会话，输出 1 个会话 → 新导入 1", r.stdout)
        self.assertIn("解析/写入失败 1", r.stdout)

    def test_same_key_cli_is_partial_and_reverse_markers_report_cleanly(self) -> None:
        def conversation(cid: str, mid: str, text: str) -> dict:
            return {"id": cid, "title": cid, "current_node": mid, "mapping": {
                "root": {"parent": None, "children": [mid]},
                mid: {"parent": "root", "children": [], "message": {
                    "id": mid, "author": {"role": "user"}, "create_time": 1,
                    "content": {"parts": [text]},
                }},
            }}
        with tempfile.TemporaryDirectory() as td:
            export = Path(td) / "conversations-000.json"
            out = Path(td) / "out"
            export.write_text(json.dumps([conversation("same", "m1", "first"),
                                          conversation("same", "m2", "second")]), encoding="utf-8")
            r = run_import("--source", "chatgpt", "--path", str(export), "--root", str(out), "--yes")
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertIn("批次内重复会话键", r.stdout)
            self.assertIn("first", (out / "chatgpt-same.md").read_text(encoding="utf-8"))

            reverse = out / "chatgpt-reverse.md"
            reverse.write_text("<!-- source: chatgpt -->\n<!-- conversation_id: reverse -->\n"
                               "<!-- distill-messages:end -->\nold\n<!-- distill-messages:begin -->\n",
                               encoding="utf-8")
            export.write_text(json.dumps([conversation("reverse", "m3", "replacement")]), encoding="utf-8")
            reverse_run = run_import("--source", "chatgpt", "--path", str(export), "--root", str(out), "--yes")
            self.assertEqual(reverse_run.returncode, 1, reverse_run.stdout + reverse_run.stderr)
            self.assertIn("消息标记顺序损坏", reverse_run.stdout)
            self.assertNotIn("Traceback", reverse_run.stderr)

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

    def test_atomic_write_ignores_predictable_tmp_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "private.md"
            sentinel = root / "sentinel"
            sentinel.write_text("outside", encoding="utf-8")
            path.with_name(path.name + ".tmp").symlink_to(sentinel)
            ic._atomic_write(path, "inside")
            self.assertEqual(path.read_text(encoding="utf-8"), "inside")
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "outside")

    def test_atomic_write_cleans_unique_tmp_when_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "private.md"
            with unittest.mock.patch("os.replace", side_effect=OSError("replace failed")):
                with self.assertRaisesRegex(OSError, "replace failed"):
                    ic._atomic_write(path, "inside")
            self.assertEqual(list(Path(td).glob(".private.md.*.tmp")), [])

    def test_reserved_markers_in_user_fields_do_not_corrupt_repeat_import(self) -> None:
        out = self._tmp()
        marker_text = "<prompt>正常 XML</prompt>\n<!-- distill-messages:begin -->\n<!-- distill-messages:end -->"
        conv = ("chatgpt", "marker", "标题 <!-- distill-messages:begin -->", "2026-08-01", [
            ("user", None, "id-<!-- distill-messages:end -->", marker_text),
        ])
        imported = {}
        self.assertEqual(ic.write_conversation(conv, imported, out), "new")
        self.assertEqual(ic.write_conversation(conv, imported, out), "dup")
        content = (out / "chatgpt-marker.md").read_text(encoding="utf-8")
        self.assertEqual(content.count("<!-- distill-messages:begin -->"), 1)
        self.assertEqual(content.count("<!-- distill-messages:end -->"), 1)
        self.assertIn("&lt;!-- distill-messages:begin --&gt;", content)
        self.assertIn("<prompt>正常 XML</prompt>", content)

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

    def test_non_dict_chatgpt_and_deepseek_items_fail_without_traceback(self) -> None:
        for source, filename in (("chatgpt", "conversations-000.json"),
                                 ("deepseek", "conversations.json")):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as td:
                export = Path(td) / filename
                export.write_text("[null]", encoding="utf-8")
                r = run_import("--source", source, "--path", str(export),
                               "--root", str(self._tmp()), "--yes")
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("会话条目结构损坏", r.stdout)
                self.assertNotIn("Traceback", r.stderr)

    def test_deepseek_malformed_fragment_is_partial_cli_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            export = Path(td) / "conversations.json"
            export.write_text(json.dumps([
                {"id": "valid", "mapping": {"m": {"parent": None, "children": [], "message": {
                    "fragments": [{"type": "REQUEST", "content": "visible"}],
                }}}},
                {"id": "bad", "mapping": {"m": {"parent": None, "children": [], "message": {
                    "fragments": [{"type": "FILE", "files": [{"file_id": {"opaque": 1}}]}],
                }}}},
            ], ensure_ascii=False), encoding="utf-8")
            r = run_import("--source", "deepseek", "--path", str(export),
                           "--root", str(Path(td) / "out"), "--yes")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("原始 2 个会话，输出 1 个会话", r.stdout)
        self.assertIn("附件元数据结构损坏", r.stdout)

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

    def test_local_auto_skips_known_claude_preamble_before_classifying(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "sessions"
            root.mkdir()
            session = root / "claude.jsonl"
            session.write_text("\n".join(json.dumps(record) for record in [
                {"type": "file-history-snapshot", "payload": {}},
                {"type": "user", "uuid": "u", "message": {"role": "user", "content": "真实内容"}},
            ]), encoding="utf-8")
            r = run_import("--source", "local", "--path", str(root), "--root", str(Path(td) / "out"),
                           "--dry-run")
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn("预计新导入 1", r.stdout)

    def test_nonexistent_or_empty_local_path_is_failure(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            missing = Path(td) / "missing"
            empty = Path(td) / "empty"
            not_jsonl = Path(td) / "notes.txt"
            empty.mkdir()
            not_jsonl.write_text("not a session", encoding="utf-8")
            for path, expected in ((missing, "本地路径不存在"), (empty, "本地路径未包含 JSONL 会话"),
                                   (not_jsonl, "本地路径不是 JSONL 会话")):
                with self.subTest(path=path):
                    r = run_import("--source", "local", "--path", str(path),
                                   "--root", str(Path(td) / "out"), "--dry-run")
                    self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                    self.assertIn(expected, r.stdout)

    def test_local_dry_run_claims_paths_and_reports_same_source_collisions(self) -> None:
        out = self._tmp()
        for source, parser_name in (("codex", "parse_codex"), ("claude", "parse_claude")):
            with self.subTest(source=source):
                first = (source, "a/b", "first", "2026-08-01", [("user", None, "u1", "one")])
                second = (source, "a?b", "second", "2026-08-01", [("user", None, "u2", "two")])
                found = [
                    (source, "first-session", "first", None, None, 1, "first.jsonl"),
                    (source, "second-session", "second", None, None, 1, "second.jsonl"),
                ]
                args = unittest.mock.Mock(yes=True, dry_run=True)
                with unittest.mock.patch.object(ic, parser_name, side_effect=[[first], [second]]):
                    total, outputs, new, updated, dup, bad = ic.run_local(found, args, {}, out)
                self.assertEqual((total, outputs, new, updated, dup), (2, 1, 1, 0, 0))
                self.assertEqual(len(bad), 1)
                self.assertIn("文件名冲突", bad[0][1])
        self.assertFalse(out.exists())

    def test_local_batch_duplicate_key_is_rejected_before_second_write(self) -> None:
        out = self._tmp()
        first = ("codex", "same", "first", "2026-08-01", [("user", None, "u1", "first")])
        second = ("codex", "same", "second", "2026-08-01", [("user", None, "u2", "second")])
        found = [
            ("codex", "one", "first", None, None, 1, "one.jsonl"),
            ("codex", "two", "second", None, None, 1, "two.jsonl"),
        ]
        args = unittest.mock.Mock(yes=True, dry_run=False)
        with unittest.mock.patch.object(ic, "parse_codex", side_effect=[[first], [second]]):
            total, outputs, new, updated, dup, bad = ic.run_local(found, args, {}, out)
        self.assertEqual((total, outputs, new, updated, dup), (2, 1, 1, 0, 0))
        self.assertEqual(len(bad), 1)
        self.assertIn("批次内重复会话键", bad[0][1])
        self.assertIn("first", (out / "codex-same.md").read_text(encoding="utf-8"))

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
