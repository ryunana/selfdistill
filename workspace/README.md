# 本地工作区

这里保存使用者自己的 selfdistill 数据，与公开仓库中的虚构 Demo 分开：

- `workspace/canonical/`：经使用者确认后的 L1–L4 正式档案；
- `workspace/input/`：导入并整理后的聊天记录；
- `workspace/inbox/`：尚待审阅的持续更新候选。
- `workspace/reports/`：审计生成的本地证据包与覆盖报告。

真实内容默认被 Git 忽略。只有说明文件和 `.gitkeep` 占位符可以提交；不要用 `git add -f` 强制加入个人资料。

首次建立档案时，参考 `templates/profile/` 的空白结构；只想查看项目效果时，`build.py` 会在本地工作区为空时使用 `examples/demo-profile/canonical/` 的虚构数据。
