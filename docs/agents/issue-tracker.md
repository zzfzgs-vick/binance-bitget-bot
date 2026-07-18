# Issue tracker：Local Markdown

本仓库的 Issue 和 PRD 使用 `.scratch/` 下的 Markdown 文件管理。

## 约定

- 每项功能使用一个目录：`.scratch/<feature-slug>/`
- PRD 路径：`.scratch/<feature-slug>/PRD.md`
- 实现 Issue 路径：`.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号
- Issue 顶部附近使用 `Status:` 行记录 triage 状态；状态词汇参见 `triage-labels.md`
- 评论和对话历史追加在文件底部的 `## Comments` 标题下

## 当技能要求“发布到 issue tracker”时

在 `.scratch/<feature-slug>/` 下创建文件；目录不存在时一并创建。

## 当技能要求“获取相关 ticket”时

读取用户指定路径或编号所对应的文件。
