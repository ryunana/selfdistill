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

你只需要做两件事：**① 导出聊天记录 → ② 把项目链接和导出位置一句话发给你的 AI 助手**。之后的整理、提炼、生成候选、构建、写回全部由 AI 助手完成，你只在最后逐条确认结果。

### 你要做的

1. 按 [导入来源](#导入来源) 在对应 AI 工具里导出聊天记录，记下导出文件在本机的存放位置。
2. 把项目链接发给你正在使用的 AI（Codex、Claude Code、Hermes 或 DeepSeek Harness 等），一句话说明：

   ```text
   按这个项目蒸馏我：https://github.com/ryunana/selfdistill
   我的聊天记录导出在：<这里填导出文件在本机的路径>
   ```

   AI 助手会自己 clone 项目、读取接手指令（`AGENTS.md`）、导入记录、提出 L1–L4 候选。
3. 查看 AI 给出的候选，逐条确认、修改或拒绝；写回 AI 工具前再确认一次 diff。

> 使用 DeepSeek Harness 的用户可以[安装 selfdistill 插件](#安装-selfdistill-插件可选)，让 DSH 的 agent 直接掌握这套工作流，无需每次发送上面的链接说明。

### AI 助手会做什么（自动，无需你操心）

AI 助手 clone 项目后会自动读取根目录的 `AGENTS.md` 接手指令，按「导入 → 提炼候选 → 逐条确认 → 写 canonical/ → 构建 → 写回」执行。完整流程见 `AGENTS.md` 和 `prompts/distill.md`。

手动完成每个步骤的说明（不依赖 AI 助手）见下方各节。

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
# local --path 指向混合 JSONL 目录时：
python3 import_chats.py --source local --path <目录> --local-format auto|codex|claude --dry-run
```

导入器会把 Gemini 的每次 `Prompted` 活动单独输出；ChatGPT 在 `current_node` 有效时只保留活动路径，只有字段缺失或为 `null` 时才会保留并拆分已验证的根到叶分支；字段存在但格式非法或所指节点不存在会拒绝并报告。DeepSeek 的分支会拆成独立会话，而不是拼成假对话。图片和授权附件只保留可读占位，模型思考、工具过程与已知本机内部注入不会进入 Markdown。`--dry-run` 会完整解析并显示预计新导入、更新、重复和失败数，但不会创建文件。退出码 `0` 表示成功（含预期内部内容排除），`2` 表示部分成功，`1` 表示全部失败或致命错误。

| 来源 | 导出入口速查 | 自动导入 |
|------|--------------|----------|
| ChatGPT 网页 | 左下角头像 → 设置 → **数据管理** → 导出数据；解压后得到 `conversations-*.json` | `--source chatgpt` |
| Gemini 网页 ⚗️ | Google Takeout → 我的活动 → **Gemini Apps** → 导出；解压后得到 `我的活动记录.html` | `--source gemini`（每个 Prompted 活动一份会话；活动容器不可靠时停止并改用手工整理） |
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
