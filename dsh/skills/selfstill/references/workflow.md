# selfstill 工作流分步细节

> 本文件是 SKILL.md 的深读材料：与 SKILL.md 冲突时以 SKILL.md 为准。单一事实源始终是仓库根目录的 prompts/、docs/、schemas/。

## 目录结构速查

```text
selfstill/
├── build.py                  # 读 canonical/ 生成 dist/（HTML + codex + hermes + dsh）
├── install.py                # 写回 AI 工具（--target codex|hermes|dsh）
├── distill_audit.py          # 持续蒸馏审计（audit / verify）
├── canonical/                # 正式档案（L1–L4），只放用户确认过的内容
│   ├── 01-l1-contract.md
│   ├── 02-l2-decision-logic.md
│   ├── 03-l3-user-profile.md
│   ├── 03-l3-private.md      # 私密 L3，Git 忽略，默认不构建
│   └── 04-domain-playbooks/<领域>.md
├── templates/                # 档案空白模板
├── docs/intake.md            # 各来源导出整理说明
├── prompts/distill.md        # 蒸馏规则（L1–L4 提炼）
├── prompts/rediscovery.md    # 持续重新发现规则
├── schemas/inbox-v2.json     # inbox 候选契约
├── input/                    # 原始聊天（Git 忽略）
├── inbox/                    # 待确认候选（Git 忽略）
└── reports/                  # 审计产物（Git 忽略）
```

## L4 领域文件格式

```markdown
---
schema_version: 1
id: <kebab-case-领域id>
description: <一句话「何时使用」，agent 靠它路由>
---

# <领域名>

<正文：可复用的工作方法>
```

## 写回 DSH 的产物说明

build.py 生成 dist/dsh/：

```text
dist/dsh/
├── persona.md                 # L1 协作契约（标记包裹）
└── skills/
    ├── selfstill-decision-logic/SKILL.md   # L2
    ├── selfstill-user-profile/SKILL.md     # L3
    └── selfstill-<领域>/SKILL.md           # L4
```

install.py --target dsh 安装到 $DSH_HOME（默认 ~/.dsh）：

- persona → $DSH_HOME/cordis.patch.yml 的 system-prompt.persona（只放 L1；带 distill 标记增量合并）；
- L2/L3/L4 → $DSH_HOME/skills/<name>/SKILL.md（frontmatter 在顶部，按需加载）。

## 常见问题

**Q：用户说「直接帮我蒸馏」，可以跳过确认吗？**
不可以。selfstill 的核心是人工确认；至少对 L3/L4 候选和最终写回做一次确认。

**Q：install.py --target dsh 报「无 distill 标记，拒绝覆盖」？**
目标文件已存在但不是 selfstill 生成的（可能是用户或其他工具的文件）。不要覆盖；提示用户手动合并或移除后重试。

**Q：写回后 DSH 没生效？**
persona 在 system-prompt 行（home patch 重启后生效）；skills 在 ~/.dsh/skills/（skill-filesystem 自动发现，新会话可见）。若改了插件包本身需重启 web。

**Q：用户没有导出文件，只有聊天里的只言片语？**
按 schemas/inbox-v2.json 把明确修正/边界补充记成 inbox 候选，走持续更新流程，而不是直接改 canonical。
