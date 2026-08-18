# 定期收件箱模式

只在用户明确要求周期性扫描目录并给出执行频率后创建 scheduled task。

建议目录：

```text
<project>/xhs-paper-inbox/
<project>/xhs-paper-outbox/
<project>/xhs-paper-archive/
```

建议任务提示词：

```text
使用 $xhs-paper-publisher 检查项目中的 xhs-paper-inbox。只处理没有对应 outbox 草稿的新 PDF；每篇生成 5 张论文速读卡片、selection.md、post.md、publish_package.json 和 publish_state.json，进行视觉与事实核对，并运行发布包预检。不要打开浏览器、上传或发布到小红书。完成后列出新草稿、预检结果、证据不足项和需要用户确认的发布时间。如果没有新论文，简短报告无新增文件，不修改旧草稿。
```

运行策略：

- 先在普通任务中用一篇真实论文验证，再启用周期任务。
- 本地任务运行时电脑需开机、桌面应用需运行且项目目录可访问。
- 非 Git 项目直接在项目目录运行；Git 项目若不希望草稿干扰当前分支，可使用独立 worktree。
- 不在周期任务里保存密码、验证码或绕过平台安全检查。
