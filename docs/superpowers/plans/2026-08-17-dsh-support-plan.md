# selfdistill × DeepSeek Harness 支持实施计划

日期：2026-08-17  
状态：待执行  
设计依据：`docs/superpowers/specs/2026-08-17-dsh-support-design.md`  
代码基线：`c618526`（设计文档提交，rebase 后）  
当前分支：`main`（本地）

## 1. 交付目标

按已批准设计实现三块能力：① `install.py --target dsh` 写回目标（persona 只放 L1，L2/L3/L4 为按需加载 skill）；② 仓库内 `dsh/` DSH 插件包（bundle 形态，零依赖，git 源一行安装）；③ 社区展示（`dsh-plugin` topic + README 章节）。实现由主会话完成，不改动现有 codex/hermes 行为。

## 2. 文件范围

### 新增

- `dsh/package.json` —— selfdistill-dsh，`dsh.bundle.patch`，零依赖
- `dsh/cordis.patch.yml` —— insert 自身
- `dsh/index.mjs` —— Cordis entry，`inject: ['skills']`，运行时注册 `selfdistill` skill
- `dsh/skills/selfdistill/SKILL.md` —— <500 行工作流指南
- `dsh/skills/selfdistill/references/workflow.md` —— 详细分步
- `docs/superpowers/plans/2026-08-17-dsh-support-plan.md` —— 本文件
- `tests/test_dsh_install.py` —— install.py dsh 逻辑单元测试

### 修改

- `build.py` —— `build_targets` 增加 DSH 产物
- `install.py` —— 新增 `--target dsh`
- `README.md` —— 「DeepSeek Harness 支持」章节
- `docs/superpowers/specs/2026-08-17-dsh-support-design.md` —— L4 skill 名改为 `selfdistill-<领域>` 的一致性修正

### 不得修改

- `canonical/**`、`templates/**`、`prompts/**`、`distill_audit.py`、`docs/intake.md`
- 现有 codex/hermes 产物结构（`dist/codex`、`dist/hermes` 保持字节一致）

## 3. 实施步骤

### Step 1：build.py —— DSH 产物

在 `build_targets(l1, l2, l3, domains)` 内新增：

```text
dist/dsh/
├── persona.md                       # wrap(l1)：标记包裹整份内容
└── skills/
    ├── selfdistill-decision-logic/SKILL.md
    ├── selfdistill-user-profile/SKILL.md
    └── selfdistill-<fid>/SKILL.md      # 每个 L4 打法
```

- skill 文件格式（frontmatter 必须在顶部，标记在正文内作所有权标签）：
  ```markdown
  ---
  name: selfdistill-<fid>
  description: "<desc>"
  ---
  
  <!-- distill:begin -->
  <正文>
  <!-- distill:end -->
  ```
- L2/L3 描述常量：`DSH_L2_DESCRIPTION`（决策逻辑，任务涉及权衡/排序/风险时按需加载）、`DSH_L3_DESCRIPTION`（个人事实，需要了解用户背景/身份/偏好时按需加载）
- L4 复用 canonical frontmatter 的 `description`（已是 "Use when..." 路由风格），skill 名 `selfdistill-<fid>`
- persona.md 只含 L1（不含 L3 私密；`--include-private` 时 L3 skill 正文含私密——沿用 build.py 现有合并逻辑）
- 新 helper：`dsh_skill_content(fid, desc, text)`（frontmatter + 标记 + 正文）

### Step 2：install.py —— --target dsh

- DSH 根：`os.environ.get("DSH_HOME")` 缺省 `Path.home()/".dsh"`（常量 `DSH_HOME`）
- 目标映射（重构 `collect_plans` 为按 target 解析 dest）：
  - `persona.md` → `$DSH_HOME/cordis.patch.yml`：persona 合并（见下）
  - `skills/<name>/SKILL.md` → `$DSH_HOME/skills/<name>/SKILL.md`：整文件替换（所有权规则）
- persona 合并（`merge_persona(existing, persona_md, opener)`）：
  1. 文件不存在 → 新建：`- id: system-prompt\n  config:\n    persona: |-\n      <opener>\n\n      <persona_md>`（persona_md 自带标记）
  2. 已存在且 persona 区域含 `<!-- distill:begin -->` → 替换标记之间内容（复用 `merge()` 的标记逻辑）
  3. 已存在 `system-prompt` 行但无标记 → 报错拒绝（fail loud）
  4. 已存在但无 `system-prompt` 行 → 列表末尾追加
