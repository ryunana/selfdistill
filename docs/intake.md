# 统一 Markdown 输入格式（intake）

selfdistill 的蒸馏输入是「统一 Markdown」：不管聊天来自哪个 AI 工具，先整理成同一种中性格式，AI 才能稳定地从中提炼 L1–L4。这一步是手工/半手工的，selfdistill 不提供自动导入器。

## 格式约定

一个文件 = 一段对话（一个会话，或一个来源导出的片段）。文件头用 HTML 注释标注来源，正文每条消息用 `**role**（时间）：` 开头。尽量保留原始 ID；没有原始 ID 时，用相对文件路径 + 消息序号定位，绝不根据上下文补造时间或 ID。

```markdown
# <来源> · <会话标题>

<!-- source: chatgpt -->
<!-- conversation_id: fictional-conversation-001 -->
<!-- exported_at: 2026-08-13 [SIMULATED] 示例元数据 -->

**user**（示例时间；message_id: fictional-message-001）：
<!-- [SIMULATED] 以下为虚构示例，不代表真实个人身份。 -->
[SIMULATED] 我是一名虚构示例用户，想做一档关于电影的播客。

**assistant**（示例时间）：
[SIMULATED] 好呀，我们聊聊你的想法。
```

字段约定：

| 字段 | 约定 |
|------|------|
| role | 只用 `user` / `assistant` 两个，中性，不做额外分类 |
| 时间 | 尽量带，格式 `YYYY-MM-DD HH:MM`；缺时间标 `（未知）` |
| 来源 | 文件头 `<!-- source: xxx -->`，用简短标识 |
| conversation_id | 推荐在文件头写原始会话 ID；没有则不编造，后续用相对文件路径定位 |
| exported_at | 推荐在文件头记录导出时间；未知则写 `未知` |
| message_id | 推荐每条消息保留原始消息 ID；没有则按文件中的消息序号（如 `#17`）定位 |
| 授权附件 | 写明来源、所有者和本次授权范围；未获授权的附件不要放入输入 |

来源标识建议：`chatgpt` / `gemini` / `deepseek` / `codex` / `claude`，可自定。

## 各来源怎么整理成统一 Markdown

### ChatGPT（网页「数据管理」导出）

1. 网页左下角头像 → 设置 → **数据管理** → 导出数据（导出聊天记录）。
2. 得到压缩包，解压后包含 `conversations-000.json`、`conversations-001.json` …（对话按 100 条分片存储）+ `chat.html`（网页版）+ `file-*.dat`（附件）。
3. 用任意 JSON 工具读 `conversations-*.json`：每个元素是一条对话，字段含 `title`（会话标题）、`create_time`、`mapping`（消息树）。`mapping` 里每个节点的 `message.author.role` 区分 `user` / `assistant`，`message.content.parts` 是正文，`message.create_time` 是时间。
4. 按 `title` 一个会话一个文件，把 `user` / `assistant` 轮次整理成统一 Markdown。

### Gemini（Google Takeout「我的活动」导出）

1. Google Takeout 勾选 **Gemini Apps**（位于「我的活动」分组下）→ 导出。
2. 解压后路径为 `Takeout/我的活动/Gemini Apps/`，核心是 `我的活动记录.html`（含 Prompted / Gemini 轮次），其余是对话中上传/生成的附件。
3. 打开 `我的活动记录.html`，按「Prompted」（你输入的）/「Gemini」（模型回复）轮次，按会话整理成统一 Markdown。

### DeepSeek（网页「数据管理」导出）

1. 网页左下角头像 → **系统设置** → **数据管理** → **导出所有历史对话**。
2. 得到导出文件（JSON 或压缩包，按会话组织），按会话整理成统一 Markdown。

### 本机 Codex / Claude Code

这些来源的记录保存在本机目录，可以把整理工作交给正在使用的 AI 工具协助：把记录交给 AI，让它按上面的统一格式整理成 Markdown（原始记录仍只放在 `input/`）。

整理完成后，把文件放进 `input/` 目录（该目录已被 `.gitignore` 忽略，不会提交到仓库）。这是手工/半手工整理格式，不代表仓库会自动导入、调用模型或读取任何平台账户。首次处理时，把统一 Markdown、现有 `canonical/` 和所需授权附件交给 AI，并使用 `prompts/distill.md`；它应先报告完整阅读边界，再提出候选，不直接写正式档案。
