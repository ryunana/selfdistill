#!/usr/bin/env python3
"""发布前隐私扫描：检查仓库里是否残留本人信息、绝对路径、密钥。

纯标准库，无依赖。用法：
    python3 scripts/scan_before_release.py [路径]
默认扫描仓库根目录（自动跳过 .git / dist / input / 虚拟环境）。
"""
import re
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

SKIP_DIRS = {".git", "dist", "input", "__pycache__", ".venv", ".mypy_cache"}
TEXT_SUFFIXES = {".md", ".py", ".txt", ".json", ".yaml", ".yml", ".toml",
                 ".html", ".css", ".js", ".sh", ".csv"}


def main(root: Path) -> int:
    self_path = Path(__file__).resolve()
    hits = 0
    for p in sorted(root.rglob("*")):
        if p.resolve() == self_path:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
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
                    print(f"{p.relative_to(root)}:{lineno}  [{label}]  {line.strip()[:80]}")
                    hits += 1
    if hits:
        print(f"\n共 {hits} 处敏感命中，发布前必须处理。")
        return 1
    print("扫描通过：未发现本人信息 / 绝对路径 / 密钥。")
    return 0


if __name__ == "__main__":
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    sys.exit(main(root))
