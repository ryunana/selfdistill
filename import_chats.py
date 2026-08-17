#!/usr/bin/env python3
"""selfdistill chat importer：把各来源聊天记录自动整理成统一 Markdown 写入 input/。

用法：
    python3 import_chats.py --source chatgpt  --path <导出目录或文件>
    python3 import_chats.py --source gemini   --path <Takeout 解压目录>
    python3 import_chats.py --source deepseek --path <conversations.json 或 zip>
    python3 import_chats.py --source local [--since YYYY-MM-DD] [--exclude glob] [--dry-run]

本地主动发现（codex/claude）默认先列清单、确认后才写入；--dry-run 只列清单不写文件。
输出遵循 docs/intake.md 与 distill-candidate 的 ID 契约（conversation_id/message_id/exported_at）。
纯 Python 标准库，无第三方依赖。
"""
from __future__ import annotations

import argparse
import fnmatch
import html
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

SKIP_REASONS = {
    "empty": "无消息",
    "bad": "格式错误/损坏",
    "dup": "已导入过",
    "excluded": "被排除",
    "unparsed": "结构未能识别",
}


class ImportError_(Exception):
    pass


# ---------- 时间 ----------

_CN_DATETIME = re.compile(
    r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*([上午下午晚上]*)(\d{1,2})[:：点](\d{1,2})")
_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_EN_DATETIME = re.compile(
    r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),?\s+(\d{4})[,\s]+(\d{1,2}):(\d{2})\s*(AM|PM)", re.I)


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


# ---------- 解析器：ChatGPT ----------

def parse_chatgpt(path: Path) -> list:
    """conversations-*.json（可能多分片）：mapping 消息树 + author.role + content.parts。"""
    files = sorted(path.glob("conversations-*.json")) if path.is_dir() else [path]
    if not files:
        raise ImportError_(f"未找到 conversations-*.json：{path}")
    convs = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ImportError_(f"无法读取 {f}：{e}")
        for conv in data or []:
            mapping = conv.get("mapping") or {}
            msgs = []
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
                msgs.append((role, fmt_time(msg.get("create_time")),
                             str(msg.get("id") or nid), text))
            if not msgs:
                continue
            msgs.sort(key=lambda m: (m[1] or "9999", m[2] or ""))
            convs.append(_make_conversation("chatgpt", conv.get("id") or f.stem,
                                            conv.get("title") or "未命名会话", msgs))
    return convs


# ---------- 解析器：Gemini Takeout（best-effort） ----------

class _TextExtractor(HTMLParser):
    """提取可见文本，块级标签之间换行。"""

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


_TIME_PATTERNS = [
    re.compile(r"\b\d{4}年\d{1,2}月\d{1,2}日[^\n]*"),
    re.compile(r"\b\d{1,2}月\d{1,2}日[^\n]*"),
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}[^\n]*"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}[^\n]*"),
]


def parse_gemini(path: Path) -> list:
    """Takeout 我的活动记录.html：按 Prompted / Gemini 轮次提取（best-effort）。

    无真实样例时按文档结构实现：寻找时间头 + Prompted(用户)/Gemini(回复) 标记。
    结构无法识别时抛 ImportError_，由调用方报告为「结构未能识别」。
    """
    target = path if path.is_file() else next(iter(path.rglob("我的活动记录.html")), None)
    if target is None:
        raise ImportError_(f"未找到 我的活动记录.html：{path}")
    try:
        parser = _TextExtractor()
        parser.feed(target.read_text(encoding="utf-8", errors="replace"))
        text = parser.text()
    except OSError as e:
        raise ImportError_(f"无法读取 {target}：{e}")
    if "Prompted" not in text and "Gemini" not in text:
        raise ImportError_(f"{target} 中未找到 Prompted/Gemini 轮次标记（结构未能识别）")

    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    msgs: list = []
    current_role: Optional[str] = None
    current_time: Optional[str] = None
    pending_time: Optional[str] = None
    buffer: list[str] = []
    cid = target.stem or "gemini-export"
    title = "Gemini 会话"

    def flush():
        nonlocal buffer
        if current_role and buffer:
            msgs.append((current_role, current_time, f"seg{len(msgs) + 1}",
                         "\n".join(buffer).strip()))
        buffer = []

    def _role_time(line: str) -> Optional[str]:
        for pat in _TIME_PATTERNS:
            m = pat.search(line)
            if m:
                return fmt_time(m.group(0).strip())
        return None

    for ln in lines:
        low = ln.lower()
        has_role_marker = "prompted" in low or re.search(r"\bgemini\b", low)
        if not has_role_marker:
            # 纯时间头行：记为下一条消息的待定时间，不进入正文缓冲
            if _role_time(ln) is not None and len(ln) < 60:
                pending_time = _role_time(ln)
                continue
            if current_role:
                buffer.append(ln)
            continue
        if "prompted" in low:
            flush()
            current_role = "user"
            current_time = pending_time or _role_time(ln)
            pending_time = None
            rest = re.sub(r"^(prompted|你|you)\s*[:：]?", "", ln, flags=re.I).strip()
            if rest and rest != ln.lower() and len(rest) > 2:
                buffer.append(rest)
            continue
        # gemini
        flush()
        current_role = "assistant"
        current_time = pending_time or _role_time(ln)
        pending_time = None
        rest = re.sub(r"^\s*(gemini|assistant|ai)\s*[:：]?", "", ln, flags=re.I).strip()
        if rest and len(rest) > 2:
            buffer.append(rest)
    flush()
    if not msgs:
        raise ImportError_(f"{target} 未提取到任何 Prompted/Gemini 消息")
    return [_make_conversation("gemini", cid, title, msgs)]


