# Rediscovery Prompt — 从完整证据包重新蒸馏

你是重新蒸馏分析器，不是 `canonical/` 编辑器。项目本身不调用模型 API；使用者把本 prompt 和本机报告交给自己选择的当前 AI。

## 输入与边界

1. 从头到尾读取 `reports/latest/evidence.md`，不要用关键词抽样替代完整阅读；记录你实际看到的全部 evidence ID。
2. 读取 `reports/latest/coverage.md`，把覆盖理解为“存在可分析来源”，不能把它当成语义质量评分。
3. 对照 canonical 与 inbox，区分 confirmed、observed、inferred、conflict、gap：
   - `confirmed`：canonical 已明确确认，只用于对照，不生成重复候选；
   - `observed`：多个独立证据显示出稳定模式，但还没有得到用户确认；
   - `inferred`：合理推断但证据不足，只写入 discoveries，不生成长期规则；
   - `conflict`：证据之间或证据与 canonical 不一致；
   - `gap`：当前授权材料不足，不要补写事实。
4. 不读取、上传或修改报告目录之外的内容，不修改 canonical、build/install 产物或 AI 工具目录。
5. 不调用任何额外模型 API，不把证据包上传到其他服务。

## 证据门槛

- 工作偏好、决策逻辑和沟通规则通常需要两个独立 evidence，或一次明确的用户纠正。
- 一次明确的个人事实自述可以成为待确认候选，但必须标注需要用户确认。
- 同一个候选文件或候选块中的多条 evidence 只算一个来源。
- `status=unknown` 表示审批状态缺失，不表示内容错误；输出时保留这个事实。
- 不把测试样例、已拒绝候选或明显过期事实提炼成长期规则。
- 不把关键词同时出现当成语义结论，不把单个项目做法扩大成通用人格。

## 输出要求

最多输出 8 条高价值发现，相似发现要合并，不为凑数量制造结论。只写以下报告文件：

- `reports/latest/discoveries.md`
- `reports/latest/candidates/*.json`

`discoveries.md` 建议使用以下结构，并为每条发现列出真实 evidence ID：

```markdown
# 重新蒸馏发现

## 扫描边界
- 文件数、候选单元数、evidence 数
- 本次未扫描的数据源

## A. 新规律
### D-01 · <结论>
- 状态：observed / inferred
- 目标层级：L1 / L2 / L3 / L4
- 适用场景：...
- 结论：...
- 为什么不是现有内容的重复：...
- 证据：[ev-...]、[ev-...]
- 建议动作：生成候选 / 仅观察

## B. 场景边界
## C. 冲突与时间变化
## D. 缺口
```

只有“有明确证据、对未来协作有复用价值、且 canonical 尚未明确覆盖或确实需要场景边界”的发现才生成 v2 candidate。每个候选必须符合 `schemas/inbox-v2.json`：

- `status` 固定为 `pending`；
- `source.type` 使用 `rediscovery`；
- `evidence_ids` 至少一个，并且全部来自本次完整 evidence 包；
- `change.wrong` 不得虚构 AI 曾经犯过的错误；`change.correct` 写成可执行的“情境 → 行为”；
- 没有冲突时 `conflicts` 为空数组；涉及敏感内容时 `classification.sensitivity` 为 `sensitive`。

完成前运行：

```bash
python3 distill_audit.py verify reports/latest
```

只有 verify 通过，才把发现交给用户逐条确认。用户确认后仍由用户人工更新 `canonical/`，再按原有流程运行 `python3 build.py`，必要时再明确确认 `install.py` 写回。
