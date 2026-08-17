# selfdistill 全来源自动导入器实施计划

日期：2026-08-18  
状态：待执行  
设计依据：`docs/superpowers/specs/2026-08-18-chat-import-design.md`  
代码基线：`9346482`（设计文档提交）  
当前分支：`feat/chat-import`

## 1. 交付目标

实现 `import_chats.py`（纯 stdlib）：五来源（ChatGPT / Gemini / DeepSeek / 本地 Codex / 本地 Claude Code）自动整理为统一 Markdown 写入 `input/`；本地来源主动发现 + dry-run 清单 + 确认；`input/.imported.json` 去重；导入报告不静默丢弃。本增量不改 `build.py` / `install.py` / `distill_audit.py`。

## 2. 文件范围

### 新增

- `import_chats.py` —— 导入器主脚本
- `tests/test_chat_import.py` —— 单元 + CLI 集成测试
- `tests/fixtures/chat-import/` —— 各来源最小样例（结构真实、内容虚构）：
  - `chatgpt/conversations-000.json`（1 个会话，mapping 树）
  - `gemini/takeout/我的活动记录.html`（Prompted/Gemini 轮次）
  - `deepseek/conversations.json`（1 个会话，REQUEST/RESPONSE/THINK/FILE）
  - `codex/sessions/2026/08/01/rollout-x.jsonl`（session_meta + response_item 若干）
  - `claude/projects/-tmp/x.jsonl`（mode/user/assistant 行）

### 修改

- `docs/intake.md` —— 标注已有自动导入器（仍保留手工整理说明作为 fallback）
- `README.md` / `README.en.md` —— 导入来源节加一行导入器用法

### 不得修改

- `canonical/**`、`templates/**`、`prompts/**`、`schemas/**`、`build.py`、`install.py`、`distill_audit.py`

## 3. 实施步骤

### Step 1：骨架与 CLI

`import_chats.py` 主入口（argparse）：

```text
--source chatgpt|gemini|deepseek|local
--path <目录/文件>          # 导出来源必填；local 默认扫 ~/.codex/sessions + ~/.claude/projects
--since YYYY-MM-DD          # local 过滤（按会话时间）
--exclude <glob>            # local 过滤路径（可重复）
--dry-run                   # 只列清单不写文件
--yes                       # 跳过确认
--no-thinking               # DeepSeek 排除 THINK 片段
--root <dir>                # 覆盖 input/ 根（测试用）
```

### Step 2：五来源解析器（每个返回 [Message]）

`Message = (role: 'user'|'assistant', time: str|None, message_id: str, text: str, extra: dict)`

| 来源 | 解析要点 |
|---|---|
| chatgpt | 读 `conversations-*.json`（支持多分片）；mapping 按 parent/children 或 id 序遍历；`message.author.role`（仅 user/assistant）、`message.content.parts` 拼正文、`message.create_time`（unix→时间）；会话 `title`/id |
| gemini | 读 `我的活动记录.html`（`html.parser`）；按 Prompted / Gemini 轮次提取（best-effort，结构不符→跳过并报告） |
| deepseek | `conversations.json` 或 zip（解压到临时目录）；mapping 树；fragments：REQUEST=user / RESPONSE=assistant / THINK=assistant+`<!-- thinking -->`（`--no-thinking` 排除）/ FILE=`[附件: name]`；时间 `message.inserted_at` |
| codex（local） | 扫 `**/rollout-*.jsonl`；每行 json：`type=response_item` 且 `payload.type=message` → `payload.role` + `payload.content[].text`（`input_text`/`output_text`）；会话 id=payload id 或文件名；时间 `timestamp` |
| claude（local） | 扫 `**/*.jsonl`；行 `type` ∈ user/assistant → `message.content`（str 或 `[{type:text}]`）；会话 id=文件名 stem；时间行内时间戳或 `timestamp` |

### Step 3：统一输出 + 去重

- `write_conversation(src, conv_id, title, messages)` → `input/<src>-<conv_id>.md`，格式按设计 §6（source/conversation_id/exported_at + `**role**（时间；message_id: …）`）
- `input/.imported.json` = `{"<src>:<id>": {path, imported_at, title}}`；命中跳过
- `exported_at` 用会话最新时间或当天

### Step 4：主动发现 + dry-run + 确认

- `discover_local(since, excludes)`：扫描两个根，收集 `(source, session_id, title, first_time, last_time, size, path)`
- `--dry-run`：只打印清单（标题/时间/大小/路径），退出 0
- 正常导入：先打印清单 → 无 `--yes` 时 `input()` 确认 → 解析并写入 → 报告

### Step 5：导入报告

```text
DeepSeek：识别 220 个会话，导入 218，跳过 2（1 无消息 / 1 已导入过）
时间范围：2025-01-27 ~ 2026-08-18
```

### Step 6：测试

- fixtures 各来源样例；单元测试解析器（含坏 JSON / 空会话 / 未知 fragment / 未知行 type）
- CLI 集成测试：`--root <tmp>` 跑各来源 → 断言 .md 格式、.imported.json、重复跳过、dry-run 不写文件、确认交互（`--yes` 跳过）
- 回归：现有 4 个测试文件 + 发布扫描

### Step 7：文档

- `docs/intake.md`：开头注明「已有自动导入器 `import_chats.py`，手工整理说明保留为 fallback」
- README 双语「导入来源」节：每个来源加 `python3 import_chats.py --source …` 用法

## 4. 验收标准

- 五来源 fixture 全部导入成功，输出符合设计 §6 格式
- `input/.imported.json` 生效：重复导入被跳过并计入报告
- `--dry-run` 不写任何文件；无 `--yes` 时确认后才写入
- 坏输入按 §7 报告不静默
- 现有测试 + 发布扫描通过
