# selfdistill 持续蒸馏 MVP 设计

日期：2026-08-16  
状态：架构方向已批准，待用户复核书面设计  
基线：GitHub `main` 提交 `8979cd7`

## 1. 结论

在现有 selfdistill 本地工具包上增加一层独立的“持续蒸馏审计”，让使用者可以把后续对话修正积累到本地 inbox，并从 canonical + inbox 生成完整证据包、六维覆盖报告和待确认的新发现。

本次不改造现有 `build.py` 与 `install.py`。审计负责“蒸馏得准不准”，构建与安装继续负责“生成和写回”。两条链路保持独立。

## 2. 用户价值

当前公开版主要适合第一次建立 L1–L4。升级后，使用者还能持续完成以下闭环：

1. 在本地记录 AI 理解错误、表达偏差、事实更正和边界补充；
2. 全量整理 canonical 与 inbox，而不是靠关键词抽样；
3. 查看哪些方面已有证据、哪些仍是缺口；
4. 让当前 AI 从完整证据中发现新规律、冲突和时间变化；
5. 人工确认后才更新 canonical；
6. 继续使用现有命令构建 HTML，并选择是否写回 Codex 或 Hermes。

## 3. MVP 边界

### 本次要做

- 本地 inbox 候选契约；
- canonical + inbox 全量文件清单与哈希；
- 稳定的 evidence ID 和完整证据包；
- 六维覆盖报告；
- 重新蒸馏 prompt；
- 报告引用、来源漂移和候选格式校验；
- 最小自动测试与 README 使用说明；
- 防止 inbox、reports 和原始聊天被误提交的 Git 忽略及发布检查。

### 本次不做

- 数据库、Web UI、后台服务、常驻进程或自动调度；
- 多用户、账号、权限系统或云同步；
- 模型 API、模型选择器或自动调用第三方模型；
- 自动读取 ChatGPT、Hermes、Codex 或 Obsidian 历史；
- 自动修改 canonical；
- 把私有版的 staging、manifest、备份、原子写回和回滚系统移植到公开版；
- 批量迁移历史私有数据；
- Roundtable 或其他相邻项目能力。

所有数据和生成报告默认只留在使用者本机。语义重新蒸馏仍由使用者当前选择的 AI 完成，项目本身不发送数据。

## 4. 架构与职责

```text
canonical/**/*.md + inbox/*.json
              |
              v
       distill_audit.py audit
              |
              v
reports/latest/{inventory,evidence,coverage}
              |
              v
     prompts/rediscovery.md + 当前 AI
              |
              v
discoveries.md + reports/latest/candidates/*.json
              |
              v
       用户逐条确认或拒绝
              |
              v
  人工更新 canonical -> build.py -> install.py（可选）
```

各组件只承担一个职责：

- `distill_audit.py`：机械读取、编号、汇总和校验，不做语义判断；
- `prompts/rediscovery.md`：约束 AI 如何基于完整证据发现规律；
- `schemas/inbox-v2.json`：定义候选字段；
- `build.py`：保持现状，只生成 HTML 与 Codex/Hermes 文件；
- `install.py`：保持现状，只展示差异并在确认后写回。

## 5. 输入合同

### canonical

递归读取 `canonical/**/*.md`。每个 Markdown 标题区块形成一条证据，保留来源文件和行号。

### inbox

公开版新增 `inbox/README.md`，真实候选使用一个 JSON 文件记录一条。核心字段为：

- 来源类型、来源说明和用户原话；
- 反馈类型；
- 目标层级与章节；
- 适用范围和敏感性；
- 当时场景、错误行为、正确行为和建议动作；
- 冲突、证据引用和审批状态。

直接从对话记录的新候选允许暂时没有 `evidence_ids`，因为该候选本身会在下一次 audit 中获得 evidence ID。AI 基于已有证据生成的 rediscovery 候选必须引用至少一个真实 evidence ID。

