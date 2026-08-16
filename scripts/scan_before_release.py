#!/usr/bin/env python3
"""发布前隐私扫描：检查仓库里是否残留本人信息、绝对路径、密钥。

纯标准库，无依赖。用法：
    python3 scripts/scan_before_release.py [路径]
默认扫描仓库根目录（自动跳过 .git / dist / input / 虚拟环境）。
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# 发布前把下面两个占位符替换成你的真实姓名/用户名，运行扫描，再改回占位符提交。
REAL_NAME = "YOUR_NAME_HERE"
REAL_USERNAME = "YOUR_USERNAME_HERE"

# 按类别组织的敏感模式。
PATTERNS = [
    ("真实姓名", re.compile(REAL_NAME)),
    ("用户名", re.compile(rf"\b{REAL_USERNAME}\b")),
    ("绝对路径", re.compile(r"/Users/[^\s\"']+")),
    ("API 密钥 sk- 前缀", re.compile(r"sk-[A-Za-z0-9]{16,}")),
    ("AWS 密钥", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("私钥头", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("Bearer token", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")),
]

SKIP_DIRS = {
    ".git",
    "dist",
    "input",
    "reports",
    "__pycache__",
    ".venv",
    ".mypy_cache",
}
TEXT_SUFFIXES = {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".toml",
                 ".html", ".css", ".js", ".sh", ".csv"}

PROTECTED_DIRS = {"input", "inbox", "reports", "dist"}
ALLOWED_TRACKED = {"input/.gitkeep", "inbox/README.md"}


def tracked_files(root: Path) -> list[str] | None:
    """Return the Git tracked-file list, keeping protected data out of output."""
    try:
        result = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=root,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"无法读取 Git 跟踪文件清单：{exc}", file=sys.stderr)
        return None
    return [path for path in result.stdout.decode("utf-8", errors="strict").split("\0") if path]


def check_protected_tracked_paths(root: Path) -> int:
    """Flag tracked files in local-data directories without printing contents."""
    paths = tracked_files(root)
    if paths is None:
        return 1
    hits = 0
    for relative in paths:
        parts = Path(relative).parts
        if not parts or parts[0] not in PROTECTED_DIRS:
            continue
        if relative in ALLOWED_TRACKED:
            continue
        print(f"{relative}  [受保护目录中的跟踪文件]")
        hits += 1
    return hits


def _skip_content_path(path: Path, root: Path) -> bool:
    """Exclude private data while keeping the public inbox instructions scannable."""
    try:
        relative = path.relative_to(root)
    except ValueError:
        return True
    parts = relative.parts
    if any(part in SKIP_DIRS for part in parts):
        return True
    if parts and parts[0] == "inbox" and relative.as_posix() != "inbox/README.md":
        return True
    return False


def main(root: Path) -> int:
    self_path = Path(__file__).resolve()
    hits = check_protected_tracked_paths(root)
    for p in sorted(root.rglob("*")):
        if p.resolve() == self_path:
            continue
        if _skip_content_path(p, root):
            continue
        if p.is_dir() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for label, pat in PATTERNS:
                if pat.search(line):
                    print(f"{p.relative_to(root)}:{lineno}  [{label}]")
                    hits += 1
    if hits:
        print(f"\n共 {hits} 处敏感命中，发布前必须处理。")
        return 1
    print("扫描通过：未发现本人信息 / 绝对路径 / 密钥。")
    return 0


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    sys.exit(main(root))
