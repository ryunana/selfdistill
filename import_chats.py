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

def _stable_id(role: str, t: Optional[str], text: str) -> str:
    """稳定消息 id：无真实 id 时用内容指纹，保证增量去重不随行号漂移。"""
    return "fp-" + hashlib.sha1(f"{role}|{t or ''}|{text}".encode("utf-8")).hexdigest()[:12]


def _make_conversation(source: str, cid: str, title: str, msgs: list) -> tuple:
    title = " ".join(str(title).split())
    times = [t for _r, t, _m, _x in msgs if t]
    exported_at = times[-1][:10] if times else today_str()
    return (source, cid, title, exported_at, msgs)


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "conversation"


# ---------- 解析器：ChatGPT（沿活动路径，不压平分支） ----------

def parse_chatgpt(path: Path) -> tuple:
    """conversations-*.json：沿 current_node 的 parent 链取活动路径；无 current_node 时回退按时间。"""
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
        total += len(data or [])
        for conv in data or []:
            mapping = conv.get("mapping") or {}
            msgs = []
            current = conv.get("current_node")
            if current and current in mapping:
                node = mapping.get(current)
                chain = []
                while node and isinstance(node, dict):
                    msg = node.get("message")
                    if msg:
                        role = str(((msg.get("author") or {}).get("role") or "")).lower()
                        if role in ("user", "assistant"):
                            parts = (msg.get("content") or {}).get("parts") or []
                            text = "\n".join(str(p) for p in parts if p is not None).strip()
                            if text:
                                mid = str(msg.get("id") or node.get("id")) or _stable_id(role, None, text)
                                chain.append((role, fmt_time(msg.get("create_time")), mid, text))
                    parent = node.get("parent")
                    node = mapping.get(parent) if parent else None
                msgs = list(reversed(chain))
            else:
                for nid, node in mapping.items():
                    msg = (node or {}).get("message")
                    if not msg:
                        continue
                    role = str(((msg.get("author") or {}).get("role") or "")).lower()
                    if role not in ("user", "assistant"):
                        continue
                    parts = (msg.get("content") or {}).get("parts") or []
                    text = "\n".join(str(p) for p in parts if p is not None).strip()
                    if not text:
                        continue
                    mid = str(msg.get("id") or nid) or _stable_id(role, None, text)
                    msgs.append((role, fmt_time(msg.get("create_time")), mid, text))
                msgs.sort(key=lambda m: (m[1] or "9999", m[2] or ""))
            if not msgs:
                skipped.append((conv.get("title") or conv.get("id") or "?", SKIP_EMPTY))
                continue
            convs.append(_make_conversation("chatgpt", conv.get("id") or f.stem,
                                            conv.get("title") or "未命名会话", msgs))
    return convs, skipped, total


# ---------- 解析器：Gemini Takeout（按真实结构） ----------

