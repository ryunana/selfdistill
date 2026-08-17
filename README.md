# selfdistill · 蒸馏我

把和 AI 的聊天记录，在 AI 辅助 + 人工确认下，蒸馏成**看得见、带来源、AI 也用得上**的个人档案。

## 这是什么

selfdistill 是一个「AI 自我蒸馏」工具包，把你在 ChatGPT / Claude / Codex / Gemini 等工具里的历史对话，提炼成 L1–L4 分级信息：

| 层级 | 内容 | 通俗解释 |
|------|------|----------|
| L1 协作契约 | 授权边界、汇报习惯、反馈信号、表达偏好 | 「怎么和我共事」 |
| L2 决策逻辑 | 取舍原则、优先级、红线 | 「我会怎么做决定」 |
| L3 个人事实 | 身份、经历、偏好 | 「我是谁」 |
| L4 领域打法 | 可复用的工作方法 | 「我擅长什么、怎么做」 |

两个出口：① 本地多页 HTML 可视化；② 确认后增量写回你的 AI 工具（让 AI 持续认识你）。工作证据等具体领域内容由使用者自行放入 L4，不属于本工具的独立产物。

> 数据默认留在本机；「蒸馏」这一步要调云端 AI，提交给模型的内容受该供应商数据政策约束。

> **[在线查看 HTML Demo →](https://ryunana.github.io/selfdistill/)**
>
> 无需安装，示例内容全部为虚构数据；可以直接查看 L1–L4 分层、内容分布、设计原则和协同流程。

## 快速了解

```bash
python3 build.py   # 生成 dist/
open dist/index.html  # 可视化展示页：L1–L4 分层架构、内容分布、设计原则、协同流程
```

## 快速开始

你不需要先学会 Python。整个流程可以理解成：**你负责导出和确认，AI 负责整理、蒸馏、生成和写回。**

### 使用者要做的

1. 在你要蒸馏的 AI 工具里按对应入口导出聊天记录；各来源的导出入口和文件说明见 [`docs/intake.md`](docs/intake.md)。
2. 把导出的文件和这个仓库交给你正在使用的 AI（例如 Codex、Claude Code 或 Hermes），然后直接告诉它：

   ```text
   请接手这个 selfdistill 项目：
   1. 按 docs/intake.md 整理我提供的聊天记录，原始记录只放在 input/，不要提交到 Git；
   2. 按 prompts/distill.md 提炼 L1–L4 候选，逐条给我确认；
   3. 未经我确认，不要写入 canonical/；
   4. 我确认后再更新 canonical/ 并运行 python3 build.py；
   5. 如果要写回 Codex 或 Hermes，先展示 diff，得到我明确确认后再执行 install.py。
   ```

3. 查看 AI 给出的候选，逐条确认、修改或拒绝。需要写回 AI 工具时，再确认一次 diff。

### AI 要做的

1. 阅读 `docs/intake.md`，把使用者导出的记录整理成统一 Markdown，放进已被 Git 忽略的 `input/`。
2. 按 `prompts/distill.md` 提炼 L1–L4 候选；先展示来源和候选，不直接改正式档案。
3. 只把使用者确认过的内容写进 `canonical/`（结构参考 `templates/`，仓库里的「张三」是虚构样例）。
4. 运行 `python3 build.py`，生成 `dist/index.html`、L1–L4 报告以及 `dist/codex/`、`dist/hermes/`。
5. 如使用者要写回，运行 `python3 install.py --target codex`（或 `hermes`）：先展示 diff，等使用者明确确认后再增量写入，不覆盖无关内容。

## 支持矩阵

| 来源 | 状态 |
|------|------|
| 本机 Codex / Claude Code / ChatMemo | 📄 手工整理说明 |
| ChatGPT 网页导出（「数据管理」菜单） | 📄 按格式整理说明 |
| Gemini 网页导出（Takeout · 我的活动 · Gemini Apps） | 📄 有导入说明 |
| DeepSeek 网页导出 | 📄 有导入说明 |

## 手动更新（有新对话后）

追加到 `input/` → 重跑同一蒸馏 prompt → 人工确认 diff → `python3 build.py`（+ `install.py` 如需要）。无需任何调度器。

## 持续更新自己的档案

第一次蒸馏完成后，可以用本地 inbox 保留后续对话中的明确修正、表达偏差和边界补充：

1. 按 [`schemas/inbox-v2.json`](schemas/inbox-v2.json) 在 `inbox/` 新建一个候选 JSON。直接来自对话的候选可以先把 `evidence_ids` 留空，状态使用 `pending`。
2. 运行 `python3 distill_audit.py audit`。它会递归读取 `canonical/**/*.md` 和 `inbox/*.json`，生成完整的 `reports/latest/` 证据包与六维覆盖报告；`inbox/README.md` 只作为说明登记。
3. 把 [`prompts/rediscovery.md`](prompts/rediscovery.md) 交给你当前选择的 AI，并要求它从头到尾阅读 `reports/latest/evidence.md`。它只能把发现和待确认候选写回 `reports/`，不会自动修改 `canonical/`。
4. 运行 `python3 distill_audit.py verify reports/latest`，确认来源没有漂移、候选格式正确、所有 evidence 引用真实存在，再逐条接受、拒绝或标记为未知。
5. 由你人工把确认后的内容更新到 `canonical/`，然后继续使用原有 `python3 build.py`；确实需要写回 Codex 或 Hermes 时，再展示 diff 并明确确认 `install.py --target ...`。

`inbox/*.json`、`reports/`、`input/` 和 `dist/` 都是本机数据或生成物，默认被 Git 忽略；仓库只保留 inbox 说明和 `input/.gitkeep`。数据默认留在本机，但如果你把 `evidence.md` 交给云端 AI，仍须遵守该模型供应商的数据政策。不要把真实聊天、候选或报告提交到公开仓库。

## 依赖

纯 Python 标准库，无第三方依赖（Python 3.9+）。

## 发布前检查

```bash
python3 scripts/scan_before_release.py
```
该脚本只扫描当前工作树，不扫描 Git 历史；公开发布前还应确认历史中没有个人资料和本机作者身份。

## License

MIT
