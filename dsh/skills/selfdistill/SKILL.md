---
name: selfdistill
description: 把用户与 AI 的聊天记录蒸馏成 L1–L4 个人档案（selfdistill 工作流）：整理导出、提炼候选、逐条确认、构建 HTML、写回 DSH 或 Codex/Hermes。用户提到 selfdistill、蒸馏、个人档案、写回 DSH 时使用。
whenToUse: 用户要建立或更新 L1–L4 个人档案、蒸馏与 AI 的聊天记录、把档案写回 DSH/Codex/Hermes，或要求你接手 selfdistill 项目时。
---

# selfdistill · 蒸馏工作流（DeepSeek Harness 版）

selfdistill 是一个「AI 自我蒸馏」工具包：把用户与 AI 的聊天记录，在 **AI 辅助 + 人工确认** 下蒸馏成看得见、带来源、AI 也用得上的 L1–L4 个人档案，并写回 AI 工具（DSH / Codex / Hermes）。

| 层级 | 内容 | 通俗解释 |
|------|------|----------|
| L1 协作契约 | 授权边界、汇报习惯、反馈信号、表达偏好 | 「怎么和我共事」 |
| L2 决策逻辑 | 取舍原则、优先级、红线 | 「我会怎么做决定」 |
| L3 个人事实 | 身份、经历、偏好 | 「我是谁」 |
| L4 领域打法 | 可复用的工作方法 | 「我擅长什么、怎么做」 |

## 工作前提

- 有 selfdistill 仓库 checkout：无则先 `git clone https://github.com/ryunana/selfdistill`；
- 需要 Python 3.9+（纯标准库，无第三方依赖）；
- **用户负责导出聊天记录**（各 AI 工具的导出入口见仓库 `docs/intake.md`）。

## 完整流程（7 步）

### 0. 收集导出 → 放入 input/

- 让用户把各来源导出的聊天记录放到仓库 `input/` 目录（该目录被 Git 忽略，绝不提交）。
- 常见来源：ChatGPT 网页导出、Gemini Takeout、Codex/Claude Code 本地记录、DeepSeek 网页导出等；每种格式的整理要求见 `docs/intake.md`。

### 1. 整理（读 docs/intake.md）

- 通读 `docs/intake.md`，按其中说明把 `input/` 的原始记录整理成统一 Markdown。
- 整理结果仍只放在 `input/`（或报告里），不直接改 `canonical/`。

### 2. 提炼候选（读 prompts/distill.md）

- 通读 `prompts/distill.md`，按其中的规则从整理后的记录中提炼 L1–L4 **候选**。
- 输出形式：逐条候选 + 来源引用（哪条记录支撑了这条结论）。
- **只展示候选，不直接写正式档案。**

### 3. 逐条人工确认（关键步骤）

- 用 DSH 的提问能力（ask_user_question）把候选**逐条**交给用户确认：接受 / 修改 / 拒绝。
- **未经确认，不得写入 `canonical/`。** 这是 selfdistill 的硬规则。

### 4. 写入 canonical/

- 只把用户确认过的内容写进 `canonical/`：
  - `01-l1-contract.md`（L1）、`02-l2-decision-logic.md`（L2）、`03-l3-user-profile.md`（L3）、`04-domain-playbooks/<领域>.md`（L4，每个领域一个文件，带 frontmatter：`id`、`description`）。
  - 结构参考仓库 `templates/`（仓库里的「张三」是虚构样例）。
- 私密 L3 若用户要求单独管理，可放入 `canonical/03-l3-private.md`（已被 Git 忽略）。

### 5. 构建（build.py）

```bash
cd <selfdistill 仓库>
python3 build.py                # 生成 dist/（HTML 可视化 + codex/ + hermes/ + dsh/）
python3 build.py --include-private   # 额外包含私密 L3（默认排除）
```

- 产物：`dist/index.html`（可视化）、`dist/dsh/`（DSH 写回产物）、`dist/codex/`、`dist/hermes/`。

### 6. 写回 DSH（install.py --target dsh）

```bash
python3 install.py --target dsh
```

- 写入 `$DSH_HOME`（默认 `~/.dsh`）：
  - **persona 只放 L1**（协作契约，常驻但非敏感）；
  - **L2/L3/L4 写成 `~/.dsh/skills/` 下的 skill**（按需加载，敏感内容不默认进入每个对话）。
- 先展示 diff，**用户确认后才写入**；`--yes` 可跳过确认（慎用）。
- 重复安装增量合并；目标文件已存在但无 selfdistill 标记时拒绝覆盖。
- 写回 Codex/Hermes：`python3 install.py --target codex` / `--target hermes`（同样先展示 diff）。

### 7. 持续更新（有新对话后）

1. 把新对话导出追加到 `input/`；
2. 按 `schemas/inbox-v2.json` 在 `inbox/` 新建候选 JSON（可直接来自对话，`evidence_ids` 留空，状态 `pending`）；
3. `python3 distill_audit.py audit` 生成 `reports/latest/` 证据包与覆盖报告；
4. 读 `prompts/rediscovery.md`，让当前 AI 从 `reports/latest/evidence.md` 发现新规律/冲突/时间变化，只写回 `reports/`；
5. `python3 distill_audit.py verify reports/latest` 校验来源与引用；
6. 由用户逐条接受/拒绝后人工更新 `canonical/`，再 `build.py`（+ 写回如需要）。

## 隐私红线（必须遵守）

- `input/`、`inbox/`、`reports/`、`dist/` 都是本机数据或生成物，**绝不提交**到 Git；
- 真实聊天、候选、报告**不写进公开仓库**；`canonical/03-l3-private.md` 不提交；
- 蒸馏要调云端 AI 时，提交给模型的内容受该供应商数据政策约束——先告知用户；
- 未经用户明确确认，不写 `canonical/`、不执行 `install.py` 写回；
- 写回 DSH 时 persona 只放 L1，L3 敏感事实只在相关对话中按需加载。

## 排错与细节

- 各来源导出文件格式与整理说明：`docs/intake.md`
- 蒸馏规则全文：`prompts/distill.md`；重新发现规则：`prompts/rediscovery.md`
- inbox 候选契约：`schemas/inbox-v2.json`
- 分步细节与常见问题：`references/workflow.md`
