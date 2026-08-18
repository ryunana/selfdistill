# import_chats.py 导入器安全审查报告（最终对抗复审）

- 被审提交：`f3dcacc`（分支 `codex/pr5-hardening-design`）
- 审查方式：独立只读复审，运行时复现 33 项攻击用例 + 静态扫尾，全程未改仓库文件（哈希前后一致、工作树干净）

## 结论

**VERDICT: ship** —— 无剩余阻断项、无 important，仅 3 个 polish。

两个历史阻断点均经独立复现确认已真正修复：
- **TOCTOU / 最后一刻路径替换**：所有写入/chmod/mkdir 收口到「从 / 逐组件 `O_NOFOLLOW|O_DIRECTORY` 打开并持有的目录 fd」原语；临时文件 `O_EXCL`+随机名+`O_NOFOLLOW`；`os.replace` 双边 dir_fd；既有文件必经 `st_nlink==1` + `S_ISREG` 双重检查。7 类攻击复现全部拒绝且外部文件内容/权限未动。
- **message_ids 与正文绑定**：Markdown 正文为唯一事实源，`_validate_state_output_binding` 每次 load/save 用 `_managed_message_ids` 从正文标题正则重新提取并覆写 `entry["message_ids"]`，状态文件里的 ids 从不被信任。伪造 path/lineage/message_ids/正文注入标题 均被拒绝或自愈。

遗留「待复核」三项均可接受：Gemini 未绑定页面块告警+exit 2、空本地会话如实报「无消息」+exit 1、疑似系统包装保留正文+提醒。

## 发现（仅 polish，已修复）

1. `import_chats.py:1632` —— base 键的 branch_lineage 无绑定对象，伪造可被接受（影响≈0，会自愈）。已改为：base 键 lineage 仅作佐证，不参与身份消歧，哈希绑定的 branch 键优先。
2. `import_chats.py:74` —— `fmt_time` 接受 bool（`isinstance(True,(int,float))` 为真），畸形 `create_time:true` 会渲染 1970 年。已加 `not isinstance(value, bool)`。
3. `import_chats.py:2459` —— `--root ""` 静默回退默认 INPUT_DIR（空串 falsy）。已改为显式拒绝空串。

## 修复与验证

修复提交 `10a5675`，配 4 项回归测试。验证全绿：`python3 -m unittest discover -s tests`（191 项 OK）、`py_compile`、隐私扫描（未发现本人信息/绝对路径/密钥）、`git diff --check`。
