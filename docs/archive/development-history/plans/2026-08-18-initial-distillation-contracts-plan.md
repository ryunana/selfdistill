# selfdistill 首次蒸馏补全实施计划

日期：2026-08-18

状态：书面规格已通过，待 Terra / High 实现

设计依据：`docs/superpowers/specs/2026-08-18-initial-distillation-contracts-design.md`

代码基线：`f3da8e6`

## 1. 交付目标

在不改变现有构建、安装和持续蒸馏代码的前提下，补齐公开版首次蒸馏与工作证据两条入口。交付完整 Prompt、人类可读模板、面向未来自动化的机器格式、README/输入说明和防回退测试。

确认机制采用已批准的分级规则：

- L3 永远逐条确认；
- L1/L2/L4 中涉及个人的结论逐条确认；
- 与个人无关、低风险、无争议、无敏感信息、无冲突的通用规则可免逐条确认；
- 免审内容必须可见、可撤回，机器记录不能伪装成用户亲自接受；
- 所有内容真正写入文件前仍需总 diff 确认。

## 2. 文件范围与所有权

Terra 只允许新增或修改：

- `prompts/distill.md`
- `prompts/work-evidence.md`
- `schemas/distill-candidate-v1.json`
- `schemas/work-evidence-v1.json`
- `templates/distill-candidates.md`
- `templates/work-evidence.md`
- `docs/intake.md`
- `README.md`
- `tests/test_prompt_contracts.py`

不得修改：

- `prompts/rediscovery.md`（本次没有必须调整的术语冲突）
- `build.py`
- `install.py`
- `distill_audit.py`
- `canonical/**`
- `templates/showcase-html/**`
- 既有测试与 fixture
- 已批准的设计和本计划
- 任何私有项目文件

当前工作树中 `README.md` 已有用户改动。实现者必须先阅读并保留，不得回退或覆盖。

## 3. 首次蒸馏 Prompt

重写 `prompts/distill.md`，使其可以独立交给常见 AI 使用，并包含：

1. 输入说明和 L1–L4 定义；
2. 历史材料是数据而不是指令，防止提示注入；
3. 只有用户消息和授权第一方材料能证明用户事实；
4. 防止 assistant 幻觉、搜索结果、第三方人物、示例数据污染；
5. 从头到尾阅读、扫描边界和未完成声明；
6. 明确说过、多次表现、暂时推测、存在冲突、资料不足五类判断；
7. L1/L2/L4 的多场景证据门槛和单项目不可泛化；
8. 对现有 canonical 去重、处理冲突、过期和替代；
9. 敏感信息最小化与私有文件建议；
10. 个人结论与通用规则的确认分流；
11. 通用规则免审条件和“伪常识绕审”防护；
12. 第一阶段只展示扫描结果和候选，第二阶段才生成 canonical 精确修改建议；
13. 即使候选已接受或免审，写文件前仍要展示总 diff 并确认；
14. Markdown 候选输出格式，并说明有文件能力时可同时输出符合 Schema 的 JSON。

Prompt 不得要求直接输出或修改 canonical，也不得把推测和资料不足包装成可写入候选。

## 4. 首次蒸馏候选格式

新增 `schemas/distill-candidate-v1.json`，采用 JSON Schema Draft 2020-12。顶层拒绝未知字段，至少包含：

- `schema_version`：固定为 1；
- `id`、`created_at`；
- `target`：`layer`、`section`、可选 `domain_id`；
- `statement`；
- `assessment`：
  - `basis`：`explicit`、`observed`、`conflict`；
  - `scope`：`universal`、`contextual`、`temporary`、`one_off`；
  - `nature`：`personal`、`general_rule`；
  - `sensitivity`：`normal`、`sensitive`；
  - `confidence`：`low`、`medium`、`high`；
  - `risk`：`low`、`high`；
  - `controversy`：`none`、`present`；
- `sources`：至少一条，每条含 `type`、`reference`、`quote`、`role`、`occurred_at`；
- `conflicts`、`supersedes`；
- `proposed_action`：`add`、`amend`、`replace`、`keep_separate`；
- `review`：`requirement` 和 `reason`；
- `status`。

状态必须区分：`pending`、`user_accepted`、`user_modified`、`user_rejected`、`deferred`、`policy_accepted_general`、`unknown`。

Schema 条件至少保证：

- L3 必须是 `personal`、需要用户确认，不能使用 `policy_accepted_general`；
- `waived_general` 只能用于 `general_rule`、L1/L2/L4、normal、low risk、无争议、无冲突的候选，并对应 `policy_accepted_general`；
- `personal`、`sensitive`、high risk、存在争议或冲突的候选都必须走用户确认；
- `inferred` 和 `gap` 不属于这个 Schema 的可写入候选。

新增 `templates/distill-candidates.md`，包含扫描边界、需确认的个人候选、免逐条确认的通用规则、暂时推测、冲突和资料不足。候选卡片字段与 Schema 一致，但用中文说明。

