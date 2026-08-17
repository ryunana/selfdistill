#!/usr/bin/env python3
"""selfdistill chat importer：把各来源聊天记录自动整理成统一 Markdown 写入 input/。

用法：
    python3 import_chats.py --source chatgpt  --path <导出目录或文件>
    python3 import_chats.py --source gemini   --path <Takeout 解压目录>
    python3 import_chats.py --source deepseek --path <conversations.json 或 zip>
    python3 import_chats.py --source local [--since YYYY-MM-DD] [--exclude glob] [--dry-run]

- 本地主动发现（codex/claude）默认先列清单、确认后才写入；--dry-run 只列清单不写文件。
- 输出遵循 docs/intake.md 与 distill-candidate 的 ID 契约（conversation_id/message_id/exported_at）。
- 增量去重：.imported.json 记录每会话已导入的 message_id，重复导入只追加新消息。
- 隐私：输出目录 0700、文件 0600、原子写入。
- 纯 Python 标准库，无第三方依赖。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import sys
import tempfile
import zipfile
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "input"
IMPORTED_FILE = INPUT_DIR / ".imported.json"

SOURCES = ("chatgpt", "gemini", "deepseek", "local")
LOCAL_ROOTS = (
    ("codex", "~/.codex/sessions", "rollout-*.jsonl"),
    ("claude", "~/.claude/projects", "*.jsonl"),
)

SKIP_EMPTY = "无消息"
SKIP_BAD = "损坏/无法解析"
SKIP_UNKNOWN = "结构未能识别"
SKIP_DUP = "已导入过（无新消息）"
SKIP_EXCLUDED = "被排除"
SKIP_CANCELLED = "__cancelled__"


class ImportError_(Exception):
    pass


# ---------- 时间 ----------

_CN_DATETIME = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*([上午下午晚上]*)(\d{1,2})[:：点](\d{1,2})")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_EN_DATETIME = re.compile(
    r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),?\s+(\d{4})[,\s]+(\d{1,2}):(\d{2})\s*(AM|PM)", re.I)
_TIME_LINE = re.compile(r"\b\d{4}年\d{1,2}月\d{1,2}日\s*[上午下午晚上]*\d{1,2}[:：点]\d{1,2}")
_TIME_FIELD = re.compile(
    r"^\s*\d{4}年\d{1,2}月\d{1,2}日\s*[上午下午晚上]*\d{1,2}[:：点]\d{1,2}(?:[:：]\d{1,2})?(?:\s*(?:CST|GMT[+-]\d+)?)?\s*$")


def fmt_time(value) -> Optional[str]:
    """归一化为本地时区 'YYYY-MM-DD HH:MM'；无法解析返回 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return None
    s = str(value).strip()
    if not s:
        return None
    m = _CN_DATETIME.match(s)
    if m:
        y, mo, d, ap, h, mi = m.groups()
        h = int(h)
        if ("下" in ap or "晚" in ap) and h < 12:
            h += 12
        elif "上" in ap and h == 12:
            h = 0
        return f"{y}-{int(mo):02d}-{int(d):02d} {h:02d}:{mi}"
    m = _EN_DATETIME.match(s)
    if m:
        mon, d, y, h, mi, ap = m.groups()
        h = int(h) % 12
        if ap.upper() == "PM":
            h += 12
        return f"{y}-{_MONTHS[mon.lower()]:02d}-{int(d):02d} {h:02d}:{mi}"
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ---------- 解析器公共 ----------

def _normalize_message_text(text: str) -> str:
    """Use LF internally so cross-platform exports compare to rendered Markdown."""
    return str(text).replace("\r\n", "\n").replace("\r", "\n")


def _safe_scalar(value) -> Optional[str]:
    """Accept only normal scalar metadata; nested values never become text."""
    if isinstance(value, str):
        return value if value else None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return None


def _safe_title(value, default: str = "未命名会话") -> str:
    return _safe_scalar(value) or default


def _usable_conversation_id(value) -> Optional[str]:
    """Provider conversation IDs must be scalar and nonblank to own a file."""
    value = _safe_scalar(value)
    return value if value and value.strip() else None


def _stable_id(role: str, t: Optional[str], text: str) -> str:
    """稳定消息 id：无真实 id 时用内容指纹，保证增量去重不随行号漂移。"""
    return "fp-" + hashlib.sha1(
        f"{role}|{t or ''}|{_normalize_message_text(text)}".encode("utf-8")).hexdigest()[:12]


def _occurrence_id(role: str, raw_timestamp, line_ordinal: int, text: str) -> str:
    """Fallback for append-only local JSONL records that have no native message ID."""
    return "fp-" + hashlib.sha1(
        f"{role}|{_safe_scalar(raw_timestamp) or ''}|{line_ordinal}|{_normalize_message_text(text)}".encode("utf-8")
    ).hexdigest()[:12]


def _make_conversation(source: str, cid: str, title: str, msgs: list) -> tuple:
    title = " ".join(_safe_title(title).split())
    times = [t for _r, t, _m, _x in msgs if t]
    exported_at = times[-1][:10] if times else today_str()
    return (source, cid, title, exported_at, msgs)


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "conversation"


def _path_fingerprint(path: list[str]) -> str:
    return hashlib.sha1("\x1f".join(path).encode("utf-8")).hexdigest()[:12]


def _root_to_leaf_paths(mapping: dict) -> list[list[str]]:
    """Return validated parent-linked paths.  A tree error must not be flattened."""
    if not isinstance(mapping, dict) or not mapping:
        raise ImportError_("会话 mapping 为空或结构损坏")
    nodes = {str(nid): node for nid, node in mapping.items() if isinstance(node, dict)}
    if not nodes:
        raise ImportError_("会话 mapping 没有有效节点")
    children: dict[str, list[str]] = {nid: [] for nid in nodes}
    for nid, node in nodes.items():
        parent = node.get("parent")
        if parent is None:
            continue
        parent = str(parent)
        if parent not in nodes:
            raise ImportError_("会话 mapping 存在断链")
        children[parent].append(nid)
    for nid, node in nodes.items():
        declared = node.get("children") or []
        if not isinstance(declared, list):
            raise ImportError_("会话 mapping 的 children 不是列表")
        for child in declared:
            child = str(child)
            if child not in nodes:
                raise ImportError_("会话 mapping 存在断链")
            if str(nodes[child].get("parent")) != nid:
                raise ImportError_("会话 mapping 的 parent/children 不一致")
        if set(map(str, declared)) != set(children[nid]):
            raise ImportError_("会话 mapping 的 parent/children 不一致")
    for start in nodes:
        seen = set()
        nid: Optional[str] = start
        while nid is not None:
            if nid in seen:
                raise ImportError_("会话 mapping 存在循环")
            seen.add(nid)
            parent = nodes[nid].get("parent")
            nid = str(parent) if parent is not None else None
    leaves = sorted(nid for nid, kids in children.items() if not kids)
    if not leaves:
        raise ImportError_("会话 mapping 没有叶子节点（可能存在循环）")
    paths = []
    for leaf in leaves:
        chain = []
        seen = set()
        nid: Optional[str] = leaf
        while nid is not None:
            if nid in seen:
                raise ImportError_("会话 mapping 存在循环")
            seen.add(nid)
            chain.append(nid)
            parent = nodes[nid].get("parent")
            nid = str(parent) if parent is not None else None
        paths.append(list(reversed(chain)))
    return paths


def _path_to_node(mapping: dict, node_id: str) -> list[str]:
    """Validate and return the path ending at the explicitly active node."""
    nodes = {str(nid): node for nid, node in mapping.items() if isinstance(node, dict)}
    if node_id not in nodes:
        raise ImportError_("current_node 不存在或不是有效节点")
    chain = []
    seen = set()
    nid: Optional[str] = node_id
    while nid is not None:
        if nid in seen:
            raise ImportError_("会话 mapping 存在循环")
        seen.add(nid)
        chain.append(nid)
        parent = nodes[nid].get("parent")
        if parent is not None and str(parent) not in nodes:
            raise ImportError_("会话 mapping 存在断链")
        nid = str(parent) if parent is not None else None
    return list(reversed(chain))


def _chatgpt_parts(parts) -> tuple[str, int]:
    """Render only known human-safe ChatGPT parts; never stringify structures."""
    rendered: list[str] = []
    unknown = 0
    for part in parts or []:
        if isinstance(part, str):
            if part.strip():
                rendered.append(part)
        elif isinstance(part, dict):
            kind = str(part.get("content_type") or part.get("type") or "").lower()
            if ("image" in kind or "asset_pointer" in part or "image_asset_pointer" in part):
                rendered.append("[图片]")
            elif kind in ("thoughts", "reasoning_recap", "reasoning"):
                continue
            else:
                rendered.append("[未识别附件]")
                unknown += 1
        elif part is not None:
            rendered.append("[未识别附件]")
            unknown += 1
    return "\n".join(rendered).strip(), unknown