class _TextExtractor(HTMLParser):
    BLOCK = {"div", "p", "br", "li", "h1", "h2", "h3", "h4", "h5", "tr", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self._skip_depth += 1
        if tag in self.BLOCK and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self.BLOCK and self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self.parts.append(text)

    def text(self) -> str:
        return "\n".join(self.parts)


_GEMINI_DROP_LINES = re.compile(
    r"^(Gemini Apps|商品：|详细信息：|为什么此处会显示此活动记录？|此处|控制这些设置)$")
_GEMINI_URL_LINE = re.compile(r"^https?://gemini\.google\.com/")


def parse_gemini(path: Path) -> tuple:
    """Takeout 我的活动记录.html：Prompted 开头为用户，时间戳行后为回复；附件与元数据行按规则处理。"""
    target = path if path.is_file() else next(iter(path.rglob("我的活动记录.html")), None)
    if target is None:
        raise ImportError_(f"未找到 我的活动记录.html：{path}")
    try:
        parser = _TextExtractor()
        parser.feed(target.read_text(encoding="utf-8", errors="replace"))
        text = parser.text()
    except OSError as e:
        raise ImportError_(f"无法读取 {target}：{e}")
    if "Prompted" not in text:
        raise ImportError_(f"{target} 中未找到 Prompted 轮次标记（结构未能识别）")

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]

    def is_boundary(ln: str) -> bool:
        return (ln.lower().startswith("prompted") or _GEMINI_DROP_LINES.match(ln)
                or _GEMINI_URL_LINE.match(ln))

    msgs: list = []
    i = 0
    pending_header_time: Optional[str] = None
    while i < len(lines):
        ln = lines[i]
        if ln.lower().startswith("prompted"):
            # 用户消息：Prompted 行 + 后续续行，直到时间戳/附件/元数据边界
            user_text = re.sub(r"^[Pp]rompted\s*[:：]?\s*", "", ln).strip()
            i += 1
            while i < len(lines):
                nxt = lines[i]
                if is_boundary(nxt) or _TIME_LINE.search(nxt):
                    break
                if nxt.lower().startswith("attached "):
                    break
                user_text += "\n" + nxt
                i += 1
            # 附件：Attached N files. 后跟文件名
            if i < len(lines) and lines[i].lower().startswith("attached "):
                i += 1
                while i < len(lines) and not (_TIME_LINE.search(lines[i])
                                              or is_boundary(lines[i])):
                    if not _GEMINI_DROP_LINES.match(lines[i]) and lines[i] != "-":
                        user_text += f"\n[附件: {lines[i]}]"
                    i += 1
            if user_text.strip():
                msgs.append(("user", pending_header_time,
                             _stable_id("user", None, user_text.strip()), user_text.strip()))
            pending_header_time = None
            continue
        if _TIME_LINE.search(ln):
            t = fmt_time(ln.strip())
            i += 1
            buf = []
            while i < len(lines):
                nxt = lines[i]
                if is_boundary(nxt):
                    break
                buf.append(nxt)
                i += 1
            body = "\n".join(buf).strip()
            if body:
                msgs.append(("assistant", t, _stable_id("assistant", t, body), body))
            elif t:
                pending_header_time = t  # 无正文的时间行：作为下一条用户消息的头部时间
            continue
        i += 1

    if not msgs:
        raise ImportError_(f"{target} 未提取到任何 Prompted/Gemini 消息")
    cid = target.stem or "gemini-export"
    return [_make_conversation("gemini", cid, "Gemini 会话", msgs)], [], 1


# ---------- 解析器：DeepSeek ----------

