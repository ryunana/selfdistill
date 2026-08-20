#!/usr/bin/env python3
"""selfdistill install：把 dist/<target>/ 的产物确认后增量写入对应 AI 工具目录。

用法：
    python3 install.py --target codex     # 装到 ~/.codex
    python3 install.py --target hermes    # 装到 ~/.hermes
    python3 install.py --target dsh       # 装到 $DSH_HOME（默认 ~/.dsh）
    python3 install.py --target workbuddy # 装到 ~/.workbuddy
    python3 install.py --target codex --yes   # 跳过确认直接写（慎用）

只做三件事：目标文件不存在则新建；存在则替换 distill 标记块之间的内容；无标记则追加一个标记块。

DSH 目标（--target dsh）：
- persona（L1 协作契约）合并进 $DSH_HOME/cordis.patch.yml 的 system-prompt.persona；
- L2/L3/L4 写成 $DSH_HOME/skills/<name>/SKILL.md（frontmatter 在顶部，按需加载）；
- 目标 skill 文件已存在但无 distill 标记（非 selfdistill 管理）时拒绝覆盖。

WorkBuddy 目标（--target workbuddy）：
- L1 协作契约合并进 ~/.workbuddy/MEMORY.md（用户级记忆，每次会话常驻注入；短且非敏感）；
- L2/L3/L4 写成 ~/.workbuddy/skills/<name>/SKILL.md（WorkBuddy 按描述按需加载）；
- 目标 skill 文件已存在但无 distill 标记（非 selfdistill 管理）时拒绝覆盖。
"""
import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path

BEGIN = "<!-- distill:begin -->"
END = "<!-- distill:end -->"

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD_MANIFEST = DIST / ".selfdistill-build.json"
HOME = Path.home()

# DSH 配置根：尊重 $DSH_HOME，缺省 ~/.dsh
DSH_HOME = Path(os.environ["DSH_HOME"]) if os.environ.get("DSH_HOME") else HOME / ".dsh"

# WorkBuddy 配置根（用户级）：skills 目录 ~/.workbuddy/skills/，记忆文件 ~/.workbuddy/MEMORY.md
WORKBUDDY_HOME = HOME / ".workbuddy"

# DSH web profile 默认 persona 开场白（来自 dsh-web-app bundle patch，实测 rc.7）。
# 若你的 DSH 已自定义 persona，可用 SELFDISTILL_DSH_PERSONA_OPENER 覆盖本常量。
DEFAULT_PERSONA_OPENER = (
    os.environ.get("SELFDISTILL_DSH_PERSONA_OPENER")
    or "You are a coding agent powered by the {{model}} model. Your working directory is {{cwd}}."
)

SYSTEM_PROMPT_ID = "- id: system-prompt"


class InstallError(Exception):
    """安装过程的可预期错误：主流程捕获后打印并退出非零。"""


