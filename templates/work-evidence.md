# 工作证据审阅单

> 这是独立的工作/项目证据材料，不是简历、L4 或 canonical。只处理用户授权材料。每条事实、交付物、指标和表达建议都有自己的 `review.status`；顶层进度不等于接受任何子项。任何文件写入前仍需展示并确认 aggregate diff。

## 读取边界与整份审阅进度

- 获授权项目材料：
- 已读范围与时间范围：
- 未读、打不开或截断：
- 敏感信息处理：
- 顶层 `status`（仅审阅进度）：`pending` / `in_review` / `reviewed` / `unknown`

## 项目：<名称>

> `project.name` 只作显示。背景、目标、项目状态必须分别放进下方带来源、验证状态和逐项决定的 claims，不能在此处另写无来源事实。

### 已证实事实

| Claim ID | 类型 | 陈述 | 所有权程度 | 验证状态 | 来源与最短摘录 | 你的决定 / `review.status` | `review.note`（需要时） |
|---|---|---|---|---|---|---|---|
| C-001 | background / goal / status / responsibility / action / result |  | participated / responsible / led / decision_owner / not_applicable / unknown | verified |  | pending |  |

### 用户自述

| Claim ID | 类型 | 陈述 | 所有权程度 | 验证状态 | 来源与最短摘录 | 你的决定 / `review.status` | `review.note`（需要时） |
|---|---|---|---|---|---|---|---|
| C-002 | background / goal / status / responsibility / action / result |  | participated / responsible / led / decision_owner / not_applicable / unknown | user_stated |  | pending |  |

### 指标

| 名称 | 数值 | 单位 | 统计口径 | 时间窗口 | 基线 | 验证状态 | 来源 | 你的决定 / `review.status` | `review.note`（需要时） |
|---|---|---|---|---|---|---|---|---|---|
|  |  |  |  |  |  | verified / user_stated / third_party_stated / unknown |  | pending |  |

### 交付物

| 交付物 | 说明 | 对应 Claim IDs | 来源 | 你的决定 / `review.status` | `review.note`（需要时） |
|---|---|---|---|---|---|
|  |  |  |  | pending |  |

### 表达建议（另行审批，不覆盖事实）

#### 简历建议

| 正文 | 对应 Claim IDs | 你的决定 / `review.status` | `review.note`（需要时） |
|---|---|---|---|
|  |  | pending |  |

#### L4 建议

| 正文 | 对应 Claim IDs | 你的决定 / `review.status` | `review.note`（需要时） |
|---|---|---|---|
|  |  | pending |  |

### 待补证

- 缺口：
- 为什么当前不能声称：
- 可补充的材料：

## 决定与写入边界

- 每个可审阅子项的 `review.status`：`pending` / `user_accepted` / `user_modified` / `user_rejected` / `deferred` / `unknown`。顶层 `status` 仅表示整份审阅进度，不能推断任何一项已接受。
- `verified` claim 或指标至少要有第一方产物；`user_stated` 至少要有用户自述；`third_party_stated` 至少要有第三方评价。用户自述指标必须标为 `user_stated`，不能伪装为 `verified`。
- 不补造数字、指标口径、时间窗口、基线、职责、主导/决策所有权、因果关系、结果或项目状态。
- 不自动写简历、L4 或 `canonical/`；如要写入，先生成精确 aggregate diff 并取得明确确认。
