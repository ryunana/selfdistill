# selfstill 持续蒸馏 MVP 实施计划

日期：2026-08-16  
状态：待新版 Sol Advisor 角色在新任务中执行  
设计依据：`docs/superpowers/specs/2026-08-16-continuous-distillation-mvp-design.md`  
代码基线：`8979cd7`  
当前分支：`feat/continuous-distillation-mvp`

## 1. 交付目标

在不改变现有构建和安装行为的前提下，为公开版 selfstill 增加一个本地持续蒸馏闭环：记录候选、全量生成证据、查看六维覆盖、由当前 AI 重新发现规律、人工确认、验证来源与引用。

本次由一个 Luna / Max 实现角色完成全部已确定工作，避免多 Agent 拆分带来的协调成本。主会话负责检查完整 diff、重跑验证并判断是否需要 Terra；最后由新的 Sol / High 角色只读复审。

## 2. 文件范围

实现角色只允许新增或修改以下文件：

- `.gitignore`
- `README.md`
- `distill_audit.py`
- `schemas/inbox-v2.json`
- `inbox/README.md`
- `prompts/rediscovery.md`
- `scripts/scan_before_release.py`
- `tests/__init__.py`
- `tests/test_distill_audit.py`
- `tests/fixtures/continuous-distillation/**`

不得修改：

- `build.py`
- `install.py`
- `canonical/**`
- `templates/**`
- HTML Demo 文件
- 已提交的设计文档
- 用户私有项目 `~/personal-distillation/**`

私有项目只作为只读方法参考，任何真实 canonical、inbox、reports、manifest、backups 或个人信息都不得复制进公开仓库。

## 3. Milestone 1：本地候选与隐私边界

### 产物

- `schemas/inbox-v2.json`
- `inbox/README.md`
- `.gitignore` 更新
- `scripts/scan_before_release.py` 的受保护目录检查

### 行为

1. 一个 JSON 文件记录一条候选；新候选默认 `pending`。
2. 直接从对话记录的候选允许 `evidence_ids` 为空。
3. rediscovery 生成的候选必须至少引用一个 evidence ID。
4. `input/`、`inbox/*.json`、`reports/`、`dist/` 默认不被 Git 跟踪。
5. 发布检查使用 Git 跟踪清单识别受保护目录中的异常文件，只打印路径，不打印敏感正文。
6. 允许跟踪的例外只有 `input/.gitkeep` 与 `inbox/README.md`。

### 验证

```bash
python3 scripts/scan_before_release.py
git check-ignore input/example.md inbox/example.json reports/latest/evidence.md dist/index.html
```

成功标准：扫描通过；四类本地数据路径均被忽略；仓库说明文件仍被跟踪。

## 4. Milestone 2：最小审计与证据生成

### 产物

- `distill_audit.py`
- `tests/fixtures/continuous-distillation/**`
- `tests/test_distill_audit.py`

### CLI

```bash
python3 distill_audit.py audit
python3 distill_audit.py verify reports/latest
```

### audit 行为

1. 项目根固定为脚本所在目录，不受当前终端目录影响。
2. 递归读取 `canonical/**/*.md`，读取 `inbox/*.json`，把 `inbox/README.md` 仅登记为说明文件。
3. canonical 以二级标题区块形成证据；没有二级标题的文件形成一条文件级证据。
4. inbox 中每个合法 JSON 形成一条候选证据。
5. evidence ID 由相对路径、标题和同名序号生成，不使用内容哈希，保证正文微调后引用不变。
6. inventory 单独保存每个输入文件的完整 SHA-256，用于检测来源漂移。
7. 只在 `reports/latest/` 写入 `inventory.json`、`evidence.jsonl`、`evidence.md` 和 `coverage.md`。
8. 使用临时目录生成后整体切换；报告目录权限为 `0700`，文件为 `0600`。
9. 不修改 canonical、inbox、input、dist 或 AI 工具目录。
10. 没有 inbox 候选时正常完成，并报告候选数为 0。

### coverage 行为

六个维度只做可解释的来源映射，不进行内容打分：

- D1：L3 与 L4；
- D2：inbox 修正；
- D3：L1、表达类 L4 与 inbox；
- D4：L2、产品/Agent 类 L4 与 inbox；
- D5：候选中的外部证据字段；
- D6：带时间、临时或过期标记的 canonical 与 inbox。

