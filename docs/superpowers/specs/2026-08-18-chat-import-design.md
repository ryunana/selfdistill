# selfdistill 全来源自动导入器设计

日期：2026-08-18  
状态：架构方向已批准，待用户复核书面设计  
基线：GitHub `main` 提交 `dc78c65`（PR #3 DSH 支持已合并）

## 1. 结论

新增 `import_chats.py`（纯 Python 标准库，无第三方依赖）：把五个来源的聊天记录**自动整理成统一 Markdown**，遵循 `docs/intake.md` 的格式约定与 PR #4 的 ID 契约，写入已被 Git 忽略的 `input/`：

- **导出文件来源**：ChatGPT（`conversations-*.json`）、Gemini（Takeout `我的活动记录.html`）、DeepSeek（`conversations.json` 或压缩包）；
- **本地会话主动发现**：Codex（`~/.codex/sessions/**/rollout-*.jsonl`）、Claude Code（`~/.claude/projects/**/*.jsonl`）——默认 **dry-run 清单先行**，用户确认后才写入；
- **导入报告**：识别 N 条 / 跳过 M 条（附原因）/ 时间范围，不静默丢弃；
- **去重**：`input/.imported.json` 记录已导入会话，重复导入自动跳过。

本增量**只做导入器**；候选→canonical 受控写回是紧随其后的下一个增量（见 §10 路线图）。

## 2. 用户价值

1. 消灭「手工/半手工整理」这个最大的上手摩擦——导出文件直接进 `input/`；
2. 本地 Codex / Claude Code 会话**不用导出**，扫描即得，可批量、可按时间过滤；
3. 隐私优先：主动发现先出清单、确认后才写入；全程本地处理，不上传任何内容；
4. 与 PR #4 的 ID 契约对齐（`conversation_id` / `message_id` / `exported_at`），为下一个增量（候选→canonical 受控写回）铺好证据链基础。

## 3. MVP 边界

### 本次要做

- `import_chats.py`：五个来源解析器 + CLI（`--source` / `--path` / `--since` / `--exclude` / `--dry-run`）；
- 本地主动发现（Codex / Claude Code），默认 dry-run 清单先行；
- 统一 Markdown 输出（含 ID 契约），写入 `input/`；
- 导入报告 + `input/.imported.json` 去重；
- 每个来源一个最小测试 fixture + 单元/集成测试。

### 本次不做

- 候选生成、`canonical/` 写回（下一增量）；
- 自动脱敏、本地模型（Ollama）、云端任何调用；
- 其他平台（ChatMemo 等）解析器；
- 修改现有 `build.py` / `install.py` / `distill_audit.py` 行为。

## 4. 各来源格式（已实测确认）

| 来源 | 输入 | 消息结构 | 角色判定 |
|---|---|---|---|
| ChatGPT 网页导出 | `conversations-*.json`（可能分片） | `mapping` 消息树；节点 `message.author.role`、`message.content.parts`、`message.create_time` | 显式 role |
| Gemini Takeout | `我的活动记录.html` | Prompted / Gemini 轮次段落 | 按轮次 |
| DeepSeek 网页导出 | `conversations.json`（顶层列表）或 zip | `mapping` 消息树；节点 `message.fragments`（`REQUEST`=用户 / `RESPONSE`=回复 / `THINK`=推理 / `FILE`=附件）；时间 `message.inserted_at` | 按 fragment 类型推断 |
| 本地 Codex | `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl` | 每行 `{timestamp, type, payload}`；`type=response_item` 且 `payload.type=message` 时 `payload.role` + `payload.content[].text`（`input_text`/`output_text`） | 显式 role |
| 本地 Claude Code | `~/.claude/projects/<编码路径>/<uuid>.jsonl` | 每行 `{type, message}`；`type` ∈ user/assistant 时 `message.content[].text`（跳过 mode/permission-mode/summary 等元数据行） | 行 type |

## 5. CLI 与行为

