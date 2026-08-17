# selfstill × DeepSeek Harness 支持设计

日期：2026-08-17  
状态：架构方向已批准，待用户复核书面设计  
基线：GitHub `main` 提交 `9950baa`

## 1. 结论

为 selfstill 增加 DeepSeek Harness（DSH）支持，分三块：

1. **写回目标**：`install.py --target dsh` 把蒸馏出的 L1–L4 档案增量写入本机 DSH 配置；
2. **DSH 插件包**：仓库内新增 `dsh/` 目录，发布为 npm 包（bundle 形态，零依赖），DSH 用户一行命令安装后，DSH 代理即掌握 selfstill 完整蒸馏工作流；
3. **社区展示**：给仓库添加 `dsh-plugin` GitHub topic（dshfind 插件市场自动收录），README 增加 DSH 支持章节。

隐私原则：**persona 只放 L1 协作契约**（短、非敏感、应当始终生效）；L2/L3/L4 全部做成 DSH 按需加载的 skill，敏感内容默认不进入每个新对话的上下文；私密 L3 默认不写入（沿用 `build.py --include-private` 约定）。

## 2. 用户价值

1. DSH 用户可一行安装 selfstill 插件，在 DSH 内完成「导出 → 蒸馏 → 确认 → 构建 → 写回」全流程；
2. 蒸馏出的个人档案写回 DSH 后，**新对话只常驻 L1**（协作契约），L2 决策逻辑 / L3 个人事实 / L4 领域打法按需加载，敏感信息不默认暴露；
3. 现有 codex / hermes 写回不受影响，DSH 与其完全平行；
4. 插件包经 git 源一行安装（产物在库、无构建步骤），npm 发布为可选后续。

## 3. MVP 边界

### 本次要做

- `build.py`：新增 `dist/dsh/` 产物（persona + skills）；
- `install.py`：新增 `--target dsh`（尊重 `$DSH_HOME`，默认 `~/.dsh`）；
- 新增 `dsh/` 插件包（bundle 形态：`package.json` + `cordis.patch.yml` + `index.mjs` + `skills/selfstill/`）；
- README 增加「DeepSeek Harness 支持」章节；
- 最小自动测试（install.py dsh 映射纯函数 + 插件 entry 冒烟）；
- 仓库添加 `dsh-plugin` topic。

### 本次不做

- 不改造现有 codex / hermes 写回；
- 不新增 DSH 会话导入（输入来源矩阵不变）；
- 不发布到 npm（npm 未认证，git 源安装已可用；发布留作手动步骤）；
- 不做 awesome 精选列表 PR（列为可选后续）；
- 不自动调用任何模型 API；蒸馏仍由使用者当前选择的 AI 完成；
- 不把任何真实个人数据提交进仓库。

## 4. DSH 机制事实（设计依据）

- **persona**：`system-prompt` 行的 `persona` 配置以 order-0 段渲染，**每个会话的每次模型请求都完整携带**（前缀稳定、KV 缓存友好）。写 L3 敏感事实进 persona = 默认暴露给所有对话。→ persona 只放 L1。
- **skills**：`skill-filesystem` 提供者扫描 `<project>/.dsh/skills`、`~/.dsh/skills`（用户根，rank 400）等目录；会话开始时 agent 只看到目录（name + description），正文经 `skill` 工具**按需加载**。→ L2/L3/L4 全部走 `~/.dsh/skills/`。
- **home 级 patch**：`$DSH_HOME/cordis.patch.yml` 在 profile patch 之后叠加，可 patch `system-prompt` 行（整行 config 替换）。
- **插件形态**：外部插件 = npm 包，经 `dsh plugin --profile web add <包>` 安装；声明 `dsh.bundle.patch` 的包进 profile 层栈（重启生效）；`cordis.patch.yml` 用 `- insert: - id: <id> name: '<包名>'` 挂载自身；包不声明 `@deepseek-ai/*` 依赖（profile pnpm 闭包注入）。
- **运行时 skill 注册**：`ctx.skills.register({ name, description, whenToUse?, content, resourceBase? })` 返回 disposer；host 组合中 `inject: ['skills']` 可用。

## 5. ① 写回目标：`install.py --target dsh`

### 5.1 build.py 产物

`python3 build.py`（默认）额外生成：

