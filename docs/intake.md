# 统一 Markdown 输入格式（intake）

selfstill 的蒸馏输入是「统一 Markdown」：不管聊天来自哪个 AI 工具，先整理成同一种中性格式，AI 才能稳定地从中提炼 L1–L4。这一步是手工/半手工的，selfstill 不提供自动导入器。

## 格式约定

一个文件 = 一段对话（一个会话，或一个来源导出的片段）。文件头用 HTML 注释标注来源，正文每条消息用 `**role**（时间）：` 开头。

```markdown
# <来源> · <会话标题>

<!-- source: chatgpt -->
<!-- exported_at: 2026-08-13 [SIMULATED] 示例元数据 -->

**user**（示例时间）：
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

来源标识建议：`chatgpt` / `gemini` / `deepseek` / `codex` / `claude` / `chatmemo`，可自定。

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

### DeepSeek

网页导出 → 按会话整理成统一 Markdown。

### 本机 Codex / Claude Code / ChatMemo

这些来源目前需要按上面的统一格式手工或半手工整理；仓库不提供自动导出脚本。

整理完成后，把文件放进 `input/` 目录（该目录已被 `.gitignore` 忽略，不会提交到仓库）。