```bash
# 导出文件来源
python3 import_chats.py --source chatgpt --path <导出目录或文件>
python3 import_chats.py --source gemini  --path <Takeout 解压目录>
python3 import_chats.py --source deepseek --path <conversations.json 或 zip>

# 本地主动发现
python3 import_chats.py --source local --dry-run                    # 先列清单（会话标题/时间/大小/来源路径）
python3 import_chats.py --source local --since 2026-08-01           # 确认后导入；--since 过滤
python3 import_chats.py --source local --exclude '*/数据看板*'       # --exclude glob 排除
python3 import_chats.py --source local --path ~/.codex/sessions     # 覆盖默认根目录
```

- **本地主动发现默认行为**：导入前总是先列出会话清单并请求确认（`--yes` 可跳过确认）；`--dry-run` 只列清单、不写任何文件；
- **输出命名**：`input/<source>-<conversation_id>.md`（本地来源用原始 session id）；
- **去重**：`input/.imported.json` = `{ "<source>:<id>": {path, imported_at, title} }`，命中即跳过并计入报告「已导入过」；
- **报告**：stdout 输出「识别 / 导入 / 跳过（原因：无消息 / 格式未知 / 已导入过 / 被排除 / 损坏）」+ 时间范围。

## 6. 统一 Markdown 输出（遵循 intake.md + PR #4 ID 契约）

```markdown
# <来源> · <会话标题>

<!-- source: <chatgpt|gemini|deepseek|codex|claude> -->
<!-- conversation_id: <原始会话 id> -->
<!-- exported_at: <YYYY-MM-DD> -->

**user**（YYYY-MM-DD HH:MM；message_id: <原始 id 或序号>）：
<正文>

**assistant**（…）：
<正文>
```

- 时间缺失标 `（未知）`；message_id 缺失用文件内序号（如 `#17`），**绝不补造**；
- DeepSeek `THINK` 片段**默认归入 assistant 正文**（推理也是模型输出），在其前加一行 `<!-- thinking -->` 注释便于区分，`--no-thinking` 可排除；`FILE` 片段记为 `[附件: <file_name>]`；
- 保持原始文本，不做任何改写或脱敏（脱敏是后续增量的独立能力）。

## 7. 错误处理

| 情形 | 行为 |
|---|---|
| JSON 损坏 / HTML 结构不符合预期 | 跳过该会话，报告原因，不静默 |
| 无 user/assistant 消息的会话 | 跳过并报告 |
| 重复导入（.imported.json 命中） | 跳过，计入报告 |
| 符号链接 / 无权限文件 | 跳过并报告 |
| 未知 `--source` / 缺 `--path` | 用法错误，退出非零 |
| dry-run 清单为空 | 提示「未发现可导入会话」，退出 0 |

## 8. 测试

- `tests/fixtures/chat-import/`：每个来源一个最小样例（结构真实、内容全部虚构，符合发布扫描）；
- 解析器单元测试：正确提取 role/时间/正文/ID，异常输入（坏 JSON、空会话、未知 fragment）按 §7 处理；
- CLI 集成测试（临时目录）：各 `--source` 跑通 → 断言 output/ 格式、`.imported.json` 写入、重复导入跳过、dry-run 不写文件；
- 回归：现有 `test_distill_audit.py` / `test_dsh_install.py` / `test_prompt_contracts.py` + 发布扫描。

## 9. 隐私

- 全部本地处理，不调用任何云端；
- dry-run 清单只显示**会话标题 / 时间 / 大小 / 来源路径**，不预览正文；
- `.imported.json` 只存 id / 路径 / 导入时间，不存正文；
- 导入内容进入 `input/`（gitignored）；真实数据绝不提交仓库。

## 10. 路线图（后续增量）

1. **本增量**：全来源自动导入器；
2. **候选→canonical 受控写回**：读 PR #4 候选契约（`schemas/distill-candidate-v1.json`），生成 canonical 修改预览 → L3 逐条确认 / 通用规则 `policy_accepted_general` → 最终 aggregate diff 确认 → 写入前快照、失败可恢复、重复执行不产生重复；
3. **可选**：自动脱敏预览（生成替换映射供审阅）、更多平台解析器、本地模型路径。