```text
dist/dsh/
├── persona.md                 # L1 协作契约（不含 L3 私密）
└── skills/
    ├── selfstill-decision-logic/SKILL.md   # L2 决策逻辑
    ├── selfstill-user-profile/SKILL.md     # L3 个人事实（默认不含私密；--include-private 时包含）
    └── <领域>/SKILL.md                     # 每个 L4 打法一个
```

每个 SKILL.md 带 frontmatter（`name` kebab-case、`description` 写明「何时才加载」）；正文含蒸馏来源引用。私密 L3 沿用 `build.py` 的 `--include-private` 语义：默认不生成，传参才生成。

### 5.2 install.py 目标映射

| dist/dsh 产物 | 安装目标 | 合并规则 |
|---|---|---|
| `persona.md` | `$DSH_HOME/cordis.patch.yml` 中 `system-prompt.persona` | 标记**区域**合并（`<!-- distill:begin/end -->` 之间替换，其余字节不变） |
| `skills/<name>/SKILL.md` | `$DSH_HOME/skills/<name>/SKILL.md` | **整文件替换**，以标记存在性为所有权判定（见下） |

- DSH 根：`os.environ.get("DSH_HOME")`，缺省 `Path.home()/".dsh"`。
- **persona 合并规则**（纯字符串操作，保持既有文件字节不变）：
  1. `cordis.patch.yml` 不存在 → 新建，写入 `- id: system-prompt` + `config.persona`（默认开场白常量 + 标记块 + L1）；
  2. 已存在且 `system-prompt` 行的 persona 含 distill 标记 → 只替换标记块之间内容；
  3. 已存在 `system-prompt` 行但 persona 无标记（用户自定义）→ 报错拒绝（fail loud，提示手动处理），不盲改；
  4. 已存在但无 `system-prompt` 行 → 在列表末尾追加该行。
- **SKILL.md 所有权规则**：frontmatter 必须在文件顶部（provider 依赖它解析 name/description）；正文内放 `<!-- distill:begin -->` 标记作为 selfstill 所有权标签。已存在文件含标记 → 整文件替换（frontmatter 更新可传播）；已存在且无标记 → 拒绝（不覆盖未知内容）；不存在 → 新建。
- 默认开场白常量（已实测本机 rc.7 web profile 默认：`You are a coding agent powered by the {{model}} model. Your working directory is {{cwd}}.`，来自 dsh-web-app bundle patch），可用环境变量 `SELFSTILL_DSH_PERSONA_OPENER` 覆盖；若 L1 内容含 `{{`/`}}`（persona 模板无转义）→ 警告。
- **确认 UX**：与 codex/hermes 完全一致 —— 先展示 diff，`--yes` 可跳过；安全检查（拒绝符号链接、非普通目录/文件）沿用现有 `reject_symlink` / `safe_target_path`。

### 5.3 隐私与安全

- persona 常驻 = 仅 L1（协作契约，非敏感）；L2/L3/L4 按需加载；
- 私密 L3 默认不生成、不写入；
- 所有内容只写本机 `$DSH_HOME`；
- 每次安装先展示 diff、人工确认。

## 6. ② DSH 插件包 `dsh/`

### 6.1 文件结构

```text
dsh/
├── package.json              # name: selfstill-dsh；type: module；main: ./index.mjs；
│                             # dsh.bundle.patch → ./cordis.patch.yml；files: 全部；零依赖
├── cordis.patch.yml          # - insert: - id: selfstill-dsh, name: 'selfstill-dsh'
├── index.mjs                 # Cordis entry：注册 selfstill 运行时 skill
└── skills/selfstill/
    ├── SKILL.md              # <500 行：DSH 代理跑完整蒸馏流程的工作流指南
    └── references/
        ├── workflow.md       # 分步细节
        └── faq.md            # 常见问题（可选）
```

### 6.2 入口契约（index.mjs）

```js
import { readFileSync } from 'node:fs'

export const name = 'selfstill-dsh'
export const inject = ['skills']
export function apply(ctx) {
  ctx.effect(() => ctx.skills.register({
    name: 'selfstill',
    description: '…按需路由描述…',
    whenToUse: '…',
    content: readFileSync(new URL('./skills/selfstill/SKILL.md', import.meta.url), 'utf-8'),
    resourceBase: { kind: 'directory', path: /* 包内 skills/selfstill 绝对路径 */ },
  }))
}
```

