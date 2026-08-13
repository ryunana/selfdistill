# selfstill · 蒸馏我

把和 AI 的聊天记录，在 AI 辅助 + 人工确认下，蒸馏成**看得见、带来源、AI 也用得上**的个人档案。

## 这是什么

selfstill 是一个「AI 自我蒸馏」工具包，把你在 ChatGPT / Claude / Codex / Gemini 等工具里的历史对话，提炼成 L1–L4 分级信息：

| 层级 | 内容 | 通俗解释 |
|------|------|----------|
| L1 协作契约 | 授权边界、汇报习惯、反馈信号、表达偏好 | 「怎么和我共事」 |
| L2 决策逻辑 | 取舍原则、优先级、红线 | 「我会怎么做决定」 |
| L3 个人事实 | 身份、经历、偏好 | 「我是谁」 |
| L4 领域打法 | 可复用的工作方法 | 「我擅长什么、怎么做」 |

两个出口：① 本地多页 HTML 可视化；② 确认后增量写回你的 AI 工具（让 AI 持续认识你）。工作证据等具体领域内容由使用者自行放入 L4，不属于本工具的独立产物。

> 数据默认留在本机；「蒸馏」这一步要调云端 AI，提交给模型的内容受该供应商数据政策约束。

## 快速了解

```bash
python3 build.py   # 生成 dist/
open dist/index.html  # 可视化展示页：L1–L4 分层架构、内容分布、设计原则、协同流程
```

## 快速开始

1. **整理聊天记录**：按 `docs/intake.md` 把各来源导出整理成统一 Markdown，放进 `input/`。
2. **蒸馏**：用 `prompts/distill.md` 喂给你选择的 AI，生成 L1–L4 候选。
3. **填 canonical**：确认后把结果填进 `canonical/`（参考 `templates/` 空白模板和 `canonical/` 里的虚构样例「张三」）。
4. **构建**：
   ```bash
   python3 build.py
   ```
   生成 `dist/index.html` 及 L1–L4 可视化/原始报告页面 + `dist/codex/` + `dist/hermes/`。
5. **写回**（可选）：
   ```bash
   python3 install.py --target codex     # 或 hermes
   ```
   展示 diff → 你确认 → 增量写入 `~/.codex` 或 `~/.hermes`。只做三件事：不存在则新建、存在则替换标记块间内容、无标记则追加，不覆盖你已有的无关内容。

## 支持矩阵

| 来源 | 状态 |
|------|------|
| 本机 Codex / Claude Code / ChatMemo | 📄 手工整理说明 |
| ChatGPT 网页导出（「数据管理」菜单） | 📄 按格式整理说明 |
| Gemini 网页导出（Takeout · 我的活动 · Gemini Apps） | 📄 有导入说明 |
| DeepSeek 网页导出 | 📄 有导入说明 |

## 手动更新（有新对话后）

追加到 `input/` → 重跑同一蒸馏 prompt → 人工确认 diff → `python3 build.py`（+ `install.py` 如需要）。无需任何调度器。

## 依赖

纯 Python 标准库，无第三方依赖（Python 3.9+）。

## 发布前检查

```bash
python3 scripts/scan_before_release.py
```
该脚本只扫描当前工作树，不扫描 Git 历史；公开发布前还应确认历史中没有个人资料和本机作者身份。

## License

MIT