状态只允许 `pending`、`accepted`、`rejected`、`unknown`。新候选默认 `pending`；`accepted` 只表示用户接受，不代表已经写入 canonical。

## 6. 输出合同

运行：

```bash
python3 distill_audit.py audit
```

只在 `reports/latest/` 生成：

- `inventory.json`：输入文件、SHA-256、大小和解析状态；
- `evidence.jsonl`：机器可读证据；
- `evidence.md`：供当前 AI 和用户完整阅读；
- `coverage.md`：六维覆盖与缺口。

六个维度沿用私有版已经验证的口径：作品与实际输出、明确修正、表达方式、决策取舍、外部评价与反证、时间变化与过期规则。覆盖只表示“存在可分析证据”，不冒充语义质量评分。

AI 可在同一目录生成 `discoveries.md` 和 `candidates/*.json`。每条发现必须引用 evidence ID；相似发现合并，最多保留 8 条高价值结果。

## 7. 校验与失败处理

运行：

```bash
python3 distill_audit.py verify reports/latest
```

以下情况直接失败，不输出模糊的“已完成”：

- canonical 或 inbox 文件读取失败；
- JSON 候选缺少必要字段或使用非法枚举；
- 两条证据 ID 冲突；
- audit 后来源文件集合或哈希发生变化；
- discoveries 或 rediscovery candidates 引用了不存在的 evidence ID；
- 报告目录是符号链接或输出试图离开 `reports/`。

报告使用临时目录生成后整体替换，避免留下半套结果；报告目录和文件使用仅当前用户可读写的权限。任何失败都不得修改 canonical、input、build 产物或 AI 工具目录。

## 8. 隐私与公开仓库边界

- `input/`、真实 `inbox/*.json`、`reports/` 和 `dist/` 默认不提交；
- 仓库只保留 inbox 说明、schema 和虚构测试样本；
- 发布检查除扫描常见密钥和绝对路径外，还要检查受保护目录是否出现被 Git 跟踪的真实数据文件；
- 检查只报告文件路径，不打印候选、证据包或报告中的敏感正文；
- README 明确说明：数据留在本机，但使用者把 evidence 交给云端 AI 时仍受该模型供应商的数据政策约束；
- 不复制私有仓库中的真实 canonical、inbox、reports、backups、manifest 或运行时文件。

## 9. 向后兼容

- 原有 `python3 build.py`、HTML Demo 和 `install.py --target ...` 行为不变；
- 没有 inbox 候选时也能运行 audit，并明确显示候选为 0；
- 不要求现有使用者迁移 canonical；
- 新能力作为“持续更新”章节加入 README，不改变第一次使用的最短路径；
- 仅使用 Python 标准库，保持 Python 3.9+。

## 10. 最小文件范围

预计新增：

- `distill_audit.py`
- `schemas/inbox-v2.json`
- `inbox/README.md`
- `prompts/rediscovery.md`
- `tests/test_distill_audit.py`
- `tests/fixtures/` 中的虚构最小样本

预计修改：

- `.gitignore`
- `README.md`
- `scripts/scan_before_release.py`

不修改 `build.py`、`install.py`、公开 canonical 示例和 HTML 模板。

## 11. MVP 验收

必须同时满足：

1. `python3 -m unittest discover -s tests -v` 全部通过；
2. 对仓库虚构样例运行 audit 成功；
3. `python3 distill_audit.py verify reports/latest` 通过；
4. 修改任一来源后 verify 能检测到漂移；
5. 未知 evidence 引用会失败；
6. audit 前后 canonical 和 inbox 输入哈希不变；
7. `python3 build.py` 仍成功；
8. `python3 scripts/scan_before_release.py` 通过；
9. `git diff --check` 通过；
10. Git 跟踪文件中没有真实 input、inbox 候选或 reports 内容。

只要以上闭环成立，MVP 即完成；不为未来可能出现的自动化、云端或多用户需求预建架构。