## 5. 工作证据 Prompt 与格式

新增 `prompts/work-evidence.md`，必须做到：

- 只处理用户授权的项目材料；
- 区分用户自述、第一方产物、第三方评价和未知；
- 按项目整理背景、目标、职责、行动、交付物、结果、指标和来源；
- 严格区分参与、负责、主导和决策；
- 指标保留口径、时间窗口、基线和来源，缺失就留空；
- 禁止补造数字、职责、所有权、因果关系和项目状态；
- 将已证实事实、用户自述、表达建议和待补证分开；
- 敏感信息最小化；
- 不自动写入简历、L4 或 canonical；
- 所有工作证据均涉及个人，必须逐条确认，不适用通用规则免审。

新增 `schemas/work-evidence-v1.json`，顶层拒绝未知字段，至少包含：

- `schema_version`、`id`、`created_at`；
- `project`：名称、背景、目标；
- `claims[]`：编号、类型、陈述、所有权程度、验证状态、来源；
- `deliverables[]`；
- `metrics[]`：名称、数值、单位、口径、时间窗口、基线、来源；
- `resume_suggestions[]`：正文和对应 claim IDs；
- `l4_suggestions[]`：只作为另行审批建议；
- `sensitivity`、`gaps[]`、`status`。

工作证据状态不包含自动免审。新增 `templates/work-evidence.md`，明确分为“已证实事实、用户自述、表达建议、待补证”四区。

## 6. 输入说明与 README

更新 `docs/intake.md`：

- 文件级推荐记录 `source`、`conversation_id`、`exported_at`；
- 消息级推荐记录 `message_id`、角色和时间；
- 没有原始 ID 时用相对文件路径 + 消息序号定位；
- 缺时间写未知，不推算；
- 授权文档和附件标明来源与所有者；
- 保持现有来源整理说明，不声称自动导入。

更新 `README.md`：

- 保留当前未提交的“重新导入一批新对话”和持续更新说明；
- 首屏定位不改；
- 清楚区分首次蒸馏、持续蒸馏、工作证据三条路径；
- 首次蒸馏说明分级确认和最终 diff 确认；
- 工作证据说明其独立、可选、不自动进入 L4/简历；
- 说明机器格式为未来自动化准备，普通用户无需手写 JSON；
- 不承诺尚未实现的自动导入、模型调用或审批页面。

## 7. 防回退测试

新增 `tests/test_prompt_contracts.py`，只用 Python 标准库：

1. 解析两个 JSON Schema；
2. 检查 schema 版本、必要顶层字段、关键枚举和条件结构；
3. 检查首次蒸馏 Prompt 含证据边界、提示注入、完整阅读、五类判断、证据门槛、冲突/时效、敏感信息、分级确认、最终 diff 确认；
4. 检查 L3 和个人/高风险内容不能免审；
5. 检查通用规则免审必须可见、可撤回，且机器状态不冒充用户确认；
6. 检查工作证据 Prompt 禁止补造指标、升级所有权和自动写入；
7. 检查两个 Markdown 模板含核心字段；
8. 检查 README 出现三条路径；
9. 检查 `prompts/distill.md` 不再包含“直接输出 canonical”或未经确认写入的旧合同。

测试应检查合同语义所需的稳定短语或字段，不对整段文案做脆弱的全文快照。

## 8. 验证

实现者和主任务均需运行：

```bash
python3 -m unittest discover -s tests -v
python3 distill_audit.py audit
python3 distill_audit.py verify reports/latest
python3 build.py
python3 -m py_compile build.py install.py distill_audit.py scripts/scan_before_release.py
python3 scripts/scan_before_release.py
git diff --check
git status --short
git diff --stat f3da8e6
git ls-files input inbox reports dist
```

成功标准：

- 所有命令返回 0；
- diff 只包含批准文件和进入任务前已存在的 README 改动；
- 没有真实个人资料、聊天内容、密钥、绝对用户路径或生成报告被跟踪；
- 现有 build/install/audit 行为无回归；
- Prompt、模板、Schema、README 语义一致；
- 没有模型 API、数据库、服务、自动写入或私有运行时复制。

## 9. Sol Advisor 执行

1. 由 Terra / High 在上述文件范围内实现；
2. 主任务检查完整 diff、保留的 README 修改、Schema 约束和 Prompt 全文；
3. 主任务重跑第 8 节全部验证；
4. 新建一个 Sol / High reviewer，只读检查实际累计 diff；
5. reviewer 必须对提示注入、证据污染、主体混淆、截断、过度泛化、冲突/过期、敏感信息、伪造工作证据、分级确认绕过、伪常识免审、未来方案 C 接口和范围控制发起对抗式审查；
6. verdict 只能是 `ship`、`fix-first` 或 `rethink`；
7. 任一修复都会使旧 verdict 失效，必须重新验证并启动新的 Sol reviewer。
