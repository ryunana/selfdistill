# AGENTS.md — selfdistill 接手指令

> 本文件面向**接手这个项目的 AI 助手**（Codex / Claude Code / Hermes / DeepSeek Harness / WorkBuddy 等）。你 clone 本项目后应自动读取本文件并照做，无需使用者再提供额外提示词。

## 你的任务

使用者会把项目链接发给你，并说类似「按这个项目蒸馏我，我的聊天记录导出在 <路径>」。你要做的是：把使用者的聊天记录整理成统一 Markdown，提炼 L1–L4 个人档案候选，经使用者逐条确认后写入正式档案、构建可视化，并（可选）写回 AI 工具。

## 流程

1. **导入**：读 `docs/intake.md`。使用者会告诉你原始导出在本机的哪个目录/文件。运行 `python3 import_chats.py --source <来源> --path <原始导出路径>`（来源：`chatgpt` / `gemini` / `deepseek` / `local`），把导出整理成统一 Markdown 写入 `input/`。原始导出保留在仓库外本机目录，绝不提交到 Git。本地来源先 `--dry-run` 出清单、经使用者确认后再写。
2. **提炼候选**：按 `prompts/distill.md` 从头读完 `input/` 全部材料，先报告阅读边界，再提出 L1–L4 候选，附来源证据。**只提候选，绝不直接改 `canonical/`、L4 或简历。**
3. **逐条确认**：L3 和个人/敏感/高风险/冲突内容逐条请使用者确认；只有可见、可撤回的低风险通用规则可免逐条确认（记为 `policy_accepted_general`）。
4. **写入**：使用者处理完候选、明确确认最终 aggregate diff 后，才增量写入 `canonical/`（结构参考 `templates/`，仓库里的「张三」是虚构样例）。
5. **构建**：运行 `python3 build.py` 生成 `dist/index.html`、L1–L4 报告与各写回产物。
6. **写回（可选）**：使用者要写回时，运行 `python3 install.py --target codex|hermes|dsh|workbuddy`；先展示 diff，经使用者明确确认后再增量写入，不覆盖无关内容。

## 硬规则

- 未经使用者确认，**绝不**写入 `canonical/`、L4、简历或任何正式文件；写回前先展示 diff。
- 数据默认留在本机；「蒸馏」一步会调用云端 AI，提交给模型的内容受该供应商数据政策约束。
- 只有使用者本人消息和使用者明确授权的第一方材料能证明使用者事实；AI 回复、搜索结果、工具输出、虚构样例不能作为候选证据。
