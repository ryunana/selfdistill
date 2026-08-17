# selfdistill · 蒸馏我

[English](README.en.md) | 中文

把和 AI 的聊天记录，在 **AI 辅助 + 人工确认** 下，蒸馏成**看得见、带来源、AI 也用得上**的个人档案，并写回你常用的 AI 工具，让它持续认识你。

> 数据默认留在本机；「蒸馏」这一步要调云端 AI，提交给模型的内容受该供应商数据政策约束。

> **[在线查看 HTML Demo →](https://ryunana.github.io/selfdistill/)**
>
> 无需安装，示例内容全部为虚构数据；可直接查看 L1–L4 分层架构、内容分布、设计原则和协同流程（Demo 支持中 / EN 语言切换）。

## 目录

- [这是什么](#这是什么)
- [数据流](#数据流)
- [快速开始](#快速开始)
- [首次蒸馏：从完整历史建立 L1–L4](#首次蒸馏从完整历史建立-l1l4)
- [导入来源](#导入来源)
- [产出与写回目标](#产出与写回目标)
- [重新导入一批新对话](#重新导入一批新对话)
- [持续更新自己的档案](#持续更新自己的档案)
- [工作证据：整理项目事实，不自动包装成果](#工作证据整理项目事实不自动包装成果)
- [隐私与安全](#隐私与安全)
- [依赖](#依赖)

## 这是什么

selfdistill 是一个「AI 自我蒸馏」工具包：把你在 ChatGPT / Claude / Codex / Gemini 等工具里的历史对话，提炼成 L1–L4 分级信息，并写回 AI 工具（Codex / Hermes / DeepSeek Harness）：

| 层级 | 内容 | 通俗解释 | 在 AI 工具里的加载方式 |
|------|------|----------|------------------------|
| L1 协作契约 | 授权边界、汇报习惯、反馈信号、表达偏好 | 「怎么和我共事」 | **默认常驻**：每次对话都生效（短、非敏感） |
| L2 决策逻辑 | 取舍原则、优先级、红线 | 「我会怎么做决定」 | **按需加载**：涉及权衡、排序、风险判断时 |
| L3 个人事实 | 身份、经历、偏好 | 「我是谁」 | **按需加载**：涉及个人背景时；私密块默认不加载 |
| L4 领域打法 | 可复用的工作方法 | 「我擅长什么、怎么做」 | **按需加载**：进入对应领域任务时 |

设计原则：**常驻内容最薄（L1），越往下越重、越按需**；L3 只提供事实与默认偏好，不能发出行为命令；用户当前明确要求永远高于历史画像。

两个出口：① 本地多页 HTML 可视化；② 确认后增量写回你的 AI 工具（让 AI 持续认识你）。此外，仓库提供独立的工作证据整理入口：它帮助核验项目贡献，但不会自动进入 L4、简历或正式档案。

## 数据流

```text
导出聊天记录 → 整理成统一 Markdown → AI 提炼 L1–L4 候选 → 逐条人工确认 → 写入 canonical/ → 构建 HTML / 写回 AI 工具
```

全程「人工确认」是硬规则：**未经确认，不写入正式档案；写回前先展示 diff。**

## 快速开始

你不需要先学会 Python。整个流程可以理解成：**你负责导出和确认，AI 负责整理、提出候选和生成建议；所有正式写入仍由你确认。**

### 环境要求

- Python 3.9+（纯标准库，无第三方依赖）；
- 本仓库（clone 或下载后解压）。

### 使用者要做的

1. 按 [导入来源](#导入来源) 在对应 AI 工具里导出聊天记录，把导出文件放进仓库的 `input/` 目录（该目录已被 Git 忽略，不会提交）。
2. 把这个仓库交给你正在使用的 AI（例如 Codex、Claude Code、Hermes 或 DeepSeek Harness），然后直接告诉它：

   ```text
   请接手这个 selfdistill 项目：
   1. 按 docs/intake.md 整理我提供的聊天记录，原始记录只放在 input/，不要提交到 Git；
   2. 按 prompts/distill.md 从头读完材料，先报告阅读边界，再提出 L1–L4 候选；
   3. L3 和个人/敏感/高风险/冲突内容逐条给我确认；只有可见、可撤回的低风险通用规则可免逐条确认；
   4. 不要直接写 canonical/、L4 或简历。等我处理候选后，先展示完整 aggregate diff，再等我明确确认才写入；
   5. 写入后再运行 python3 build.py；如果要写回 Codex、Hermes 或 DeepSeek Harness（DSH），先展示 diff，得到我明确确认后再执行 install.py。
   ```

3. 查看 AI 给出的候选，逐条确认、修改或拒绝。需要写回 AI 工具时，再确认一次 diff。

> 使用 DeepSeek Harness 的用户可以[安装 selfdistill 插件](#安装-selfdistill-插件可选)，让 DSH 的 agent 直接掌握这套工作流，无需每次粘贴上面的 prompt。

### AI 要做的

1. 阅读 `docs/intake.md`，把使用者导出的记录整理成统一 Markdown，放进已被 Git 忽略的 `input/`。
2. 按 `prompts/distill.md` 提炼 L1–L4 候选；先展示来源和候选，不直接改正式档案。
3. 只在用户已处理候选、并明确确认了最终 aggregate diff 后，才增量写入 `canonical/`（结构参考 `templates/`，仓库里的「张三」是虚构样例）。
4. 运行 `python3 build.py`，生成 `dist/index.html`、L1–L4 报告以及 `dist/codex/`、`dist/hermes/`、`dist/dsh/`。
5. 如使用者要写回，运行 `python3 install.py --target codex`（或 `hermes` / `dsh`）：先展示 diff，等使用者明确确认后再增量写入，不覆盖无关内容。

## 首次蒸馏：从完整历史建立 L1–L4

先按 [`docs/intake.md`](docs/intake.md) 把获授权的聊天整理为统一 Markdown，再使用 [`prompts/distill.md`](prompts/distill.md)。AI 必须完整阅读并报告范围、证据、冲突、时效和未读内容，只提出候选而不直接改正式档案。

L3 始终逐条确认；L1/L2/L4 中描述个人的内容，以及敏感、高风险、有争议或有冲突的内容，也都逐条确认。只有与个人无关、低风险、非敏感、无争议、无冲突的通用规则可以免逐条确认；它们仍必须单独可见、可撤回，并记录为 `policy_accepted_general`，绝不是用户逐条接受。无论候选如何通过，真正写文件前始终需要一次明确的 aggregate diff 确认。

[`templates/distill-candidates.md`](templates/distill-candidates.md) 是人看的审阅单；[`schemas/distill-candidate-v1.json`](schemas/distill-candidate-v1.json) 是给未来自动化准备的同一份字段契约。普通使用者不需要手写 JSON。

## 导入来源

**自动导入器**（推荐）：导出文件直接交给 `import_chats.py`，本地会话自动发现（先 dry-run 清单、确认后写入）：

```bash
python3 import_chats.py --source chatgpt  --path <导出目录>
python3 import_chats.py --source gemini   --path <Takeout 解压目录>
python3 import_chats.py --source deepseek --path <conversations.json 或 zip>
python3 import_chats.py --source local [--since YYYY-MM-DD] [--exclude glob] [--dry-run]
```

| 来源 | 导出入口速查 | 自动导入 |
|------|--------------|----------|
| ChatGPT 网页 | 左下角头像 → 设置 → **数据管理** → 导出数据；解压后得到 `conversations-*.json` | `--source chatgpt` |
| Gemini 网页 ⚗️ | Google Takeout → 我的活动 → **Gemini Apps** → 导出；解压后得到 `我的活动记录.html` | `--source gemini`（实验性，结构不符时请手工整理） |
| DeepSeek 网页 | 左下角头像 → **系统设置** → **数据管理** → **导出所有历史对话** | `--source deepseek` |
| 本机 Codex / Claude Code | 会话保存在 `~/.codex/sessions`、`~/.claude/projects` | `--source local`（自动发现） |

详细格式与手工整理 fallback 见 [docs/intake.md](docs/intake.md)。

## 产出与写回目标

### ① HTML 可视化

```bash
python3 build.py          # 生成 dist/
open dist/index.html      # L1–L4 分层架构、内容分布、设计原则、协同流程（支持中 / EN 切换）
```

### ② 写回 AI 工具（让 AI 持续认识你）

| 目标 | 装到哪 | 命令 | 加载方式 |
|------|--------|------|----------|
| Codex | `~/.codex`（AGENTS.md + profile/ + skills/） | `python3 install.py --target codex` | Codex 自动读取 AGENTS.md，其余按需 |
| Hermes | `~/.hermes/skills/` | `python3 install.py --target hermes` | Hermes skill 机制，按需加载 |
| DeepSeek Harness | `$DSH_HOME`（默认 `~/.dsh`） | `python3 install.py --target dsh` | persona 常驻 L1，L2/L3/L4 为 skill 按需加载 |

每次写回都**先展示 diff，确认后才写入**；重复安装增量合并，不覆盖无关内容。

#### 写回 DeepSeek Harness 的隐私分级

| 内容 | 写入位置 | 加载时机 |
|------|----------|----------|
| L1 协作契约 | `system-prompt.persona`（`$DSH_HOME/cordis.patch.yml`） | 每个新对话常驻（短、非敏感） |
| L2 决策逻辑 | `~/.dsh/skills/selfdistill-decision-logic/SKILL.md` | 按需加载 |
| L3 个人事实 | `~/.dsh/skills/selfdistill-user-profile/SKILL.md` | 按需加载；私密 L3 默认不写（`--include-private` 才包含） |
| L4 领域打法 | `~/.dsh/skills/selfdistill-<领域>/SKILL.md` | 按需加载 |

#### 安装 selfdistill 插件（可选）

写回是把「档案」装进 DSH；插件则是让 DSH 的 agent 直接掌握 selfdistill **工作流**（整理 → 提炼 → 逐条确认 → 构建 → 写回），安装后即可在 DSH 内完成整套流程：

```bash
dsh plugin --profile web add "github:ryunana/selfdistill#main&path:/dsh"
# 重启 dsh web 生效
```

- 插件包为零依赖 bundle（`selfdistill-dsh`），安装后 agent 的 skill 目录里出现 `selfdistill`；
- 发布到 npm 后可直接 `dsh plugin --profile web add selfdistill-dsh`。

## 重新导入一批新对话

如果新增的是一批完整聊天记录，继续把整理后的内容追加到 `input/`，重跑 `prompts/distill.md`，人工确认候选后再运行 `python3 build.py`（确实需要写回时再确认 `install.py`）。这个流程适合批量导入新的聊天记录，不需要任何调度器。

## 持续更新自己的档案

第一次蒸馏完成后，如果新增的是日常对话中的明确修正、表达偏差或边界补充，可以走更轻量的 inbox 流程，不必重新导入整批聊天记录：

1. 按 [`schemas/inbox-v2.json`](schemas/inbox-v2.json) 在 `inbox/` 新建一个候选 JSON。直接来自对话的候选可以先把 `evidence_ids` 留空，状态使用 `pending`。
2. 运行 `python3 distill_audit.py audit`。它会递归读取 `canonical/**/*.md` 和 `inbox/*.json`，生成完整的 `reports/latest/` 证据包与六维覆盖报告；`inbox/README.md` 只作为说明登记。
   > 每次运行 `audit` 都会重建并替换整个 `reports/latest/`。如果里面已有尚未处理的 `discoveries.md` 或 `candidates/`，请先完成审阅，或把需要保留的文件另存到 `reports/latest/` 之外。
3. 把 [`prompts/rediscovery.md`](prompts/rediscovery.md) 交给你当前选择的 AI，并要求它从头到尾阅读 `reports/latest/evidence.md`。要求它只把发现和待确认候选写回 `reports/`，不要修改 `canonical/`。
4. 运行 `python3 distill_audit.py verify reports/latest`，确认来源没有漂移、候选格式正确、所有 evidence 引用真实存在，再逐条接受、拒绝或标记为未知。`verify` 不判断候选结论是否正确，也不能证明 AI 已完整阅读全部证据，最终仍需人工审阅；`accepted` 只表示你接受了候选，不表示它已经写入 `canonical/`。
5. 由你人工把确认后的内容更新到 `canonical/`，然后继续使用原有 `python3 build.py`；确实需要写回 Codex、Hermes 或 DSH 时，再展示 diff 并明确确认 `install.py --target ...`。

## 工作证据：整理项目事实，不自动包装成果

把用户授权的项目材料交给 [`prompts/work-evidence.md`](prompts/work-evidence.md)。它会将项目背景、目标、职责、行动、交付物、结果、指标、来源和待补证分开，并严格区分参与、负责、主导与决策所有权。指标必须保留统计口径、时间窗口、基线和来源；缺失就留空，不补造数字、因果关系、职责或项目状态。

工作证据是独立、可选的审阅材料：所有个人贡献均需逐条确认，不存在通用规则免审，也不会自动写入简历、L4 或 `canonical/`。[`templates/work-evidence.md`](templates/work-evidence.md) 供人工审阅；[`schemas/work-evidence-v1.json`](schemas/work-evidence-v1.json) 供将来自动化读取，普通使用者无需手写 JSON。若日后确实要写文件，仍先展示并明确确认 aggregate diff。

## 隐私与安全

- `input/`、`inbox/`、`reports/`、`dist/` 都是本机数据或生成物，默认被 Git 忽略；仓库只保留 inbox 说明和 `input/.gitkeep`。**不要把真实聊天、候选或报告提交到公开仓库。**
- 数据默认留在本机；若把 `evidence.md` 等交给云端 AI，仍须遵守该模型供应商的数据政策。
- 私密 L3（`canonical/03-l3-private.md`）默认不构建、不写回；需要时用 `python3 build.py --include-private`。
- 所有写回都先展示 diff、人工确认后执行；重复安装增量合并，目标文件非 selfdistill 管理时拒绝覆盖。

## 依赖

纯 Python 标准库，无第三方依赖（Python 3.9+）。

## 发布前检查

```bash
python3 scripts/scan_before_release.py
```
该脚本只扫描当前工作树，不扫描 Git 历史；公开发布前还应确认历史中没有个人资料和本机作者身份。

## License

MIT
