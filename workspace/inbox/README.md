# 持续蒸馏 inbox

这里是本机的候选暂存区。一个 `*.json` 文件记录一条候选，格式见
[`../../schemas/inbox-v2.json`](../../schemas/inbox-v2.json)。真实候选会被 Git 忽略；本说明文件是仓库中唯一保留的 inbox 内容。

## 记录规则

- 新候选的 `status` 使用 `pending`；`accepted` 只表示你接受了候选，不表示它已经写入 `workspace/canonical/`。
- 直接来自对话的候选可以暂时使用空的 `evidence_ids`，下一次 audit 会把这条 JSON 作为一条证据。
- 由 rediscovery 产生的候选必须引用至少一个真实的 `ev-` evidence ID。`distill_audit.py verify` 会检查引用是否存在。
- `status` 只能是 `pending`、`accepted`、`rejected` 或 `unknown`。
- 候选可以包含敏感内容；它们只留在本机，不要把 `workspace/inbox/` 或 `workspace/reports/` 提交到 Git。

一个最小的直接对话候选（全部内容均为虚构示例）：

```json
{
  "schema_version": 2,
  "id": "conversation-example-01",
  "created_at": "2026-08-16T12:00:00+08:00",
  "source": {
    "type": "conversation",
    "reference": "local chat, turn 3",
    "quote": "[SIMULATED] 请把结论放在前面。"
  },
  "classification": {
    "feedback_type": ["表达方式"],
    "target_layer": "L1",
    "target_section": "汇报与完成",
    "scope": "contextual",
    "sensitivity": "normal"
  },
  "change": {
    "scene": "[SIMULATED] 交付小工具时",
    "wrong": "[SIMULATED] 先罗列过程。",
    "correct": "[SIMULATED] 先说明结果和验证状态。",
    "proposed_action": "[SIMULATED] 写入待确认候选。"
  },
  "evidence_ids": [],
  "conflicts": [],
  "status": "pending"
}
```
