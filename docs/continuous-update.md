# 持续更新个人档案

[English](continuous-update.en.md) | 中文

首次蒸馏完成后，根据新增内容选择更新路径，不必每次重跑全部历史。

## 路径一：导入一批新对话

适合新增了一段时间的完整聊天记录。

1. 按 [导入来源](../README.md#导入来源) 继续使用 `import_chats.py`，把新记录整理到本机 `workspace/input/`。
2. 按 [`prompts/distill.md`](../prompts/distill.md) 阅读新增材料、报告边界并提出 L1–L4 候选，不直接修改 `workspace/canonical/`。
3. 逐条审阅候选；真正写入前，再明确确认一次最终 aggregate diff。
4. 写入后运行 `python3 build.py`。确实需要写回 AI 工具时，再确认 `install.py --target ...` 的 diff。

## 路径二：记录少量日常修正

适合日常对话里出现的明确纠正、表达偏差或边界补充。

1. 按 [`schemas/inbox-v2.json`](../schemas/inbox-v2.json) 在 `workspace/inbox/` 新建一个候选 JSON。直接来自对话的候选可以暂时留空 `evidence_ids`，状态使用 `pending`。
2. 运行 `python3 distill_audit.py audit`，生成 `workspace/reports/latest/` 证据包。该命令每次都会重建这个目录；如有未处理内容，先完成审阅或移到目录外保存。
3. 把 [`prompts/rediscovery.md`](../prompts/rediscovery.md) 交给当前 AI，让它完整阅读 `workspace/reports/latest/evidence.md`。AI 只能把发现和待确认候选写回 `workspace/reports/`，不能修改 `workspace/canonical/`。
4. 运行 `python3 distill_audit.py verify reports/latest`，检查来源漂移、候选格式和 evidence 引用。
5. 人工审阅后再更新 `workspace/canonical/`，然后运行 `python3 build.py`；需要写回 AI 工具时，仍先确认 diff。

## 边界

- `accepted` 只表示候选已被接受，不表示已经写入 `workspace/canonical/`。
- `verify` 只检查完整性、格式和引用，不判断候选结论是否正确，也不能证明 AI 已完整阅读证据。
- `workspace/input/`、真实 `workspace/inbox/*.json`、`workspace/reports/` 和 `dist/` 默认被 Git 忽略，不要提交真实个人资料。
- 把证据交给云端 AI 时，提交内容仍受该模型供应商的数据政策约束。