# ---------- 解析器：DeepSeek ----------

def parse_deepseek(path: Path) -> list:
    """conversations.json（或 zip）：mapping 消息树 + fragments（REQUEST/RESPONSE/THINK/FILE）。"""
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
            if role is None or not text_parts:
                continue
            msgs.append((role, t, str(nid), "\n\n".join(text_parts).strip()))
        if not msgs:
            continue
        msgs.sort(key=lambda m: (m[1] or "9999", m[2] or ""))
        convs.append(_make_conversation("deepseek", conv.get("id") or "unknown",
                                        conv.get("title") or "未命名会话", msgs))
    return convs


# ---------- 解析器：本地 Codex / Claude Code ----------

# Codex 系统注入块（非用户真实内容）：会话预热、环境上下文、插件推荐等
_SYSTEM_BLOCKS = (
    re.compile(r"<environment_context[^>]*>.*?</environment_context>", re.S),
    re.compile(r"<recommended_plugins[^>]*>.*?</recommended_plugins>", re.S),
    re.compile(r"<heartbeat[^>]*>.*?</heartbeat>", re.S),
)


def _strip_system_blocks(text: str) -> str:
    for pat in _SYSTEM_BLOCKS:
        text = pat.sub("", text)
    return text.strip()


def _codex_text(content) -> str:
    parts = []
    for c in content or []:
        if not isinstance(c, dict):
            continue
        if c.get("type") in ("input_text", "output_text") and c.get("text"):
            parts.append(str(c["text"]))
    return "\n".join(parts).strip()


def _codex_session_id(path: Path) -> str:
    """从 session_meta 行取真实会话 id；取不到回退文件名。"""
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
                break
    except OSError:
        pass
    return path.stem.removeprefix("rollout-") or path.stem


def parse_codex(path: Path) -> Optional[list]:
    """rollout-*.jsonl：response_item + payload.type=message；剥系统注入块。"""
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
                text = _strip_system_blocks(text)
            if not text:
                continue
            msgs.append((role, fmt_time(d.get("timestamp")),
                         str(payload.get("id") or f"line{i}"), text))
    if not msgs:
        return None
    title = _first_user_snippet(msgs) or path.stem
    return [_make_conversation("codex", cid, title, msgs)]


def parse_claude(path: Path) -> Optional[list]:
    """projects/<enc>/<uuid>.jsonl：type=user/assistant + message.content；跳过 CLI 调用行。"""
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
            msgs.append((role, fmt_time(d.get("timestamp")),
                         str(d.get("uuid") or f"line{i}"), text))
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


# ---------- 会话组装 ----------

def _make_conversation(source: str, cid: str, title: str, msgs: list) -> tuple:
    title = " ".join(str(title).split())
    times = [t for _r, t, _m, _x in msgs if t]
    exported_at = times[-1][:10] if times else today_str()
    return (source, cid, title, exported_at, msgs)


def _sanitize_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "conversation"


# ---------- 去重与写入 ----------

def imported_path(out_dir: Path) -> Path:
    """去重状态文件与输出目录同域（--root 测试时不污染真实 input/）。"""
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
    p = imported_path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(imported, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_conversation(conv: tuple, imported: dict, out_dir: Path) -> str:
    source, cid, title, exported_at, msgs = conv
    key = f"{source}:{cid}"
    if key in imported:
        return "dup"
    lines = [f"# {source} · {title}", "",
             f"<!-- source: {source} -->",
             f"<!-- conversation_id: {cid} -->",
             f"<!-- exported_at: {exported_at} -->", ""]
    for role, t, mid, text in msgs:
        tstr = t or "（未知）"
        lines.append(f"**{role}**（{tstr}；message_id: {mid}）：")
        lines.append(text)
        lines.append("")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{source}-{_sanitize_filename(cid)}.md"
    path.write_text("\n".join(lines), encoding="utf-8")
    imported[key] = {"path": str(path), "imported_at": today_str(), "title": title}
    return "ok"


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
    """轻量读取：只扫开头若干行拿时间与标题，不解析整个会话（dry-run 友好）。"""
    first_t = last_t = None
    title = ""
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh):
                if i > 60:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = d.get("timestamp")
                if ts and not first_t:
                    first_t = fmt_time(ts)
                last_t = fmt_time(ts) if ts else last_t
                if source == "codex":
                    payload = d.get("payload") or {}
                    if payload.get("type") == "message" and payload.get("role") == "user" and not title:
                        for c in payload.get("content") or []:
                            if isinstance(c, dict) and c.get("type") == "input_text" and c.get("text"):
                                t = _strip_system_blocks(str(c["text"])).replace("\n", " ").strip()
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
                        if t and not re.match(r"^claude(\s+--[\w-]+)*\s*$", t):
                            title = t[:40] + ("…" if len(t) > 40 else "")
    except OSError:
        pass
    return (first_t, last_t, title)


