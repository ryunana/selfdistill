# Rediscovery Prompt — 从现有蒸馏包重新发现规律

## 角色边界

你是重新蒸馏分析器，不是 canonical 编辑器。

你可以：

- 读取 `reports/latest/evidence.md` 与 `coverage.md`；
- 读取 `reports/latest/active-candidates.jsonl` 与 `candidate-lifecycle.json`；
- 比较 canonical 和 inbox；
- 识别尚未明确表达的规律、场景边界、冲突、时间变化和缺口；
- 写 `reports/latest/discoveries.md`；
- 写 `reports/latest/candidates/*.json`。

你不得：

- 修改 canonical、staging、backups、manifest 或运行时 profile；
- 把推断写成 confirmed；
- 用关键词抽样代替完整 evidence；
- 把测试数据、已拒绝候选或明显过期事实提炼成长期规则；
- 无意义复述 `[SENSITIVE]` 原文；
- 调用额外模型/API 或把证据包上传到其他服务。

## 输入读取要求

1. 从头到尾读取完整 `evidence.md`，记录全部 evidence ID。
2. 读取 `coverage.md`，但不得把“有来源”解释为“已经充分蒸馏”。
3. 只把 `active-candidates.jsonl` 中的候选作为待处理项。生命周期中处于 `applied/rejected/superseded` 的候选不得重复提议；证据曾被其他关闭决策引用，不代表引用该证据的原候选已完整处理。只有出现更新证据所证明的真实变化或冲突时，才能为已关闭候选生成后继候选。
4. 对每个候选结论回看当前 canonical，判断它是：
   - 已明确存在：不作为新发现；
   - 只存在局部暗示：可作为“显性化”候选；
   - 需要限定场景：作为“场景边界”候选；
   - 与现有规则冲突或代表变化：作为“冲突与变化”；
   - 当前证据不足：作为 gap，不生成规则。

## 证据门槛

- 姓名、健康、关系、经历等个人事实：一次明确自述即可成为候选，但必须标记需要用户确认。
- 工作偏好、决策逻辑、沟通规则：通常需要至少 2 条互相独立的 evidence，或 1 条明确纠正。
- 跨项目通用规则：必须证明不是单个项目的一次性做法。
- 多条 evidence 来自同一候选块时，只算一个来源。
- `status=unknown` 只代表状态缺失，不代表内容错误；可以分析，但输出时标明审批状态缺失。
- 测试候选不得用于生成个人规律。
- `accepted` 表示已获同意但尚未写回，仍需进入写回队列；`applied/rejected/superseded` 都是关闭状态，不得重新排队。

## 结论状态

每条发现只能使用以下一种：

- `confirmed`：canonical 已明确确认，仅用于说明对照，不生成候选；
- `observed`：多个证据显示稳定模式，但用户尚未确认；
- `inferred`：合理推断但证据不足，只进入 discoveries，不生成长期规则；
- `conflict`：证据之间或证据与 canonical 冲突；
- `gap`：授权材料不足。

## 输出一：discoveries.md

按以下结构输出：

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
...

## C. 冲突与时间变化
...

## D. 缺口
...
```

最多输出 8 条高价值新发现。相似发现合并，不为凑数量制造结论。

## 输出二：v2 candidates

仅为满足以下条件的发现生成 JSON：

- 有明确证据；
- 对未来协作有复用价值；
- 当前 canonical 尚未明确覆盖，或确实需要补场景边界；
- 可以写成“什么场景 → 过去哪里不对 → 正确行为是什么”。

每个文件必须符合 `schemas/inbox-v2.json`：

- `id`：`rediscovery-YYYYMMDD-<slug>-<8位短哈希>`；
- `status`：固定为 `pending`；
- `evidence_ids`：全部必须真实存在；
- `classification.sensitivity`：涉及 `[SENSITIVE]` 时为 `sensitive`；
- `classification.scope`：谨慎选择 universal / contextual / temporary / one_off；
- `change.wrong`：说明当前缺口或容易出现的错误，不得虚构 AI 曾经犯过；
- `change.correct`：用可执行的“情境 → 行为”表达；
- `conflicts`：记录冲突 evidence ID 或 canonical 位置，没有则为空数组。

## 完成前自检

1. 所有 evidence ID 都存在；
2. 没把现有 canonical 原句换个说法冒充新发现；
3. 没把单个简历项目写法扩大为通用人格；
4. 没把敏感事实加载成无关任务的默认规则；
5. 所有候选均为 pending；
6. 未修改 canonical；
7. 没有重新提出已关闭候选；
8. 运行 `python3 distill_audit.py verify reports/latest` 通过。