# ---------- 解析器：ChatGPT（沿活动路径，不压平分支） ----------

def parse_chatgpt(path: Path) -> tuple:
    """Use current_node, otherwise preserve each complete branch rather than flattening."""
    files = sorted(path.glob("conversations-*.json")) if path.is_dir() else [path]
    if not files:
        raise ImportError_(f"未找到 conversations-*.json：{path}")
    convs = []
    skipped = []
    total = 0
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            skipped.append((f.name, SKIP_BAD))
            continue
        if not isinstance(data, list):
            skipped.append((f.name, SKIP_BAD))
            continue
        total += len(data or [])
        for conv in data or []:
            if not isinstance(conv, dict):
                skipped.append((f.name, "会话条目结构损坏"))
                continue
            base = _usable_conversation_id(conv.get("id"))
            if base is None:
                skipped.append(("—", "ChatGPT 会话 ID 无效"))
                continue
            mapping = conv.get("mapping") or {}
            if not isinstance(mapping, dict):
                skipped.append(("—", "会话 mapping 不是对象"))
                continue
            if any(not isinstance(node, dict) for node in mapping.values()):
                skipped.append(("—", "会话 mapping 节点不是对象"))
                continue
            malformed = False
            for node in mapping.values():
                msg = node.get("message")
                if msg is not None and not isinstance(msg, dict):
                    malformed = True
                    break
                if isinstance(msg, dict):
                    for name in ("author", "content"):
                        value = msg.get(name)
                        if value is not None and not isinstance(value, dict):
                            malformed = True
                            break
                    content = msg.get("content") if isinstance(msg.get("content"), dict) else None
                    if content is not None and content.get("parts") is not None and not isinstance(content.get("parts"), list):
                        malformed = True
                        break
                if malformed:
                    break
            if malformed:
                skipped.append(("—", "会话消息结构不是对象"))
                continue
            current = conv.get("current_node")
            has_valid_current = bool(current and str(current) in mapping)
            try:
                paths = ([_path_to_node(mapping, str(current))]
                         if has_valid_current else _root_to_leaf_paths(mapping))
            except ImportError_ as e:
                skipped.append(("—", "会话 mapping 结构损坏"))
                continue
            valid = []
            unknown_role_nodes: set[str] = set()
            known_internal_role_nodes: set[str] = set()
            reasoning_nodes: set[str] = set()
            unknown_parts_by_node: dict[str, int] = {}
            for node_path in paths:
                msgs = []
                for nid in node_path:
                    node = mapping[nid]
                    if not isinstance(node.get("message"), dict):
                        continue
                    msg = node["message"]
                    author = msg.get("author") if isinstance(msg.get("author"), dict) else {}
                    raw_role = author.get("role")
                    role = raw_role.lower() if isinstance(raw_role, str) else ""
                    if role in ("system", "tool"):
                        known_internal_role_nodes.add(nid)
                        continue
                    if role not in ("user", "assistant"):
                        unknown_role_nodes.add(nid)
                        continue
                    content = msg.get("content") or {}
                    content_kind = str(content.get("content_type") or content.get("type") or "").lower()
                    if content_kind in ("thoughts", "reasoning_recap", "reasoning"):
                        reasoning_nodes.add(nid)
                        continue
                    text, unknown = _chatgpt_parts(content.get("parts"))
                    if unknown:
                        unknown_parts_by_node.setdefault(nid, unknown)
                    if not text:
                        continue
                    mid = _safe_scalar(msg.get("id")) or nid or _stable_id(role, None, text)
                    msgs.append((role, fmt_time(msg.get("create_time")), mid, text))
                if msgs:
                    valid.append((node_path, msgs))
            if not valid:
                if reasoning_nodes:
                    skipped.append(("—",
                                    f"内部内容已排除：ChatGPT reasoning {len(reasoning_nodes)} 个"))
                else:
                    skipped.append(("—", SKIP_EMPTY))
                if unknown_parts_by_node:
                    skipped.append(("—", f"未识别 ChatGPT 附件 {sum(unknown_parts_by_node.values())} 个"))
                for _ in unknown_role_nodes:
                    skipped.append(("—", "未知 ChatGPT 消息角色"))
                for _ in known_internal_role_nodes:
                    skipped.append(("—", "内部内容已排除：ChatGPT 已知消息角色"))
                continue
            branching = not has_valid_current and len(valid) > 1
            for index, (node_path, msgs) in enumerate(valid, 1):
                cid = f"{base}--branch-{_path_fingerprint(node_path)}" if branching else base
                title = _safe_title(conv.get("title"))
                if branching:
                    title += f"（分支 {index}）"
                convs.append(_make_conversation("chatgpt", cid, title, msgs))
            if unknown_parts_by_node:
                skipped.append(("—", f"未识别 ChatGPT 附件 {sum(unknown_parts_by_node.values())} 个"))
            if reasoning_nodes:
                skipped.append(("—", f"内部内容已排除：ChatGPT reasoning {len(reasoning_nodes)} 个"))
            for _ in unknown_role_nodes:
                skipped.append(("—", "未知 ChatGPT 消息角色"))
            for _ in known_internal_role_nodes:
                skipped.append(("—", "内部内容已排除：ChatGPT 已知消息角色"))
    return convs, skipped, total


# ---------- 解析器：Gemini Takeout（按真实结构） ----------

_GEMINI_DROP_LINES = re.compile(
    r"^(Gemini Apps|商品：|详细信息：|为什么此处会显示此活动记录？|此处|控制这些设置)$")
_GEMINI_URL_LINE = re.compile(r"^https?://gemini\.google\.com/")