某维度没有来源时明确标记 `gap`。

## 5. Milestone 3：验证与重新发现合同

### 产物

- `prompts/rediscovery.md`
- `distill_audit.py verify` 完整行为

### verify 行为

以下任一情况返回非零：

- 当前输入文件集合与 inventory 不一致；
- 任一输入 SHA-256 变化；
- JSON 候选格式非法；
- evidence ID 重复；
- `discoveries.md` 引用不存在的 evidence ID；
- `reports/latest/candidates/*.json` 格式非法或引用不存在的 evidence ID；
- rediscovery candidate 没有 evidence ID；
- 报告路径位于 `reports/` 之外或是符号链接。

### rediscovery prompt 行为

- 要求从头到尾读取完整 `evidence.md`；
- 区分 confirmed、observed、inferred、conflict 和 gap；
- 不把关键词命中当成语义结论；
- 工作偏好通常需要两个独立证据或一次明确纠正；
- 单次明确个人事实可以成为待确认候选；
- 最多输出 8 条高价值发现；
- 只写 reports，不自动修改 canonical；
- 不调用额外模型 API。

## 6. Milestone 4：用户说明与完整验收

### README 更新

在不改变现有首次使用路径的前提下，新增“持续更新自己的档案”章节，按用户动作解释：

1. 把明确修正记录到 inbox；
2. 运行 audit；
3. 让当前 AI 按 rediscovery prompt 阅读完整证据；
4. 审批 discoveries 和 candidates；
5. 人工更新 canonical；
6. 继续使用原有 build/install。

说明本地数据边界、云端 AI 数据政策和禁止提交的目录。

### 自动测试

最小测试覆盖：

1. 合法 inbox 候选通过，缺字段或非法枚举失败；
2. canonical 与 inbox 全部进入 inventory；
3. 没有 inbox 候选时 audit 仍成功；
4. evidence ID 在正文变化后保持稳定；
5. audit 不修改输入文件；
6. 来源哈希变化后 verify 失败；
7. 未知 evidence 引用失败；
8. rediscovery candidate 的空 evidence 引用失败；
9. 从项目外目录运行仍使用正确项目根；
10. 输出只位于 reports。

### 完整验证命令

```bash
python3 -m unittest discover -s tests -v
python3 distill_audit.py audit
python3 distill_audit.py verify reports/latest
python3 build.py
python3 -m py_compile build.py install.py distill_audit.py scripts/scan_before_release.py
python3 scripts/scan_before_release.py
git diff --check 8979cd7
git status --short
git diff --stat 8979cd7
git ls-files input inbox reports dist
```

成功标准：

- 所有测试和命令返回 0；
- build 行为无回归；
- Git 跟踪清单中只有允许的说明或占位文件；
- diff 仅包含已批准文件；
- 没有个人数据、绝对用户路径、密钥或真实报告；
- 没有数据库、服务、调度、模型 API 或自动 canonical 写入。

## 7. Sol Advisor 执行合同

### Luna / Max 实现

OBJECTIVE：完成上述本地持续蒸馏闭环，并保持公开版原有 build/install 接口不变。

FILES AND OWNERSHIP：只拥有第 2 节列出的文件；不是独自在代码库中工作，必须保留其他人或用户的并行修改，不得回退无关变更。

INTERFACES：保留现有命令；新增 `distill_audit.py audit` 与 `distill_audit.py verify [report]`；保持 Python 3.9+ 标准库运行。

CONSTRAINTS：遵守第 3–6 节全部行为；不复制真实私有数据；不扩大 MVP；不提交或推送。

VERIFICATION：运行第 6 节完整命令并返回实际输出证据；完成声明没有证据即无效。

### 主会话验收

1. 检查全部工作树 diff 和文件范围；
2. 逐项重跑完整验证；
3. 检查生成报告与 Git 跟踪清单；
4. 检查私有数据和绝对路径泄漏；
5. 判断 Luna 结果是否暴露高风险或规格误解；只有必要时才升级 Terra。

### Sol / High 最终复审

主会话验证通过后，启动一个新的只读 Sol reviewer，检查实际 diff、接口兼容、隐私边界、测试充分性和范围控制，只能返回：

- `ship`：可以交付；
- `fix-first`：有明确必须修复的问题；
- `rethink`：架构或范围需要重做。

任何复审后的代码修改都会使原 verdict 失效，必须重新验证并重新复审。