- `ctx.skills.register` 返回 disposer，`ctx.effect` 持有生命周期（disable 时清理）；
- 不 import 任何 `@deepseek-ai/*`（零依赖，避免公共 npm 解析失败）；
- 单一事实源：SKILL.md 在包内，运行时读取，不复制正文进代码。

### 6.3 skill 内容（SKILL.md 大纲）

> 插件的 skill 是**工作流指南**；提示词正文仍以仓库 `prompts/`、`docs/intake.md` 为单一事实源。

1. 前置：确认 selfstill 仓库可用（无则 `git clone https://github.com/ryunana/selfstill`）；
2. 用户导出聊天记录 → 放入 `input/`（不入 Git）；
3. 读 `docs/intake.md` + `prompts/distill.md`，提炼 L1–L4 候选；
4. **逐条人工确认**（用 DSH 的提问能力，未确认不写 `canonical/`）；
5. 确认后更新 `canonical/`，运行 `python3 build.py`；
6. 写回 DSH：`python3 install.py --target dsh`（先展示 diff，确认后执行）；
7. 持续更新：`distill_audit.py audit` + `prompts/rediscovery.md` 流程。

### 6.4 安装与验证

- 安装（git 源一行，产物在库无需构建）：
  ```sh
  dsh plugin --profile web add "github:ryunana/selfstill#<commit>&path:/dsh"
  ```
  或本地验证：`dsh plugin --profile selftest add <绝对路径>/dsh`（用独立测试 profile，不碰用户 web profile）。
- 验证：`dsh --profile selftest --dump-config` 确认插入行；`node` 冒烟测试 index.mjs（mock ctx 断言 skill 注册）；安装后重启 web 生效。

## 7. ③ 社区展示

- `gh repo edit ryunana/selfstill --add-topic dsh-plugin` → dshfind.com 插件市场自动收录；
- README「DeepSeek Harness 支持」章节：写回用法、插件一行安装命令、隐私说明；
- 可选后续：awesome 精选列表 PR（awesome-deepseek-harness 等）、npm publish。

## 8. 错误处理

| 情形 | 行为 |
|---|---|
| `dist/dsh/` 不存在 / 为空 / 非普通目录 | 拒绝安装（沿用现有检查） |
| `cordis.patch.yml` 已有自定义 persona 且无标记 | fail loud，提示手动处理 |
| 目标路径是符号链接 / 父路径非目录 | 拒绝（沿用 `safe_target_path`） |
| L1 内容含 `{{`/`}}` | 警告（persona 模板无转义） |
| 插件 entry 加载失败 | cordis 报错并停止该行；不静默 |
| `dsh` 未安装 / pnpm 缺失 | 安装命令由 DSH 报错，README 注明前置 |

## 9. 测试计划

1. `python3 build.py`（仓库自带 canonical 样例）→ 断言 `dist/dsh/` 产物齐全、frontmatter 合法、默认不含私密 L3；
2. `python3 build.py --include-private` → `dist/dsh/skills/selfstill-user-profile/SKILL.md` 含私密内容；
3. `DSH_HOME=<临时目录> python3 install.py --target dsh` → 断言 `cordis.patch.yml` 结构、skills 落盘、重复安装增量合并、diff 确认流程（`--yes` 跳过）；
4. 现有 codex/hermes 目标回归（build + install 到临时 HOME）；
5. 插件包：`dsh plugin --profile selftest add <路径>/dsh` + `--dump-config` 断言插入行；`node` mock-ctx 冒烟断言 skill 注册成功；
6. `python3 scripts/scan_before_release.py` 通过；
7. 现有测试 `tests/test_distill_audit.py` 回归。

## 10. 已知限制

- persona 是模板（`{{…}}` 无转义）：内容含花括号双写时需警告或改写；
- home 级 persona patch 会替换 `system-prompt` 行整行 config：若使用者已在别处自定义 persona，diff 预览会暴露差异，需人工确认；
- 默认开场白常量随 DSH 版本可能漂移：实现时以本机 `dsh --dump-config` 为准，提供环境变量覆盖；
- 插件 skill 依赖用户网络 clone 主仓库（提示词单一事实源在仓库）；离线场景由用户在安装时自行准备。

## 11. 开放问题

- 插件包名 `selfstill-dsh` 是否保留（npm 发布前可改，git 源安装不受影响）；
- 是否在本次就把仓库 push 到 GitHub 并加 topic（gh 已以 ryunana 登录，可代为执行）。