class _GeminiActivityExtractor(HTMLParser):
    """Capture Takeout fields and mark only structurally explicit activity times."""
    _VOID = {"br", "img", "meta", "link", "input", "hr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[list[str], set[int], set[int], set[int]]] = []
        self._parts: list[tuple[str, bool, bool, bool]] = []
        self._depth = 0
        self._tags: list[tuple[str, set[str]]] = []

    def handle_starttag(self, tag, attrs):
        class_tokens = {token for key, value in attrs if key == "class" and value
                        for token in str(value).split()}
        if self._depth == 0 and tag == "div" and class_tokens.intersection({"outer-cell", "activity-container"}):
            self._depth = 1
            self._parts = []
            self._tags = [(tag, class_tokens)]
            return
        if self._depth and tag not in self._VOID:
            self._depth += 1
            self._tags.append((tag, class_tokens))

    def handle_endtag(self, tag):
        if not self._depth:
            return
        if tag in self._VOID:
            return
        if self._tags:
            self._tags.pop()
        self._depth -= 1
        if self._depth == 0:
            lines = [text for text, _is_time, _is_field, _is_chrome in self._parts]
            if lines:
                self.blocks.append((lines,
                    {i for i, (_text, is_time, _is_field, _is_chrome) in enumerate(self._parts) if is_time},
                    {i for i, (_text, _is_time, is_field, _is_chrome) in enumerate(self._parts) if is_field},
                    {i for i, (_text, _is_time, _is_field, is_chrome) in enumerate(self._parts) if is_chrome}))

    def handle_data(self, data):
        if self._depth and data.strip():
            tag, classes = self._tags[-1]
            ancestor_classes = set().union(*(tag_classes for _tag, tag_classes in self._tags))
            # In current Takeout the time is direct text in this cell; response
            # content after <br> lives in nested p/h3/pre/li nodes.
            is_time_field = (tag == "div" and (("content-cell" in classes
                              and "mdl-typography--body-1" in classes)
                             or "header-cell" in classes))
            is_current_provider_field = tag == "div" and "content-cell" in classes and "mdl-typography--body-1" in classes
            is_legacy_provider_label = (tag == "div" and len(self._tags) == 2 and re.match(
                r"^(?:Prompted|Gemini)(?:\s*[:：]\s*|\s*$)", data.strip(), re.I))
            is_provider_field = is_current_provider_field or bool(is_legacy_provider_label)
            # Google chrome is emitted inside header/caption containers.  The
            # identical words in a normal nested body node are user/answer text.
            is_chrome = bool({"header-cell", "mdl-typography--caption"}.intersection(ancestor_classes))
            self._parts.append((data.strip(), is_time_field, is_provider_field, is_chrome))


def _gemini_time(lines: list[str]) -> Optional[str]:
    for line in lines:
        m = _TIME_LINE.search(line)
        if m:
            return fmt_time(m.group(0))
    return None


def _gemini_visible_text(lines: list[str], marker: str, metadata_indexes: Optional[set[int]] = None,
                         provider_indexes: Optional[set[int]] = None,
                         chrome_indexes: Optional[set[int]] = None) -> str:
    out = []
    marker_re = re.compile(rf"^{re.escape(marker)}(?:\s*[:：]\s*|\s*$)", re.I)
    metadata_indexes = metadata_indexes or set()
    provider_indexes = provider_indexes or set()
    chrome_indexes = chrome_indexes or set()
    for index, line in enumerate(lines):
        if index in metadata_indexes or index in chrome_indexes:
            continue
        if index in provider_indexes:
            line = marker_re.sub("", line).strip()
            if re.match(rf"^{re.escape(marker)}\s+", line, re.I):
                line = re.sub(rf"^{re.escape(marker)}\s+", "", line, flags=re.I)
        # A bare provider word is structural only when the extractor proved
        # that this field is provider-owned; ordinary nested body text wins.
        if line and (index not in provider_indexes or line.lower() not in ("gemini", "prompted")):
            out.append(line)
    return "\n".join(out).strip()


def _gemini_answer_text(lines: list[str], metadata_indexes: Optional[set[int]] = None,
                        provider_indexes: Optional[set[int]] = None,
                        chrome_indexes: Optional[set[int]] = None) -> str:
    return _gemini_visible_text(lines, "Gemini", metadata_indexes, provider_indexes, chrome_indexes)


def _gemini_user_text(lines: list[str], provider_indexes: Optional[set[int]] = None,
                      chrome_indexes: Optional[set[int]] = None) -> str:
    out = []
    attachments = False
    provider_indexes = provider_indexes or set()
    chrome_indexes = chrome_indexes or set()
    for index, line in enumerate(lines):
        # The caller has already sliced away the one selected activity timestamp.
        # Date-like text inside a prompt is legitimate user content.
        if index in chrome_indexes:
            continue
        if index in provider_indexes and re.match(r"^Prompted(?:\s*[:：]\s*|\s*$)", line, re.I):
            line = re.sub(r"^Prompted(?:\s*[:：]\s*|\s*$)", "", line, flags=re.I)
        elif index in provider_indexes and re.match(r"^Prompted\s+", line, re.I):
            line = re.sub(r"^Prompted\s+", "", line, flags=re.I)
        if index in provider_indexes and re.match(r"^Attached\s+\d+\s+files?\.?", line, re.I):
            attachments = True
            continue
        if line and line != "-":
            out.append(f"[附件: {line}]" if attachments and index in provider_indexes else line)
    return "\n".join(out).strip()


def parse_gemini(path: Path) -> tuple:
    """Split Takeout activity containers; never invent a global conversation stream."""
    if path.is_file():
        target = path
    else:
        candidates = sorted(path.rglob("我的活动记录.html"))
        if not candidates:
            raise ImportError_("未找到 Gemini 活动文件")
        if len(candidates) > 1:
            raise ImportError_("Gemini 活动文件候选不唯一")
        target = candidates[0]
    try:
        parser = _GeminiActivityExtractor()
        parser.feed(target.read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        raise ImportError_(f"Gemini HTML UTF-8 解码失败：{target.name}")
    except OSError as e:
        raise ImportError_(f"无法读取 {target}：{e}")
    if not parser.blocks:
        raise ImportError_(f"{target} 未找到可靠的 Gemini 活动容器（请改用手工整理）")
    activities = []
    pending = None
    for lines, structural_time_indexes, provider_indexes, chrome_indexes in parser.blocks:
        prompt_indexes = [i for i, line in enumerate(lines)
                          if i in provider_indexes and (re.match(r"^Prompted(?:\s*[:：]|\s*$)", line, re.I)
                          or re.match(r"^Prompted\s+", line, re.I))]
        if len(prompt_indexes) > 1:
            raise ImportError_(f"{target} 存在多个结构化 Prompted 标记，无法可靠绑定活动（请改用手工整理）")
        is_prompt = bool(prompt_indexes)
        is_legacy_answer = any(i in provider_indexes and re.match(r"^Gemini(?:\s*[:：]|\s*$)", line, re.I)
                               for i, line in enumerate(lines))
        if is_prompt:
            if pending is not None:
                activities.append(pending)
            prompt_index = prompt_indexes[0]
            timestamp_indexes = [i for i in structural_time_indexes if i > prompt_index
                                 and _TIME_FIELD.fullmatch(lines[i])]
            # Bind only direct content-cell/body-1 timestamp fields. Dates in
            # nested answer markup (or in user fields) remain visible text.
            if len(timestamp_indexes) > 1:
                raise ImportError_(f"{target} 存在多个结构化活动时间，无法可靠绑定 Prompted 活动（请改用手工整理）")
            timestamp_index = timestamp_indexes[0] if timestamp_indexes else None
            legacy_timestamp_indexes = [i for i in structural_time_indexes if i <= prompt_index
                                        and _TIME_FIELD.fullmatch(lines[i])]
            legacy_time = (_gemini_time([lines[legacy_timestamp_indexes[0]]])
                           if len(legacy_timestamp_indexes) == 1 else None)
            user_lines = lines[prompt_index:timestamp_index] if timestamp_index is not None else lines[prompt_index:]
            end_index = timestamp_index if timestamp_index is not None else len(lines)
            text = _gemini_user_text(
                user_lines,
                {i - prompt_index for i in provider_indexes if prompt_index <= i < end_index},
                {i - prompt_index for i in chrome_indexes if prompt_index <= i < end_index})
            timestamp = _gemini_time([lines[timestamp_index]]) if timestamp_index is not None else legacy_time
            if not timestamp or not text:
                raise ImportError_(f"{target} 存在无法可靠绑定时间或正文的 Prompted 活动（请改用手工整理）")
            activity = {"time": timestamp, "user": text, "answer": None}
            if timestamp_index is not None:
                answer_start = timestamp_index + 1
                activity["answer"] = _gemini_answer_text(
                    lines[answer_start:],
                    provider_indexes={i - answer_start for i in provider_indexes if i >= answer_start},
                    chrome_indexes={i - answer_start for i in chrome_indexes if i >= answer_start})
                activities.append(activity)
                pending = None
            else:
                pending = activity
        elif is_legacy_answer:
            if pending is None:
                raise ImportError_(f"{target} 存在未绑定 Prompted 的 Gemini 回答（请改用手工整理）")
            answer = _gemini_visible_text(lines, "Gemini", structural_time_indexes, provider_indexes, chrome_indexes)
            if answer:
                pending["answer"] = answer
                activities.append(pending)
                pending = None
        # Non-Prompted Takeout activity rows are informational and intentionally ignored.
    if pending is not None:
        activities.append(pending)
    if not activities:
        raise ImportError_(f"{target} 未提取到任何 Prompted 活动")
    convs = []
    activity_occurrences: dict[str, int] = {}
    for activity in sorted(activities, key=lambda a: (a["time"], a["user"])):
        # Answers can arrive later in Takeout.  Prompt-side identity plus the
        # stable parse-order occurrence keeps that later answer an update.
        activity_key = f"{activity['time']}\x1f{activity['user']}"
        fingerprint = hashlib.sha1(activity_key.encode("utf-8")).hexdigest()[:16]
        occurrence = activity_occurrences.get(activity_key, 0) + 1
        activity_occurrences[activity_key] = occurrence
        cid = f"activity-{fingerprint}" + (f"--occurrence-{occurrence}" if occurrence > 1 else "")
        msgs = [("user", activity["time"], f"{cid}:user:1", activity["user"])]
        if activity["answer"]:
            msgs.append(("assistant", activity["time"], f"{cid}:assistant:2", activity["answer"]))
        convs.append(_make_conversation("gemini", cid, "Gemini 活动", msgs))
    return convs, [], len(activities)


# ---------- 解析器：DeepSeek ----------

def parse_deepseek(path: Path) -> tuple:
    """conversations.json（或 zip）：mapping 树 + fragments（REQUEST/RESPONSE/THINK/FILE）。"""
    data = None
    if path.is_dir():
        files = sorted(path.rglob("conversations.json"))
        if not files:
            raise ImportError_("未找到 DeepSeek conversations.json")
        if len(files) > 1:
            raise ImportError_("DeepSeek conversations.json 候选不唯一")
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_("无法读取 DeepSeek conversations.json")
    elif str(path).endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                names = sorted(n for n in z.namelist() if n.endswith("conversations.json"))
                if not names:
                    raise ImportError_("DeepSeek ZIP 未找到 conversations.json")
                if len(names) > 1:
                    raise ImportError_("DeepSeek ZIP conversations.json 候选不唯一")
                data = json.loads(z.read(names[0]).decode("utf-8"))
        except (OSError, RuntimeError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_("无法解压/读取 DeepSeek ZIP")
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_(f"无法读取 {path}：{e}")

    if not isinstance(data, list):
        raise ImportError_("conversations.json 顶层必须是会话列表")

    convs = []
    skipped = []
    tool_count = 0
    total = len(data or [])
    for conv in data or []:
        if not isinstance(conv, dict):
            skipped.append(("conversations.json", "会话条目结构损坏"))
            continue
        base = _usable_conversation_id(conv.get("id"))
        if base is None:
            skipped.append(("—", "DeepSeek 会话 ID 无效"))
            continue
        mapping = conv.get("mapping") or {}
        if not isinstance(mapping, dict) or any(not isinstance(node, dict) for node in mapping.values()):
            skipped.append(("—", "会话 mapping 结构损坏"))
            continue
        malformed_reason = None
        for node in mapping.values():
            msg = node.get("message")
            if msg is not None and not isinstance(msg, dict):
                malformed_reason = "会话消息结构损坏"
                break
            if isinstance(msg, dict):
                fragments = msg.get("fragments")
                if fragments is not None and not isinstance(fragments, list):
                    malformed_reason = "会话消息结构损坏"
                    break
                if isinstance(fragments, list):
                    visible_roles: set[str] = set()
                    for fragment in fragments:
                        if not isinstance(fragment, dict):
                            malformed_reason = "会话消息结构损坏"
                            break
                        ftype = fragment.get("type")
                        if not isinstance(ftype, str):
                            malformed_reason = "会话片段 type 结构损坏"
                            break
                        if ftype in ("REQUEST", "RESPONSE", "THINK"):
                            content = fragment.get("content")
                            if content is not None and not isinstance(content, str):
                                malformed_reason = f"会话片段 {ftype} content 不是字符串"
                                break
                            if ftype in ("REQUEST", "RESPONSE") and isinstance(content, str) and content.strip():
                                visible_roles.add(ftype)
                        if ftype == "FILE":
                            files = fragment.get("files")
                            if files is not None and (not isinstance(files, list)
                                                      or any(not isinstance(item, dict) for item in files)):
                                malformed_reason = "附件元数据结构损坏"
                                break
                            for item in files or []:
                                value = item.get("file_name") or item.get("file_id")
                                if not isinstance(value, (str, int, float)):
                                    malformed_reason = "附件元数据结构损坏"
                                    break
                        if malformed_reason:
                            break
                    if not malformed_reason and len(visible_roles) > 1:
                        malformed_reason = "会话节点混合 REQUEST/RESPONSE 可见内容"
                if malformed_reason:
                    break
        if malformed_reason:
            skipped.append(("—", malformed_reason))
            continue
        try:
            paths = _root_to_leaf_paths(mapping)
        except ImportError_ as e:
            skipped.append(("—", "会话 mapping 结构损坏"))
            continue
        outputs = []
        counted_fragments: set[tuple[str, int]] = set()
        for node_path in paths:
            msgs = []
            for nid in node_path:
                node = mapping[nid]
                msg = node.get("message") or {}
                t = fmt_time(msg.get("inserted_at"))
                role = None
                text_parts: list[str] = []
                for fragment_index, fr in enumerate(msg.get("fragments") or []):
                    if not isinstance(fr, dict):
                        continue
                    ftype = fr.get("type")
                    content = fr.get("content")
                    content = content.strip() if isinstance(content, str) else ""
                    if ftype == "REQUEST":
                        if content:
                            role = "user"
                            text_parts.append(content)
                    elif ftype == "RESPONSE":
                        if content:
                            role = "assistant"
                            text_parts.append(content)
                    elif ftype == "THINK":
                        if _INCLUDE_THINKING and content:
                            text_parts.append("<!-- thinking -->\n" + content)
                        elif content and (nid, fragment_index) not in counted_fragments:
                            skipped.append(("—", "内部内容已排除：THINK"))
                            counted_fragments.add((nid, fragment_index))
                    elif ftype == "FILE":
                        for fi in fr.get("files") or []:
                            value = fi.get("file_name") or fi.get("file_id")
                            if isinstance(value, (str, int, float)):
                                text_parts.append(f"[附件: {value}]")
                            else:
                                skipped.append(("—", "附件元数据结构损坏"))
                    elif ftype in ("SEARCH", "TOOL_SEARCH", "TOOL_OPEN"):
                        if (nid, fragment_index) not in counted_fragments:
                            tool_count += 1
                            counted_fragments.add((nid, fragment_index))
                    else:
                        if (nid, fragment_index) not in counted_fragments:
                            skipped.append(("—", "未识别 DeepSeek 片段"))
                            counted_fragments.add((nid, fragment_index))
                # Tool-only nodes retain their graph position but never become body text.
                if role is not None and text_parts:
                    msgs.append((role, t, str(nid), "\n\n".join(text_parts).strip()))
            if msgs:
                outputs.append((node_path, msgs))
        if not outputs:
            skipped.append(("—", SKIP_EMPTY))
            continue
        branching = len(outputs) > 1
        for index, (node_path, msgs) in enumerate(outputs, 1):
            cid = f"{base}--branch-{_path_fingerprint(node_path)}" if branching else base
            title = _safe_title(conv.get("title"))
            if branching:
                title += f"（分支 {index}）"
            convs.append(_make_conversation("deepseek", cid, title, msgs))
    if tool_count:
        skipped.append(("—", f"工具片段 {tool_count} 条（SEARCH/TOOL_SEARCH/TOOL_OPEN）已识别，不纳入蒸馏正文"))
    return convs, skipped, total


# ---------- 解析器：本地 Codex ----------

# Only confirmed outer envelopes are removed.  Generic XML names are user content.
_CODEX_ENVELOPE_TAGS = (
    "environment_context", "recommended_plugins", "heartbeat", "in-app-browser-context",
    "skills_instructions", "plugins_instructions", "apps_instructions", "permissions_instructions",
    "external_codex_apps_writing_block_edits_part_1_of_3",
    "external_codex_apps_writing_block_edits_part_2_of_3",
    "external_codex_apps_writing_block_edits_part_3_of_3",
)
_CODEX_ENVELOPE_RE = {tag: re.compile(rf"^\s*<{tag}\b[^>]*>(.*?)</{tag}>\s*", re.I | re.S)
                      for tag in _CODEX_ENVELOPE_TAGS}
_CODEX_IMAGE_PLACEHOLDER_RE = re.compile(
    r"<image\b(?=[^>]*\bname\s*=\s*\[Image\s+#\d+\])[^>]*>(?:.*?</image\s*>)?", re.S)
_CODEX_AGENTS_RE = re.compile(
    r"^\s*#\s*AGENTS\.md instructions[^\n]*\n\s*<INSTRUCTIONS\b[^>]*>.*?</INSTRUCTIONS>\s*",
    re.I | re.S)
_CODEX_ABORT_RE = re.compile(r"^\s*<turn_aborted\b[^>]*>.*?(?:</turn_aborted>|$)\s*$", re.I | re.S)
_CODEX_PREFIX_RECORDS = ("# Files mentioned by the user:", "# In app browser:")


def _clean_codex_user(text: str, events: Optional[list[str]] = None) -> str:
    if _CODEX_ABORT_RE.match(text) or _is_known_codex_automation(text):
        if events is not None:
            events.append("内部内容已排除：Codex 中断或自动化注入")
        return ""
    while True:
        before = text
        text, agents_removed = _CODEX_AGENTS_RE.subn("", text)
        if agents_removed and events is not None:
            events.append("内部内容已排除：Codex AGENTS 包装")
        for tag, pat in _CODEX_ENVELOPE_RE.items():
            match = pat.match(text)
            if match and _is_known_codex_envelope(tag, match.group(1)):
                text = text[match.end():]
                if events is not None:
                    events.append("内部内容已排除：Codex 系统包装")
        if text == before:
            break
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if (_is_incomplete_codex_envelope(text)
            or re.match(r"^#\s*AGENTS\.md instructions\b", first, re.I)):
        if events is not None:
            events.append("内部内容已排除：Codex 残留未闭合系统包装")
        return ""
    if first in _CODEX_PREFIX_RECORDS:
        if events is not None:
            events.append("内部内容已排除：Codex 前置文件或浏览器上下文")
        return ""
    text = _CODEX_IMAGE_PLACEHOLDER_RE.sub("[图片]", text)
    return text.strip()


def _is_known_codex_envelope(tag: str, body: str) -> bool:
    """Require a provider-specific payload signature, never tag name alone."""
    lowered = body.lower()
    if tag == "environment_context":
        return _codex_system_field_count(body) >= 2
    return _has_codex_envelope_signature(tag, lowered)


_CODEX_SYSTEM_FIELDS = {
    "cwd", "shell", "current_date", "timezone", "filesystem", "file_system",
    "permission_profile", "workspace_roots", "approval_policy", "sandbox_mode", "network_access",
}


def _codex_system_field_count(body: str) -> int:
    found = {name.lower() for name in re.findall(r"<([\w-]+)\b", body)
             if name.lower() in _CODEX_SYSTEM_FIELDS}
    return len(found)


def _has_codex_envelope_signature(tag: str, lowered_body: str) -> bool:
    """Known non-XML payload markers also identify incomplete injected envelopes."""
    if tag == "recommended_plugins":
        return "available but not installed" in lowered_body or "plugin_id" in lowered_body
    if tag == "skills_instructions":
        return "## skills" in lowered_body
    if tag == "plugins_instructions":
        return "## plugins" in lowered_body
    if tag == "apps_instructions":
        return "apps (connectors)" in lowered_body
    if tag == "permissions_instructions":
        return "permission_profile" in lowered_body or "permissions" in lowered_body
    if tag == "in-app-browser-context":
        return "browser" in lowered_body or "ref_id" in lowered_body
    if tag == "heartbeat":
        return all(marker in lowered_body for marker in ("automation_id", "current_time_iso", "instructions"))
    if tag.startswith("external_codex_apps_writing_block_edits_part_"):
        markers = ("block", "edit", "writing")
        return (all(marker in lowered_body for marker in markers)
                and ("part_2" not in tag or "mcp" in lowered_body))
    return False


def _is_incomplete_codex_envelope(text: str) -> bool:
    """Fail closed only for a leading, schema-proven wrapper lacking its closer."""
    match = re.match(r"^\s*<([\w-]+)\b[^>]*>(.*)$", text, re.I | re.S)
    if not match or match.group(1).lower() not in _CODEX_ENVELOPE_TAGS:
        return False
    tag, body = match.group(1).lower(), match.group(2)
    if re.search(rf"</{re.escape(tag)}\s*>", body, re.I):
        return False
    if tag == "environment_context":
        return _codex_system_field_count(body) >= 2
    return _has_codex_envelope_signature(tag, body.lower())


def _is_known_codex_automation(text: str) -> bool:
    if not text.lstrip().startswith("Automation:"):
        return False
    return bool(re.search(r"<(?:automation_id|current_time_iso)\b", text, re.I)
                or re.match(r"^\s*Automation:\s*(?:Personal context|Daily observer|Weekly reflection)\b", text, re.I))


def _codex_text(content) -> str:
    return _codex_text_with_events(content, None)


def _codex_text_with_events(content, events: Optional[list[str]]) -> str:
    parts = []
    for c in content or []:
        if not isinstance(c, dict):
            if events is not None:
                events.append("未知 Codex 内容块类型")
            continue
        raw_ctype = c.get("type")
        ctype = raw_ctype.lower() if isinstance(raw_ctype, str) else ""
        if ctype in ("input_text", "output_text"):
            if "text" in c:
                if not isinstance(c["text"], str):
                    if events is not None:
                        events.append(f"内容块结构损坏：Codex {ctype} text 不是字符串")
                elif c["text"]:
                    parts.append(c["text"])
        elif ctype in ("input_image", "output_image", "image"):
            parts.append("[图片]")
        elif events is not None:
            events.append("未知 Codex 内容块类型")
    return "\n".join(parts).strip()


def _codex_session_id(path: Path) -> str:
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(d, dict):
                    continue
                if d.get("type") == "session_meta":
                    payload = d.get("payload")
                    pid = payload.get("id") if isinstance(payload, dict) else None
                    if isinstance(pid, (str, int, float)) and not isinstance(pid, bool) and str(pid).strip():
                        return str(pid)
                break
    except (OSError, UnicodeDecodeError):
        pass
    return path.stem.removeprefix("rollout-") or path.stem


_CODEX_KNOWN_TOP_LEVEL_TYPES = {
    "session_meta", "turn_context", "event_msg", "compacted",
    "inter_agent_communication_metadata", "world_state",
}
_CODEX_KNOWN_RESPONSE_PAYLOAD_TYPES = {
    "agent_message", "custom_tool_call", "custom_tool_call_output",
    "function_call", "function_call_output", "image_generation_call",
    "reasoning", "tool_search_call", "tool_search_output", "web_search_call",
}


def parse_codex(path: Path, events: Optional[list[str]] = None) -> Optional[list]:
    cid = _codex_session_id(path)
    msgs: list = []
    try:
        fh = path.open(encoding="utf-8")
    except OSError as e:
        raise ImportError_("无法读取 Codex JSONL")
    try:
        with fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    if events is not None:
                        events.append(f"损坏 JSONL 行：Codex 第 {i} 行")
                    continue
                if not isinstance(d, dict):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Codex 第 {i} 行")
                    continue
                raw_top_type = d.get("type")
                top_type = raw_top_type if isinstance(raw_top_type, str) else ""
                if top_type in _CODEX_KNOWN_TOP_LEVEL_TYPES:
                    if events is not None:
                        events.append("内部内容已排除：Codex 已知顶层记录")
                    continue
                if top_type != "response_item":
                    if events is not None:
                        events.append("未知 Codex 顶层记录类型")
                    continue
                raw_payload = d.get("payload")
                if raw_payload is not None and not isinstance(raw_payload, dict):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Codex 第 {i} 行 payload 不是对象")
                    continue
                payload = raw_payload or {}
                if not isinstance(payload, dict):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Codex 第 {i} 行 payload 不是对象")
                    continue
                raw_payload_type = payload.get("type")
                payload_type = raw_payload_type if isinstance(raw_payload_type, str) else ""
                if payload_type in _CODEX_KNOWN_RESPONSE_PAYLOAD_TYPES:
                    if events is not None:
                        events.append("内部内容已排除：Codex 已知响应记录")
                    continue
                if payload_type != "message":
                    if events is not None:
                        events.append("未知 Codex 响应记录类型")
                    continue
                raw_role = payload.get("role")
                role = raw_role.lower() if isinstance(raw_role, str) else ""
                if role in ("developer", "system"):
                    if events is not None:
                        events.append("内部内容已排除：Codex developer/system 消息")
                    continue
                if role not in ("user", "assistant"):
                    if events is not None:
                        events.append("未知 Codex 消息角色")
                    continue
                content = payload.get("content")
                if content is not None and not isinstance(content, list):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Codex 第 {i} 行 content 不是列表")
                    continue
                text = _codex_text_with_events(content, events)
                if role == "user":
                    text = _clean_codex_user(text, events)
                if not text:
                    continue
                mid = (_safe_scalar(payload.get("id"))
                       or _occurrence_id(role, d.get("timestamp"), i, text))
                msgs.append((role, fmt_time(d.get("timestamp")), mid, text))
    except UnicodeDecodeError:
        raise ImportError_("Codex JSONL UTF-8 解码失败")
    if not msgs:
        return None
    title = _first_user_snippet(msgs) or path.stem
    return [_make_conversation("codex", cid, title, msgs)]


# ---------- 解析器：本地 Claude Code ----------

_CLAUDE_INTERNAL_BLOCK = re.compile(
    r"\s*<(command-name|command-message|command-args|local-command-caveat)\b[^>]*>.*?</\1>", re.I | re.S)
_CLAUDE_TASK_NOTIFICATION = re.compile(r"^\s*<task-notification\b[^>]*>.*?</task-notification>\s*$", re.I | re.S)


def _is_claude_internal_user_record(text: str) -> bool:
    if _CLAUDE_TASK_NOTIFICATION.match(text):
        return True
    pos = 0
    blocks = 0
    while True:
        match = _CLAUDE_INTERNAL_BLOCK.match(text, pos)
        if not match:
            break
        blocks += 1
        pos = match.end()
    return bool(blocks and not text[pos:].strip())

_CLAUDE_KNOWN_NON_MESSAGE_TYPES = {
    "system", "mode", "permission-mode", "file-history-snapshot", "ai-title",
    "last-prompt", "attachment", "queue-operation", "summary",
}
_CLAUDE_KNOWN_CONTENT_BLOCK_TYPES = {"tool_result", "tool_use", "thinking"}


def _claude_content_text(content, events: Optional[list[str]]) -> tuple[str, bool]:
    """Keep visible text blocks while accounting for known/unknown structured blocks."""
    if isinstance(content, str):
        return content.strip(), True
    if not isinstance(content, list):
        return "", content is None
    parts = []
    for block in content:
        if not isinstance(block, dict):
            if events is not None:
                events.append("未知 Claude 内容块类型")
            continue
        raw_block_type = block.get("type")
        block_type = raw_block_type if isinstance(raw_block_type, str) else ""
        if not block_type:
            if events is not None:
                events.append("未知 Claude 内容块类型")
            continue
        if block_type == "text":
            text = block.get("text")
            if not isinstance(text, str):
                if events is not None:
                    events.append("内容块结构损坏：Claude text 内容块 text 不是字符串")
            elif text:
                parts.append(text)
        elif block_type == "image":
            # Never stringify source/base64 fields from a local image block.
            parts.append("[图片]")
        elif block_type in _CLAUDE_KNOWN_CONTENT_BLOCK_TYPES:
            if events is not None:
                events.append(f"内部内容已排除：Claude {block_type} 内容块")
        elif events is not None:
            events.append("未知 Claude 内容块类型")
    return "\n".join(parts).strip(), True


def parse_claude(path: Path, events: Optional[list[str]] = None) -> Optional[list]:
    cid = path.stem
    msgs: list = []
    try:
        fh = path.open(encoding="utf-8")
    except OSError as e:
        raise ImportError_("无法读取 Claude JSONL")
    try:
        with fh:
            for i, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    if events is not None:
                        events.append(f"损坏 JSONL 行：Claude 第 {i} 行")
                    continue
                if not isinstance(d, dict):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Claude 第 {i} 行")
                    continue
                if d.get("isMeta") is True:
                    if events is not None:
                        events.append("内部内容已排除：Claude isMeta")
                    continue
                if d.get("isSidechain") is True:
                    if events is not None:
                        events.append("内部内容已排除：Claude isSidechain")
                    continue
                dtype = d.get("type")
                if not isinstance(dtype, str):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Claude 第 {i} 行 type 不是字符串")
                    continue
                if dtype not in ("user", "assistant"):
                    if events is not None:
                        if dtype in _CLAUDE_KNOWN_NON_MESSAGE_TYPES:
                            events.append("内部内容已排除：Claude 已知非消息记录")
                        else:
                            events.append("未知 Claude 顶层记录类型")
                    continue
                raw_message = d.get("message")
                if raw_message is not None and not isinstance(raw_message, dict):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Claude 第 {i} 行 message 不是对象")
                    continue
                m = raw_message or {}
                if not isinstance(m, dict):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Claude 第 {i} 行 message 不是对象")
                    continue
                raw_role = m.get("role", dtype)
                role = raw_role.lower() if isinstance(raw_role, str) else ""
                if role not in ("user", "assistant"):
                    if events is not None:
                        events.append("未知 Claude 消息角色")
                    continue
                content = m.get("content")
                if content is not None and not isinstance(content, (str, list)):
                    if events is not None:
                        events.append(f"结构损坏 JSONL 行：Claude 第 {i} 行 content 结构无效")
                    continue
                text, content_handled = _claude_content_text(content, events)
                if role == "user":
                    if re.match(r"^claude(?:\s+--?[\w-]+(?:\s+\S+)?)*\s*$", text):
                        if events is not None:
                            events.append("内部内容已排除：Claude CLI/resume")
                        continue  # CLI 调用/resume 行，不是真实内容
                    if _is_claude_internal_user_record(text):
                        if events is not None:
                            events.append("内部内容已排除：Claude 命令或任务通知")
                        continue  # known whole-record internal notification
                if not text:
                    if content is not None and not content_handled and events is not None:
                        events.append("未知内部记录告警：Claude 未识别消息内容")
                    continue
                mid = (_safe_scalar(d.get("uuid"))
                       or _occurrence_id(role, d.get("timestamp"), i, text))
                msgs.append((role, fmt_time(d.get("timestamp")), mid, text))
    except UnicodeDecodeError:
        raise ImportError_("Claude JSONL UTF-8 解码失败")
    if not msgs:
        return None
    title = _first_user_snippet(msgs) or path.stem
    return [_make_conversation("claude", cid, title, msgs)]


def _first_user_snippet(msgs: list) -> str:
    for role, _t, _mid, text in msgs:
        if role == "user":
            one = text.replace("\n", " ").strip()
            return one[:40] + ("…" if len(one) > 40 else "")
    return ""


# ---------- 写入：权限 0700/0600 + 原子写入 + 增量去重 ----------

def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        os.fchmod(fd, mode)
        f = os.fdopen(fd, "w", encoding="utf-8")
        fd = None
        with f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.chmod(path, mode)


def imported_path(out_dir: Path) -> Path:
    return out_dir / ".imported.json"


def _assert_safe_output_root(out_dir: Path) -> None:
    if out_dir.is_symlink():
        raise ImportError_("输出根目录是符号链接，拒绝访问")
    absolute = out_dir.absolute()
    trusted = [ROOT.absolute(), Path.cwd().absolute(), Path.home().absolute(),
               Path(tempfile.gettempdir()).absolute()]
    bases = []
    for base in trusted:
        try:
            absolute.relative_to(base)
            bases.append(base)
        except ValueError:
            continue
    base = max(bases, key=lambda candidate: len(candidate.parts)) if bases else Path(absolute.anchor)
    current = base
    for part in absolute.relative_to(base).parts:
        current /= part
        if current.is_symlink():
            raise ImportError_("输出根目录祖先是符号链接，拒绝访问")
    if imported_path(out_dir).is_symlink():
        raise ImportError_("状态文件是符号链接，拒绝访问")


def load_imported(out_dir: Path) -> dict:
    _assert_safe_output_root(out_dir)
    p = imported_path(out_dir)
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ImportError_("状态文件损坏或 UTF-8 解码失败，未修改")
        if not isinstance(data, dict):
            raise ImportError_("状态文件结构损坏，未修改（期望 JSON 对象）")
        for key, entry in data.items():
            if not isinstance(key, str) or ":" not in key:
                raise ImportError_("状态文件结构损坏，未修改（会话键无效）")
            state_source, state_cid = key.split(":", 1)
            if not state_source or not state_cid:
                raise ImportError_("状态文件结构损坏，未修改（会话键无效）")
            if not isinstance(entry, dict):
                raise ImportError_("状态文件结构损坏，未修改（会话记录不是对象）")
            path = entry.get("path")
            imported_at = entry.get("imported_at")
            title = entry.get("title")
            message_ids = entry.get("message_ids")
            if (not isinstance(path, str) or not path or not isinstance(imported_at, str)
                    or not isinstance(title, str) or not isinstance(message_ids, list)
                    or any(not isinstance(mid, str) or not mid for mid in message_ids)
                    or len(message_ids) != len(set(message_ids))):
                raise ImportError_("状态文件结构损坏，未修改（会话字段无效）")
        return data
    return {}


def save_imported(imported: dict, out_dir: Path) -> None:
    _assert_safe_output_root(out_dir)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    _atomic_write(imported_path(out_dir), json.dumps(imported, ensure_ascii=False, indent=2) + "\n")


def _format_message(role: str, t: Optional[str], mid: str, text: str) -> str:
    tstr = t or "（未知）"
    return f"**{role}**（{tstr}；message_id: {_markdown_metadata(mid)}）：\n{_escape_managed_markers(text)}"


def _render_messages(msgs: list) -> str:
    return "\n\n".join(_format_message(*m) for m in msgs)


def _escape_managed_markers(text: str) -> str:
    """Keep user text visible without allowing it to forge writer delimiters."""
    text = _normalize_message_text(text)
    return (text.replace("<!-- distill-messages:begin -->", "&lt;!-- distill-messages:begin --&gt;")
                .replace("<!-- distill-messages:end -->", "&lt;!-- distill-messages:end --&gt;"))


def _markdown_metadata(value) -> str:
    """Render IDs in one inert Markdown line while preserving safe normal IDs."""
    text = str(value).replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n")
    return (text.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;"))


def _managed_parts(content: str, path: Path) -> tuple[str, str, str]:
    begin = "<!-- distill-messages:begin -->"
    end = "<!-- distill-messages:end -->"
    if content.count(begin) != 1 or content.count(end) != 1:
        raise ImportError_("现有 Markdown 的消息标记损坏，拒绝覆盖")
    if content.find(begin) > content.find(end):
        raise ImportError_("现有 Markdown 的消息标记顺序损坏，拒绝覆盖")
    before, rest = content.split(begin, 1)
    body, after = rest.split(end, 1)
    return before, body.strip("\n"), after


def _state_entry(path: Path, title: str, msgs: list) -> dict:
    return {
        "path": str(path), "imported_at": today_str(), "title": title,
        "message_ids": [m[2] for m in msgs],
    }


def _same_path(left, right) -> bool:
    return os.path.abspath(os.fspath(left)) == os.path.abspath(os.fspath(right))


def _assert_no_filename_collision(source: str, cid: str, key: str, path: Path,
                                  imported: dict) -> None:
    """Fail closed when lossy filename sanitization would target another conversation."""
    for other_key, entry in imported.items():
        if other_key != key and isinstance(entry, dict) and isinstance(entry.get("path"), str):
            if _same_path(entry["path"], path):
                raise ImportError_("文件名冲突：目标文件已被其他会话占用")
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8")
    old_sources = re.findall(r"^<!-- source: (.*?) -->\s*$", content, re.MULTILINE)
    old_cids = re.findall(r"^<!-- conversation_id: (.*?) -->\s*$", content, re.MULTILINE)
    if len(old_sources) != 1 or len(old_cids) != 1:
        raise ImportError_("文件名冲突：现有目标缺少或重复所有权元数据")
    if (old_sources[0], old_cids[0]) != (_markdown_metadata(source), _markdown_metadata(cid)):
        raise ImportError_("文件名冲突：现有目标所有权不匹配")


def _claim_dry_run_output(conv: tuple, imported: dict, out_dir: Path) -> None:
    """Record an in-memory output claim so dry-run reports later collisions."""
    source, cid, title, _exported_at, msgs = conv
    path = out_dir / f"{source}-{_sanitize_filename(cid)}.md"
    imported[f"{source}:{cid}"] = _state_entry(path, title, msgs)


def write_conversation(conv: tuple, imported: dict, out_dir: Path, dry_run: bool = False) -> str:
    """Markdown is the source of truth; state is reconstructed from its final block."""
    source, cid, title, exported_at, msgs = conv
    _assert_safe_output_root(out_dir)
    key = f"{source}:{cid}"
    ids = [m[2] for m in msgs]
    if len(ids) != len(set(ids)):
        raise ImportError_("会话出现重复 message_id，拒绝写入")
    path = out_dir / f"{source}-{_sanitize_filename(cid)}.md"
    if path.is_symlink():
        raise ImportError_("输出目标是符号链接，拒绝写入")
    _assert_no_filename_collision(source, cid, key, path, imported)
    desired = _render_messages(msgs)
    result = "new"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        before, existing_body, after = _managed_parts(existing, path)
        if existing_body == desired:
            if not dry_run:
                os.chmod(out_dir, 0o700)
                os.chmod(path, 0o600)
                imported[key] = _state_entry(path, title, msgs)
            return "dup"
        result = "update"
        content = before + "<!-- distill-messages:begin -->\n" + desired + "\n<!-- distill-messages:end -->" + after
    else:
        content = _build_content(source, cid, title, exported_at, msgs)
    if dry_run:
        return result
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    _atomic_write(path, content)
    imported[key] = _state_entry(path, title, msgs)
    return result


def _build_content(source: str, cid: str, title: str, exported_at: str, msgs: list) -> str:
    lines = [f"# {_escape_managed_markers(source)} · {_escape_managed_markers(title)}", "",
             f"<!-- source: {_markdown_metadata(source)} -->",
             f"<!-- conversation_id: {_markdown_metadata(cid)} -->",
             f"<!-- exported_at: {exported_at} -->",
             "", "<!-- distill-messages:begin -->"]
    if msgs:
        lines.append(_render_messages(msgs))
    lines.append("<!-- distill-messages:end -->")
    return "\n".join(lines)


# ---------- 本地主动发现 ----------

def discover_local(since: Optional[str] = None, excludes: tuple = (), roots: tuple = LOCAL_ROOTS,
                   failures: Optional[list[tuple[str, str]]] = None) -> list:
    found = []
    for source, root_glob, pattern in roots:
        root = Path(os.path.expanduser(root_glob))
        if not root.is_dir():
            continue
        for p in sorted(root.rglob(pattern)):
            rel = str(p.relative_to(root))
            if any(fnmatch.fnmatch(rel, ex) for ex in excludes):
                continue
            try:
                size = p.stat().st_size
            except OSError:
                continue
            if size == 0:
                continue
            try:
                first_t, last_t, title = _peek(source, p)
            except ImportError_ as e:
                if failures is not None:
                    failures.append((p.name, str(e)))
                continue
            if since and (last_t or first_t or "") < since:
                continue
            found.append((source, _session_id(source, p), title, first_t, last_t, size, str(p)))
    return found


def _session_id(source: str, path: Path) -> str:
    if source == "codex":
        return _codex_session_id(path)
    return path.stem


def _peek(source: str, path: Path) -> tuple:
    """轻量读取：头 60 行 + 尾 30 行，拿时间与标题（dry-run 友好，长会话不因开头旧而被 --since 漏掉）。"""
    first_t = last_t = None
    title = ""
    head_lines: list[str] = []
    tail_lines: list[str] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i < 60:
                    head_lines.append(line)
                else:
                    tail_lines.append(line)
                    if len(tail_lines) > 30:
                        tail_lines.pop(0)
    except UnicodeDecodeError:
        raise ImportError_("本地 JSONL UTF-8 解码失败")
    except OSError:
        pass
    for line in head_lines + tail_lines:
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(d, dict):
            continue
        ts = d.get("timestamp")
        if ts:
            ft = fmt_time(ts)
            if ft and not first_t:
                first_t = ft
            if ft:
                last_t = ft
        if source == "codex":
            payload = d.get("payload")
            if not isinstance(payload, dict):
                continue
            if payload.get("type") == "message" and payload.get("role") == "user" and not title:
                content = payload.get("content")
                if not isinstance(content, list):
                    continue
                for c in content:
                    if (isinstance(c, dict) and c.get("type") == "input_text"
                            and isinstance(c.get("text"), str) and c["text"]):
                        t = _clean_codex_user(c["text"]).replace("\n", " ").strip()
                        if t:
                            title = t[:40] + ("…" if len(t) > 40 else "")
                        break
        elif source == "claude":
            if d.get("type") == "user" and not title:
                m = d.get("message")
                if not isinstance(m, dict):
                    continue
                content = m.get("content")
                if isinstance(content, str):
                    t = content.strip()
                elif isinstance(content, list):
                    t = " ".join(c["text"] for c in content
                                 if isinstance(c, dict) and c.get("type") == "text"
                                 and isinstance(c.get("text"), str)).strip()
                else:
                    t = ""
                if t and not re.match(r"^claude(?:\s+--?[\w-]+(?:\s+\S+)?)*\s*$", t):
                    title = t[:40] + ("…" if len(t) > 40 else "")
    return (first_t, last_t, title)


# ---------- 主流程 ----------

def run_source(source: str, path_arg: Optional[str], args, imported: dict,
               out_dir: Path) -> tuple:
    if source == "chatgpt":
        convs, skipped, total = parse_chatgpt(Path(path_arg))
    elif source == "gemini":
        convs, skipped, total = parse_gemini(Path(path_arg))
    elif source == "deepseek":
        convs, skipped, total = parse_deepseek(Path(path_arg))
    else:  # local
        since = args.since
        excludes = tuple(args.exclude or [])
        if args.path:
            found, discovery_failures = discover_local_path(Path(args.path), since, excludes, args.local_format)
            return run_local(found, args, imported, out_dir, discovery_failures)
        roots = LOCAL_ROOTS
        discovery_failures: list[tuple[str, str]] = []
        found = discover_local(since, excludes, roots, discovery_failures)
        return run_local(found, args, imported, out_dir, discovery_failures)
    return import_convs(convs, skipped, total, imported, out_dir, dry_run=args.dry_run)


def import_convs(convs: list, skipped: list, total: int, imported: dict,
                 out_dir: Path, dry_run: bool) -> tuple:
    new = updated = dup = 0
    seen_keys: set[str] = set()
    if total == 0 and not convs and not skipped:
        skipped.append(("导出文件", SKIP_EMPTY))
    for conv in convs:
        key = f"{conv[0]}:{conv[1]}"
        if key in seen_keys:
            skipped.append(("—", "写入失败：批次内重复会话键"))
            continue
        seen_keys.add(key)
        try:
            result = write_conversation(conv, imported, out_dir, dry_run)
        except (OSError, UnicodeDecodeError, ImportError_) as e:
            detail = str(e) if isinstance(e, ImportError_) else "输出写入失败"
            skipped.append(("—", f"写入失败：{detail}"))
            continue
        if dry_run:
            _claim_dry_run_output(conv, imported, out_dir)
        if result == "dup":
            dup += 1
        elif result == "update":
            updated += 1
        else:
            new += 1
    if not dry_run and (new or updated or dup):
        save_imported(imported, out_dir)
    return (total, new + updated + dup, new, updated, dup, skipped)


def run_local(found: list, args, imported: dict, out_dir: Path, discovery_failures: Optional[list] = None) -> tuple:
    discovery_failures = discovery_failures or []
    if not found:
        print("未发现可导入的本地会话（codex/claude）。")
        return (0, 0, 0, 0, 0, discovery_failures)
    total_size = sum(f[5] for f in found)
    print(f"发现 {len(found)} 个本地会话，总大小 {total_size / 1024:.0f} KB：")
    for source, sid, title, first_t, last_t, size, path in found:
        print(f"  [{source}] {title or sid}  {first_t or '?'} ~ {last_t or '?'}  {size}B  {path}")
    if args.dry_run:
        print("（--dry-run：完整解析和对账，未写入任何文件）")
    if not args.dry_run and not args.yes:
        try:
            ans = input(f"\n确认导入以上 {len(found)} 个会话？[y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("已取消。")
            return (len(found), 0, 0, 0, 0, [("—", SKIP_CANCELLED)])
    new = updated = dup = 0
    bad = list(discovery_failures)
    seen_keys: set[str] = set()
    for source, sid, title, first_t, last_t, size, path in found:
        events: list[str] = []
        try:
            convs = (parse_codex(Path(path), events) if source == "codex"
                     else parse_claude(Path(path), events))
        except ImportError_ as e:
            bad.append((sid, str(e)))
            continue
        bad.extend((sid, reason) for reason in events)
        if not convs:
            if not events:
                bad.append((sid, SKIP_EMPTY))
            continue
        key = f"{convs[0][0]}:{convs[0][1]}"
        if key in seen_keys:
            bad.append(("—", "写入失败：批次内重复会话键"))
            continue
        seen_keys.add(key)
        try:
            result = write_conversation(convs[0], imported, out_dir, args.dry_run)
        except (OSError, UnicodeDecodeError, ImportError_) as e:
            detail = str(e) if isinstance(e, ImportError_) else "输出写入失败"
            bad.append(("—", f"写入失败：{detail}"))
            continue
        if args.dry_run:
            _claim_dry_run_output(convs[0], imported, out_dir)
        if result == "dup":
            dup += 1
        elif result == "update":
            updated += 1
        else:
            new += 1
    if not args.dry_run and (new or updated or dup):
        save_imported(imported, out_dir)
    return (len(found), new + updated + dup, new, updated, dup, bad)


def _is_expected_exclusion(reason: str) -> bool:
    return reason.startswith("内部内容已排除") or reason.startswith("工具片段")


def _expected_exclusion_count(expected: list[tuple[str, str]]) -> int:
    count = 0
    for _ref, reason in expected:
        match = re.match(r"(?:工具片段\s+(\d+)\s+条|内部内容已排除：ChatGPT reasoning\s+(\d+)\s+个)", reason)
        count += int(match.group(1) or match.group(2)) if match else 1
    return count


def print_report(total: int, outputs: int, new: int, updated: int, dup: int, skipped: list, source: str,
                 dry_run: bool) -> None:
    expected = [(ref, reason) for ref, reason in skipped if _is_expected_exclusion(reason)]
    failures = [(ref, reason) for ref, reason in skipped if not _is_expected_exclusion(reason)]
    if dry_run:
        print(f"{source}：原始 {total} 个会话，输出 {outputs} 个会话；dry-run 预计新导入 {new}、更新 {updated}、重复 {dup}（未写入）")
    else:
        print(f"{source}：原始 {total} 个会话，输出 {outputs} 个会话 → 新导入 {new}、更新 {updated}、重复 {dup}"
              + ("（已导入过）" if dup else ""))
    if expected:
        print(f"  预期内部内容排除 {_expected_exclusion_count(expected)} 个片段（不计为失败）")
    by_reason: dict[str, int] = {}
    for _ref, reason in failures:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    if by_reason:
        detail = "；".join(reason + (f" ×{n}" if n > 1 else "") for reason, n in sorted(by_reason.items()))
        print(f"  解析/写入失败 {len(failures)}：{detail}")
    if not failures:
        print("完成。写入目录见各文件（本地处理，不上传）。")


def _classify_local_file(path: Path, forced: str) -> str:
    if forced != "auto":
        return forced
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if not line.strip():
                    continue
                record = json.loads(line)
                if not isinstance(record, dict):
                    raise ImportError_("无法识别本地 JSONL：记录不是对象")
                dtype = record.get("type")
                if dtype is not None and not isinstance(dtype, str):
                    raise ImportError_("无法识别本地 JSONL：type 不是字符串")
                if dtype in _CLAUDE_KNOWN_NON_MESSAGE_TYPES:
                    continue
                if dtype == "session_meta" or "payload" in record:
                    return "codex"
                if dtype in ("user", "assistant", "mode") or "message" in record:
                    return "claude"
    except UnicodeDecodeError:
        raise ImportError_("无法识别本地 JSONL：UTF-8 解码失败")
    except (OSError, json.JSONDecodeError):
        raise ImportError_("无法识别本地 JSONL：读取或 JSON 结构损坏")
    raise ImportError_("无法自动识别本地 JSONL；请使用 --local-format codex 或 claude")


def discover_local_path(root: Path, since: Optional[str], excludes: tuple, forced: str) -> tuple[list, list]:
    found, failures = [], []
    if not root.exists():
        return found, [(str(root), "本地路径不存在")]
    if root.is_file() and root.suffix != ".jsonl":
        return found, [(str(root), "本地路径不是 JSONL 会话")]
    if root.is_dir() and not any(root.rglob("*.jsonl")):
        return found, [(str(root), "本地路径未包含 JSONL 会话")]
    candidates = [root] if root.is_file() else sorted(root.rglob("*.jsonl"))
    for path in candidates:
        if path.suffix != ".jsonl":
            continue
        rel = path.name if root.is_file() else str(path.relative_to(root))
        if any(fnmatch.fnmatch(rel, ex) for ex in excludes):
            continue
        try:
            source = _classify_local_file(path, forced)
            size = path.stat().st_size
            first_t, last_t, title = _peek(source, path)
        except (ImportError_, OSError) as e:
            failures.append(("—", str(e) if isinstance(e, ImportError_) else "本地会话读取失败"))
            continue
        if since and (last_t or first_t or "") < since:
            continue
        found.append((source, _session_id(source, path), title, first_t, last_t, size, str(path)))
    return found, failures


def main() -> int:
    ap = argparse.ArgumentParser(description="selfdistill 全来源聊天导入器")
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--path", help="导出来源目录/文件；local 可覆盖扫描根")
    ap.add_argument("--since", help="仅导入该日期（YYYY-MM-DD）之后的本地会话")
    ap.add_argument("--exclude", action="append", help="本地发现排除 glob（可重复）")
    ap.add_argument("--local-format", choices=("auto", "codex", "claude"), default="auto",
                    help="local --path 的 JSONL 格式；默认按结构自动识别")
    ap.add_argument("--dry-run", action="store_true", help="只列清单/识别，不写文件")
    ap.add_argument("--yes", action="store_true", help="跳过确认直接导入")
    ap.add_argument("--include-thinking", action="store_true",
                    help="DeepSeek 包含 THINK 推理片段（默认排除）")
    ap.add_argument("--root", help="覆盖 input/ 根目录（测试用）")
    args = ap.parse_args()

    global _INCLUDE_THINKING
    _INCLUDE_THINKING = args.include_thinking

    out_dir = Path(args.root).expanduser() if args.root else INPUT_DIR
    try:
        # Even dry-run consults the Markdown truth and must not hide a corrupt state file.
        imported = load_imported(out_dir)
        if args.source == "local" and not args.path:
            path_arg = None
        else:
            if not args.path:
                ap.error(f"--source {args.source} 需要 --path")
            path_arg = args.path
        total, outputs, new, updated, dup, skipped = run_source(args.source, path_arg, args, imported, out_dir)
    except (ImportError_, OSError) as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    if any(reason == SKIP_CANCELLED for _ref, reason in skipped):
        return 0

    print_report(total, outputs, new, updated, dup, skipped, args.source, args.dry_run)
    failures = sum(1 for _ref, reason in skipped if not _is_expected_exclusion(reason))
    successes = new + updated + dup
    if failures:
        return 2 if successes else 1
    return 0


_INCLUDE_THINKING = False


if __name__ == "__main__":
    sys.exit(main())
