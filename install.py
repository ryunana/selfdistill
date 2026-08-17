#!/usr/bin/env python3
"""selfdistill install：把 dist/<target>/ 的产物确认后增量写入对应 AI 工具目录。

用法：
    python3 install.py --target codex     # 装到 ~/.codex
    python3 install.py --target hermes    # 装到 ~/.hermes
    python3 install.py --target codex --yes   # 跳过确认直接写（慎用）

只做三件事：目标文件不存在则新建；存在则替换 distill 标记块之间的内容；无标记则追加一个标记块。
"""
import argparse
import difflib
import sys
from pathlib import Path

BEGIN = "<!-- distill:begin -->"
END = "<!-- distill:end -->"

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
HOME = Path.home()


def merge(existing: str, incoming: str) -> str:
    """把 incoming（含标记块）合并进 existing。"""
    if not existing:
        return incoming
    b = existing.find(BEGIN)
    e = existing.find(END)
    if b != -1 and e != -1 and e > b:
        suffix = existing[e + len(END):]
        suffix = ("\n\n" + suffix.lstrip("\n")) if suffix.strip() else ""
        return existing[:b] + incoming.rstrip() + "\n" + suffix
    return existing.rstrip() + "\n\n" + incoming.rstrip() + "\n"


def reject_symlink(path: Path, label: str) -> None:
    if path.is_symlink():
        print(f"错误：{label} 不允许是符号链接：{path}", file=sys.stderr)
        sys.exit(1)


def safe_target_path(root: Path, dest: Path) -> None:
    """Reject symlinked or non-directory target components before any read or write."""
    reject_symlink(root, "安装目标目录")
    if root.exists() and not root.is_dir():
        print(f"错误：安装目标根路径不是目录：{root}", file=sys.stderr)
        sys.exit(1)
    current = root
    for part in dest.relative_to(root).parts:
        current = current / part
        reject_symlink(current, "安装目标路径")
        if current != dest and current.exists() and not current.is_dir():
            print(f"错误：安装目标父路径不是目录：{current}", file=sys.stderr)
            sys.exit(1)


def collect_plans(target: str) -> list:
    src_root = DIST / target
    if not src_root.exists():
        print(f"错误：dist/{target}/ 不存在，先运行 python3 build.py。", file=sys.stderr)
        sys.exit(1)
    if src_root.is_symlink() or not src_root.is_dir():
        print(f"错误：dist/{target}/ 不是普通目录，拒绝安装。", file=sys.stderr)
        sys.exit(1)
    source_files = sorted(src_root.rglob("*"))
    if not any(f.is_file() and not f.is_symlink() for f in source_files):
        print(f"错误：dist/{target}/ 为空，拒绝安装。", file=sys.stderr)
        sys.exit(1)
    plans = []
    reject_symlink(src_root, "构建产物目录")
    for f in source_files:
        reject_symlink(f, "构建产物路径")
        if f.is_dir():
            continue
        rel = f.relative_to(src_root)
        dest = HOME / f".{target}" / rel
        target_root = HOME / f".{target}"
        safe_target_path(target_root, dest)
        try:
            incoming = f.read_text(encoding="utf-8")
        except UnicodeError:
            print(f"错误：构建产物不是 UTF-8 文本：{f}", file=sys.stderr)
            sys.exit(1)
        if dest.exists() and not dest.is_file():
            print(f"错误：已有目标路径不是普通文件：{dest}", file=sys.stderr)
            sys.exit(1)
        try:
            existing = dest.read_text(encoding="utf-8") if dest.exists() else ""
        except UnicodeError:
            print(f"错误：已有目标文件不是 UTF-8 文本：{dest}", file=sys.stderr)
            sys.exit(1)
        new_content = merge(existing, incoming)
        plans.append((dest, existing, new_content))
    return plans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=["codex", "hermes"])
    ap.add_argument("--yes", action="store_true", help="跳过确认，直接写入")
    args = ap.parse_args()

    plans = collect_plans(args.target)
    changed = [(d, e, n) for d, e, n in plans if e != n]
    if not changed:
        print("所有目标文件均已是最新，无需变更。")
        return 0

    for dest, existing, new_content in changed:
        print(f"\n=== {dest} ===")
        if not existing:
            print("  [新建]")
        else:
            diff = difflib.unified_diff(
                existing.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"当前 {dest}", tofile="安装后",
            )
            for line in diff:
                print("  " + line.rstrip("\n"))

    if not args.yes:
        try:
            ans = input("\n确认写入以上变更？[y/N] ").strip().lower()
        except EOFError:
            print("错误：未收到确认输入，已取消。", file=sys.stderr)
            return 1
        if ans not in ("y", "yes"):
            print("已取消。")
            return 0

    for dest, existing, new_content in changed:
        safe_target_path(HOME / f".{args.target}", dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(new_content, encoding="utf-8")
        print(f"已写入 {dest}")
    print(f"完成：{len(changed)} 个文件已更新。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