- 默认 opener：`You are a coding agent powered by the {{model}} model. Your working directory is {{cwd}}.`，环境变量 `SELFDISTILL_DSH_PERSONA_OPENER` 覆盖
- L1 含 `{{`/`}}` → 警告（persona 模板无转义）
- 安全检查：`safe_target_path` 的 root 换成 `$DSH_HOME`；拒绝符号链接；skills 目标文件已有但无标记 → 拒绝
- diff 确认 UX 与 codex/hermes 一致；`--target` choices 增加 `dsh`

### Step 3：dsh/ 插件包

- `package.json`：`name: selfdistill-dsh`，`type: module`，`main: ./index.mjs`，`exports`，`files: [index.mjs, cordis.patch.yml, skills]`，`dsh.bundle.patch: ./cordis.patch.yml`，零依赖，MIT
- `cordis.patch.yml`：`- insert: - id: selfdistill-dsh, name: 'selfdistill-dsh'`
- `index.mjs`：`export const name/inject/apply`；`ctx.effect(() => ctx.skills.register({ name: 'selfdistill', description, whenToUse, content, resourceBase }))`；正文从包内 `skills/selfdistill/SKILL.md` 读取（`node:fs` + `import.meta.url`）
- SKILL.md 大纲：前置（clone 仓库或使用已有 checkout）→ 导出记录入 `input/` → 读 `docs/intake.md` + `prompts/distill.md` 提炼 L1–L4 → 用 DSH 提问能力逐条确认 → 写 `canonical/` → `build.py` → `install.py --target dsh`（展示 diff 确认）→ 持续更新（audit + rediscovery）；隐私红线（真实数据不入库、私密 L3 默认不写）
- references/workflow.md：分步细节

### Step 4：README.md

- 「DeepSeek Harness 支持」章节：写回用法（`--target dsh` + 隐私说明）、插件一行安装命令（git 源 `github:ryunana/selfdistill#main&path:/dsh`，注明 npm 发布后可用 `dsh plugin --profile web add selfdistill-dsh`）
- 快速开始第 5 步与「手动更新」处补充 DSH

### Step 5：tests/test_dsh_install.py

unittest + tempfile（沿用现有风格），覆盖：
- `merge_persona`：新建 / 标记替换 / 无标记报错 / 追加行
- 所有权规则：新文件 / 有标记整文件替换 / 无标记拒绝
- `DSH_HOME` 环境变量生效
- install.py 模块可导入（不改 `main` 结构）

### Step 6：验证

1. `python3 build.py` → 断言 `dist/dsh/` 产物、frontmatter 合法、默认无私密 L3、codex/hermes 字节不变
2. `python3 build.py --include-private` → L3 skill 含私密
3. `DSH_HOME=<tmp> python3 install.py --target dsh --yes` → 断言 cordis.patch.yml 结构、skills 落盘、重复安装合并、无标记拒绝
4. `python3 install.py --target codex --yes`（临时 HOME）回归
5. 插件包：`dsh plugin --profile selftest add <abs>/dsh` + `dsh --profile selftest --dump-config` 断言插入行；`node` mock-ctx 冒烟断言 skill 注册
6. `python3 -m unittest tests.test_dsh_install` + 现有测试回归 + `python3 scripts/scan_before_release.py`

### Step 7：社区与发布

- `gh repo edit ryunana/selfdistill --add-topic dsh-plugin`
- 询问用户是否 push 到 GitHub（本地已完成全部验证后再 push）

## 4. 验收标准

- `--target dsh` 安装后：`$DSH_HOME/cordis.patch.yml` 的 `system-prompt.persona` 只含 L1 + 开场白；`$DSH_HOME/skills/` 出现 selfdistill-* skill；重复安装幂等；无标记文件被保护
- `dsh plugin --profile web add "github:ryunana/selfdistill#<ref>&path:/dsh"` 安装后，DSH agent 目录中出现 `selfdistill` skill（重启 web 生效）
- README 提供可直接复制的安装命令
- 现有测试与发布扫描通过