# ---------- 主流程 ----------

def run_source(source: str, path_arg: Optional[str], args, imported: dict,
               out_dir: Path) -> tuple:
    if source == "chatgpt":
        convs = parse_chatgpt(Path(path_arg))
    elif source == "gemini":
        convs = parse_gemini(Path(path_arg))
    elif source == "deepseek":
        convs = parse_deepseek(Path(path_arg))
    else:  # local
        since = args.since
        excludes = tuple(args.exclude or [])
        found = discover_local(since, excludes)
        return run_local(found, args, imported, out_dir)
    return import_convs(convs, imported, out_dir, dry_run=args.dry_run)


def import_convs(convs: list, imported: dict, out_dir: Path, dry_run: bool) -> tuple:
    ok = dup = 0
    skipped_bad = []
    for conv in convs:
        try:
            result = write_conversation(conv, imported, out_dir) if not dry_run else "dry"
        except OSError as e:
            skipped_bad.append((conv[1], str(e)))
            continue
        if result == "dup":
            dup += 1
        else:
            ok += 1
    if not dry_run:
        save_imported(imported, out_dir)
    return (len(convs), ok, dup, skipped_bad)


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
            if source == "codex":
                convs = parse_codex(Path(path))
            else:
                convs = parse_claude(Path(path))
        except ImportError_ as e:
            bad.append((sid, str(e)))
            continue
        if not convs:
            bad.append((sid, "无消息"))
            continue
        result = write_conversation(convs[0], imported, out_dir)
        if result == "dup":
            dup += 1
        else:
            ok += 1
    save_imported(imported, out_dir)
    return (len(found), ok, dup, bad)


def print_report(identified: int, ok: int, dup: int, bad: list, source: str) -> None:
    skipped = identified - ok - dup
    print(f"{source}：识别 {identified} 个会话，导入 {ok}，跳过 {skipped}"
          + (f"（其中已导入过 {dup}）" if dup else ""))
    if bad:
        print("跳过明细：")
        for sid, reason in bad[:20]:
            print(f"  - {sid}: {reason}")
        if len(bad) > 20:
            print(f"  … 及另外 {len(bad) - 20} 条")
    times = []
    # 报告时间范围由各解析器返回；此处从导入结果推算为空，保留占位
    print("时间范围：见 input/ 各文件 exported_at 头。完成。")


def main() -> int:
    ap = argparse.ArgumentParser(description="selfdistill 全来源聊天导入器")
    ap.add_argument("--source", required=True, choices=SOURCES)
    ap.add_argument("--path", help="导出来源目录/文件；local 可省略")
    ap.add_argument("--since", help="仅导入该日期（YYYY-MM-DD）之后的本地会话")
    ap.add_argument("--exclude", action="append", help="本地发现排除 glob（可重复）")
    ap.add_argument("--dry-run", action="store_true", help="只列清单/识别，不写文件")
    ap.add_argument("--yes", action="store_true", help="跳过确认直接导入")
    ap.add_argument("--no-thinking", action="store_true", help="DeepSeek 排除 THINK 片段")
    ap.add_argument("--root", help="覆盖 input/ 根目录（测试用）")
    args = ap.parse_args()

    global _INCLUDE_THINKING
    _INCLUDE_THINKING = not args.no_thinking

    out_dir = Path(args.root).expanduser() if args.root else INPUT_DIR
    imported = load_imported(out_dir) if not args.dry_run else {}

    try:
        if args.source == "local" and not args.path:
            path_arg = None
        else:
            if not args.path:
                ap.error(f"--source {args.source} 需要 --path")
            path_arg = args.path
        identified, ok, dup, bad = run_source(args.source, path_arg, args, imported, out_dir)
    except ImportError_ as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1

    print_report(identified, ok, dup, bad, args.source)
    return 0


_INCLUDE_THINKING = True


if __name__ == "__main__":
    sys.exit(main())