def parse_deepseek(path: Path) -> tuple:
    """conversations.json（或 zip）：mapping 树 + fragments（REQUEST/RESPONSE/THINK/FILE）。"""
    data = None
    if path.is_dir():
        files = list(path.rglob("conversations.json"))
        if not files:
            raise ImportError_(f"未找到 conversations.json：{path}")
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_(f"无法读取 {files[0]}：{e}")
    elif str(path).endswith(".zip"):
        try:
            with zipfile.ZipFile(path) as z:
                name = next((n for n in z.namelist() if n.endswith("conversations.json")), None)
                if name is None:
                    raise ImportError_(f"压缩包中未找到 conversations.json：{path}")
                data = json.loads(z.read(name).decode("utf-8"))
        except (OSError, zipfile.BadZipFile, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_(f"无法解压/读取 {path}：{e}")
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_(f"无法读取 {path}：{e}")

    convs = []
    skipped = []
    tool_count = 0
    total = len(data or [])
    for conv in data or []:
        mapping = conv.get("mapping") or {}
        msgs = []
        for nid, node in mapping.items():
            msg = (node or {}).get("message")
            if not msg:
                continue
            t = fmt_time(msg.get("inserted_at"))
            role = None
            text_parts: list[str] = []
            for fr in msg.get("fragments") or []:
                ftype = fr.get("type")
                content = str(fr.get("content") or "").strip()
                if ftype == "REQUEST":
                    role = "user"
                    if content:
                        text_parts.append(content)
                elif ftype == "RESPONSE":
                    role = "assistant"
                    if content:
                        text_parts.append(content)
                elif ftype == "THINK":
                    if _INCLUDE_THINKING and content:
                        text_parts.append("<!-- thinking -->\n" + content)
                elif ftype == "FILE":
                    for fi in fr.get("files") or []:
                        text_parts.append(f"[附件: {fi.get('file_name') or fi.get('file_id')}]")
                elif ftype in ("SEARCH", "TOOL_SEARCH", "TOOL_OPEN"):
                    tool_count += 1  # 工具片段：已识别并计数，不纳入蒸馏正文
                else:
                    skipped.append((conv.get("title") or nid, SKIP_UNKNOWN))
            if role is None or not text_parts:
                continue
            msgs.append((role, t, str(nid), "\n\n".join(text_parts).strip()))
        if not msgs:
            skipped.append((conv.get("title") or conv.get("id") or "?", SKIP_EMPTY))
            continue
        msgs.sort(key=lambda m: (m[1] or "9999", m[2] or ""))
        convs.append(_make_conversation("deepseek", conv.get("id") or "unknown",
                                        conv.get("title") or "未命名会话", msgs))
    if tool_count:
        skipped.append(("—", f"工具片段 {tool_count} 条（SEARCH/TOOL_SEARCH/TOOL_OPEN）已识别，不纳入蒸馏正文"))
    return convs, skipped, total


# ---------- 解析器：本地 Codex ----------

# Codex 系统注入块标签（真实会话中出现的全部标签）
_SYSTEM_TAGS = [
    "environment_context", "recommended_plugins", "heartbeat", "in-app-browser-context",
    "root", "automation_id", "current_time_iso", "instructions", "current_date", "timezone",
    "filesystem", "workspace_roots", "cwd", "shell", "INSTRUCTIONS", "special", "symbol",
    "subcommand", "prompt", "cols", "rows", "others", "path", "CallToolResult", "skill", "name",
    "TResult", "string", "TabClipboardEntry", "dir", "日期", "标题", "hash",
    "external_codex_apps_writing_block_edits_part_1_of_3",
    "external_codex_apps_writing_block_edits_part_2_of_3",
    "external_codex_apps_writing_block_edits_part_3_of_3",
]
_SYSTEM_BLOCK_RE = [re.compile(rf"<{t}[^>]*>.*?</{t}>", re.S) for t in _SYSTEM_TAGS]
_IMAGE_TAG_RE = re.compile(r"<image[^>]*>.*?</image>|<image[^>]*>", re.S)
_SYSTEM_LINE_PREFIX = ("# AGENTS.md instructions", "# Files mentioned by the user:",
                       "# In app browser:", "Automation:")
_ABORT_LINE = re.compile(r"^<turn_aborted>\s*$")


def _clean_codex_user(text: str) -> str:
    for pat in _SYSTEM_BLOCK_RE:
        text = pat.sub("", text)
    text = _IMAGE_TAG_RE.sub("[图片]", text)
    kept = []
    for ln in text.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith(_SYSTEM_LINE_PREFIX) or _ABORT_LINE.match(s):
            continue
        kept.append(ln)
    text = "\n".join(kept).strip()
    if text.startswith("Automation:"):
        return ""
    return text


def _codex_text(content) -> str:
    parts = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") in ("input_text", "output_text") and c.get("text"):
            parts.append(str(c["text"]))
    return "\n".join(parts).strip()


def _codex_session_id(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "session_meta":
                    pid = (d.get("payload") or {}).get("id")
                    if pid:
                        return str(pid)
                break
    except OSError:
        pass
    return path.stem.removeprefix("rollout-") or path.stem


def parse_codex(path: Path) -> Optional[list]:
    cid = _codex_session_id(path)
    msgs: list = []
    try:
        fh = path.open(encoding="utf-8")
    except OSError as e:
        raise ImportError_(f"无法读取 {path}：{e}")
    with fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") != "response_item":
                continue
            payload = d.get("payload") or {}
            if payload.get("type") != "message":
                continue
            role = str(payload.get("role") or "").lower()
            if role not in ("user", "assistant"):
                continue
            text = _codex_text(payload.get("content"))
            if role == "user":
                text = _clean_codex_user(text)
            if not text:
                continue
            mid = str(payload.get("id") or "") or _stable_id(role, None, text)
            msgs.append((role, fmt_time(d.get("timestamp")), mid, text))
    if not msgs:
        return None
    title = _first_user_snippet(msgs) or path.stem
    return [_make_conversation("codex", cid, title, msgs)]


# ---------- 解析器：本地 Claude Code ----------

def parse_claude(path: Path) -> Optional[list]:
    cid = path.stem
    msgs: list = []
    try:
        fh = path.open(encoding="utf-8")
    except OSError as e:
        raise ImportError_(f"无法读取 {path}：{e}")
    with fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            if d.get("type") not in ("user", "assistant"):
                continue
            m = d.get("message") or {}
            role = str(m.get("role") or d.get("type")).lower()
            if role not in ("user", "assistant"):
                continue
            content = m.get("content")
            if isinstance(content, str):
                text = content.strip()
            elif isinstance(content, list):
                text = "\n".join(str(c.get("text", "")) for c in content
                                  if isinstance(c, dict) and c.get("type") == "text").strip()
            else:
                text = ""
            if role == "user" and re.match(r"^claude(?:\s+--?[\w-]+(?:\s+\S+)?)*\s*$", text):
                continue  # CLI 调用/resume 行，不是真实内容
            if not text:
                continue
            mid = str(d.get("uuid") or "") or _stable_id(role, None, text)
            msgs.append((role, fmt_time(d.get("timestamp")), mid, text))
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
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    os.replace(tmp, path)
    os.chmod(path, mode)


def imported_path(out_dir: Path) -> Path:
    return out_dir / ".imported.json"


def load_imported(out_dir: Path) -> dict:
    p = imported_path(out_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_imported(imported: dict, out_dir: Path) -> None:
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    _atomic_write(imported_path(out_dir), json.dumps(imported, ensure_ascii=False, indent=2) + "\n")


def _format_message(role: str, t: Optional[str], mid: str, text: str) -> str:
    tstr = t or "（未知）"
    return f"**{role}**（{tstr}；message_id: {mid}）：\n{text}"


def write_conversation(conv: tuple, imported: dict, out_dir: Path, dry_run: bool = False) -> str:
    """写入会话；返回 'ok' / 'dup' / 'dry'。增量：已导入的 message_id 不再重复写，只追加新消息。"""
    source, cid, title, exported_at, msgs = conv
    key = f"{source}:{cid}"
    prev = imported.get(key) or {}
    known = set(prev.get("message_ids") or [])
    new_msgs = [m for m in msgs if m[2] not in known]
    if not new_msgs:
        return "dup"
    if dry_run:
        return "dry"
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    path = out_dir / f"{source}-{_sanitize_filename(cid)}.md"
    if path.exists():
        existing = path.read_text(encoding="utf-8")
        head, _sep, _tail = existing.partition("<!-- distill-messages:begin -->")
        if _sep:
            prefix = head
            body = "\n".join(_format_message(*m) for m in msgs if m[2] in known)
            # 追加新消息：新消息按时间排序接在后面
            tail = "\n".join(_format_message(*m) for m in new_msgs)
            content = prefix + "<!-- distill-messages:begin -->\n" + body
            if tail:
                content += ("\n" if body else "") + tail
            content += "\n<!-- distill-messages:end -->"
        else:
            # 旧格式文件（无标记）：直接整体重写为完整消息
            content = _build_content(source, cid, title, exported_at, msgs)
    else:
        content = _build_content(source, cid, title, exported_at, msgs)
    _atomic_write(path, content)
    imported[key] = {
        "path": str(path), "imported_at": today_str(), "title": title,
        "message_ids": sorted(known | {m[2] for m in new_msgs}),
    }
    return "ok"


def _build_content(source: str, cid: str, title: str, exported_at: str, msgs: list) -> str:
    lines = [f"# {source} · {title}", "",
             f"<!-- source: {source} -->",
             f"<!-- conversation_id: {cid} -->",
             f"<!-- exported_at: {exported_at} -->",
             "", "<!-- distill-messages:begin -->"]
    for role, t, mid, text in msgs:
        lines.append(_format_message(role, t, mid, text))
        lines.append("")
    lines.append("<!-- distill-messages:end -->")
    return "\n".join(lines)


# ---------- 本地主动发现 ----------

def discover_local(since: Optional[str] = None, excludes: tuple = (),
                   roots: tuple = LOCAL_ROOTS) -> list:
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
            first_t, last_t, title = _peek(source, p)
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
        with path.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i < 60:
                    head_lines.append(line)
                else:
                    tail_lines.append(line)
                    if len(tail_lines) > 30:
                        tail_lines.pop(0)
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
        ts = d.get("timestamp")
        if ts:
            ft = fmt_time(ts)
            if ft and not first_t:
                first_t = ft
            if ft:
                last_t = ft
        if source == "codex":
            payload = d.get("payload") or {}
            if payload.get("type") == "message" and payload.get("role") == "user" and not title:
                for c in payload.get("content") or []:
                    if isinstance(c, dict) and c.get("type") == "input_text" and c.get("text"):
                        t = _clean_codex_user(str(c["text"])).replace("\n", " ").strip()
                        if t:
                            title = t[:40] + ("…" if len(t) > 40 else "")
                        break
        elif source == "claude":
            if d.get("type") == "user" and not title:
                m = d.get("message") or {}
                content = m.get("content")
                if isinstance(content, str):
                    t = content.strip()
                elif isinstance(content, list):
                    t = " ".join(str(c.get("text", "")) for c in content
                                 if isinstance(c, dict) and c.get("type") == "text").strip()
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
        roots = LOCAL_ROOTS
        if args.path:
            roots = (("codex", args.path, "rollout-*.jsonl"),
                     ("claude", args.path, "*.jsonl"))
        found = discover_local(since, excludes, roots)
        return run_local(found, args, imported, out_dir)
    return import_convs(convs, skipped, total, imported, out_dir, dry_run=args.dry_run)


def import_convs(convs: list, skipped: list, total: int, imported: dict,
                 out_dir: Path, dry_run: bool) -> tuple:
    ok = dup = 0
    for conv in convs:
        try:
            result = write_conversation(conv, imported, out_dir, dry_run)
        except OSError as e:
            skipped.append((conv[1], f"写入失败：{e}"))
            continue
        if result == "dup":
            dup += 1
        else:
            ok += 1
    if not dry_run:
        save_imported(imported, out_dir)
    return (total, ok, dup, skipped)


def run_local(found: list, args, imported: dict, out_dir: Path) -> tuple:
    if not found:
        print("未发现可导入的本地会话（codex/claude）。")
        return (0, 0, 0, [])
    total_size = sum(f[5] for f in found)
    print(f"发现 {len(found)} 个本地会话，总大小 {total_size / 1024:.0f} KB：")
    for source, sid, title, first_t, last_t, size, path in found:
        print(f"  [{source}] {title or sid}  {first_t or '?'} ~ {last_t or '?'}  {size}B  {path}")
    if args.dry_run:
        print("（--dry-run：仅列出清单，未写入任何文件）")
        return (len(found), 0, 0, [])
    if not args.yes:
        try:
            ans = input(f"\n确认导入以上 {len(found)} 个会话？[y/N] ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("已取消。")
            return (len(found), 0, 0, [])
    ok = dup = 0
    bad = []
    for source, sid, title, first_t, last_t, size, path in found:
        try:
            convs = parse_codex(Path(path)) if source == "codex" else parse_claude(Path(path))
        except ImportError_ as e:
            bad.append((sid, str(e)))
            continue
        if not convs:
            bad.append((sid, SKIP_EMPTY))
            continue
        result = write_conversation(convs[0], imported, out_dir)
        if result == "dup":
            dup += 1
        else:
            ok += 1
    save_imported(imported, out_dir)
    return (len(found), ok, dup, bad)


def print_report(total: int, ok: int, dup: int, skipped: list, source: str,
                 dry_run: bool) -> None:
    if dry_run:
        print(f"{source}：原始 {total} 个会话，dry-run 将导入 {ok}（未写入）")
    else:
        print(f"{source}：原始 {total} 个会话 → 导入 {ok}"
              + (f"（其中已导入过 {dup}）" if dup else ""))
    by_reason: dict[str, int] = {}
    for _ref, reason in skipped:
        by_reason[reason] = by_reason.get(reason, 0) + 1
    if by_reason:
        detail = "；".join(reason + (f" ×{n}" if n > 1 else "") for reason, n in sorted(by_reason.items()))
        print(f"  跳过 {len(skipped)}：{detail}")
        for ref, reason in skipped[:15]:
            print(f"    - {ref}: {reason}")
        if len(skipped) > 15:
            print(f"    … 及另外 {len(skipped) - 15} 条")
    print("完成。写入目录见各文件（本地处理，不上传）。")


def main() -> int:
    ap = argparse.ArgumentParser(description="selfdistill 全来源聊天导入器")
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--path", help="导出来源目录/文件；local 可覆盖扫描根")
    ap.add_argument("--since", help="仅导入该日期（YYYY-MM-DD）之后的本地会话")
    ap.add_argument("--exclude", action="append", help="本地发现排除 glob（可重复）")
    ap.add_argument("--dry-run", action="store_true", help="只列清单/识别，不写文件")
    ap.add_argument("--yes", action="store_true", help="跳过确认直接导入")
    ap.add_argument("--include-thinking", action="store_true",
                    help="DeepSeek 包含 THINK 推理片段（默认排除）")
    ap.add_argument("--root", help="覆盖 input/ 根目录（测试用）")
    args = ap.parse_args()

    global _INCLUDE_THINKING
    _INCLUDE_THINKING = args.include_thinking

    out_dir = Path(args.root).expanduser() if args.root else INPUT_DIR
    imported = load_imported(out_dir) if not args.dry_run else {}

    try:
        if args.source == "local" and not args.path:
            path_arg = None
        else:
            if not args.path:
                ap.error(f"--source {args.source} 需要 --path")
            path_arg = args.path
        total, ok, dup, skipped = run_source(args.source, path_arg, args, imported, out_dir)
    except ImportError_ as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    print_report(total, ok, dup, skipped, args.source, args.dry_run)
    return 0


_INCLUDE_THINKING = False


if __name__ == "__main__":
    sys.exit(main())