def require_installable_build() -> None:
    """Only confirmed workspace profiles may be written into real AI tools."""

    if BUILD_MANIFEST.is_symlink() or not BUILD_MANIFEST.is_file():
        raise InstallError("构建来源标记缺失或无效；请先用当前版本重新运行 python3 build.py。")
    try:
        manifest = json.loads(BUILD_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallError("构建来源标记损坏；请重新运行 python3 build.py。") from exc
    if manifest.get("schema_version") != 1 or manifest.get("source_mode") not in {"workspace", "demo"}:
        raise InstallError("构建来源标记格式无效；请重新运行 python3 build.py。")
    if manifest["source_mode"] != "workspace":
        raise InstallError("当前 dist/ 来自虚构 Demo，仅可预览，禁止写回。"
                           "请先在 workspace/canonical/ 建立确认后的档案并重新构建。")


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


def has_system_prompt_row(text: str) -> bool:
    """当前 home patch 是否已有 system-prompt 行（行首必须顶格）。"""
    return re.search(r"(?m)^- id: system-prompt\s*$", text) is not None


def build_persona_block(persona_md: str) -> str:
    """把 persona.md（含 distill 标记）组合成 cordis.patch.yml 的一行 patch。

    persona 是字面量块标量（|），保留 Markdown 换行；distill 标记包裹开场白 + L1，
    重复安装时只替换标记之间的内容。内容统一缩进 6 空格。
    """
    opener = DEFAULT_PERSONA_OPENER
    if "{{" in persona_md or "}}" in persona_md:
        print("警告：L1 内容包含 {{ 或 }}，DSH persona 模板无转义，渲染时可能报错，请改写。",
              file=sys.stderr)
    body_lines = [line if not line else f"      {line}" for line in persona_md.rstrip().splitlines()]
    block = (f"{SYSTEM_PROMPT_ID}\n"
             f"  config:\n"
             f"    persona: |-\n"
             f"      {opener}\n"
             f"\n"
             f"{chr(10).join(body_lines)}\n")
    return block


def indent_block(text: str, indent: str = "      ") -> str:
    """给非空行加统一缩进（块标量正文）。"""
    return "\n".join(line if not line else indent + line for line in text.rstrip().splitlines())


def merge_persona_patch(existing: str, persona_md: str) -> str:
    """把 persona 合并进 $DSH_HOME/cordis.patch.yml。

    - 文件不存在 / 空白 / 空列表（[]）：写入整行；
    - 已有 system-prompt 行且 persona 区域含 distill 标记：只替换该行内标记之间的内容
      （行头、开场白、其他 patch 行保持字节不变）；
    - 已有 system-prompt 行但无标记（用户自定义）：拒绝（fail loud）；
    - 其他内容：在列表末尾追加该行。
    """
    incoming = build_persona_block(persona_md)
    stripped = existing.strip()
    if not stripped or stripped == "[]":
        return incoming
    if stripped.startswith("[") and stripped != "[]":
        raise InstallError("已有 cordis.patch.yml 使用 flow 风格列表（[...]），"
                           "无法安全追加；请手动加入 system-prompt 行后重试。")
    if has_system_prompt_row(existing):
        lines = existing.splitlines(keepends=True)
        start = next(i for i, line in enumerate(lines) if re.match(r"- id: system-prompt\s*$", line))
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if re.match(r"- id:", lines[i]):
                end = i
                break
        section = "".join(lines[start:end])
        b = section.find(BEGIN)
        if b == -1:
            raise InstallError("已有 system-prompt 自定义 persona 且无 distill 标记，"
                               "拒绝覆盖；请手动合并或移除该行后重试。")
        e = section.find(END)
        if e == -1 or e <= b:
            raise InstallError("system-prompt persona 的 distill 标记不完整，拒绝覆盖；请手动修复后重试。")
        inner = persona_md.split(BEGIN, 1)[1].rsplit(END, 1)[0].strip("\n")
        region = f"{BEGIN}\n{indent_block(inner)}\n      {END}"
        new_section = section[:b] + region + section[e + len(END):]
        return "".join(lines[:start]) + new_section + "".join(lines[end:])
    return existing.rstrip() + "\n\n" + incoming.rstrip() + "\n"


def merge_skill(existing: str, incoming: str) -> str:
    """DSH skill 文件合并：整文件替换，以 distill 标记为所有权判定。

    - 不存在：直接写入（incoming 自带 frontmatter + 标记）；
    - 已有且含 distill 标记（selfdistill 管理）：整文件替换（frontmatter 更新可传播）；
    - 已有但无标记（其他工具/用户文件）：拒绝覆盖。
    """
    if not existing:
        return incoming
    if BEGIN not in existing:
        raise InstallError(f"已有目标文件但不含 distill 标记（非 selfdistill 管理），拒绝覆盖。")
    return incoming


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
        if target == "dsh":
            target_root = DSH_HOME
            dest = DSH_HOME / "cordis.patch.yml" if rel.as_posix() == "persona.md" else DSH_HOME / rel
        elif target == "workbuddy":
            target_root = WORKBUDDY_HOME
            dest = WORKBUDDY_HOME / "MEMORY.md" if rel.as_posix() == "l1.md" else WORKBUDDY_HOME / rel
        else:
            target_root = HOME / f".{target}"
            dest = target_root / rel
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
        if target == "dsh" and rel.as_posix() == "persona.md":
            new_content = merge_persona_patch(existing, incoming)
        elif target == "workbuddy" and rel.as_posix() == "l1.md":
            # MEMORY.md 是普通 Markdown（非 YAML patch）：用标准 distill 标记块合并
            new_content = merge(existing, incoming)
        elif target in ("dsh", "workbuddy"):
            new_content = merge_skill(existing, incoming)
        else:
            new_content = merge(existing, incoming)
        plans.append((target_root, dest, existing, new_content))
    return plans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", required=True, choices=["codex", "hermes", "dsh", "workbuddy"])
    ap.add_argument("--yes", action="store_true", help="跳过确认，直接写入")
    args = ap.parse_args()

    try:
        require_installable_build()
        plans = collect_plans(args.target)
    except InstallError as e:
        print(f"错误：{e}", file=sys.stderr)
        return 1
    changed = [(r, d, e, n) for r, d, e, n in plans if e != n]
    if not changed:
        print("所有目标文件均已是最新，无需变更。")
        return 0

    for _root, dest, existing, new_content in changed:
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

    for root, dest, _existing, new_content in changed:
        safe_target_path(root, dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(new_content, encoding="utf-8")
        print(f"已写入 {dest}")
    print(f"完成：{len(changed)} 个文件已更新。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
