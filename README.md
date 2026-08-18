<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="Paper Publisher：文章自动上传的自动化工具，一键后台自动发布图文作品">
</p>

<p align="center">
  小红书<br>
  <strong>并行上传，逐项验收，默认不发布</strong>
</p>

XHS Paper Publisher 是一个面向 Codex / Claude Code 的论文发布 Skill。给它一篇本地 PDF 论文，它会自动解析论文内容，筛选适合展示的论文原始页面，生成小红书标题、正文与标签，并通过 Ego Lite 操作真实的小红书创作者页面，完成图片上传、内容填写、原创声明、合集选择和发布前检查，最后停留在可人工复核的状态，确认后即可发布。

> [!IMPORTANT]
> 默认流程不会点击最终发布按钮。只有用户在当前任务中明确授权，才允许真正发布；这项权限不会写进配置，也不会被下次任务继承。

## 已经验证到什么程度

截至 2026-08-18，项目完成初步测试，发布成功，后续优化运行速度：

## 它会完成什么

| 平台 | 发布前准备 |
| --- | --- |
| 小红书 | 论文 PDF 解析、论文原页筛选、标题、正文、真实话题实体、原创声明、合集选择、可选 3:4 封面、发布前检查 |

以下后续测试中：
| 抖音 | 论文 PDF 解析、论文原页筛选、标题、正文、真实话题实体、原创声明、合集选择、可选 3:4 封面、发布前检查 |
| 微信公众号 | 论文 PDF 解析、论文原页筛选、标题、正文、真实话题实体、原创声明、合集选择、可选 3:4 封面、发布前检查 |

它不会制作或编辑封面；如果你已经有封面文件，可以选择让 Skill 上传。


## 快速开始

### 1. 准备环境

- [Ego Lite](https://lite.ego.app/) 与可用的 `ego-browser` 命令
- Node.js 18 或更高版本
- 已在 Ego Lite 中登录需要使用的创作者平台

### 2. 安装 Skill

Codex：

```bash
git clone https://github.com/HongYiChen86/Paper-publisher.git
mkdir -p ~/.codex/skills/xhs-paper-publisher
cp -R Paper-publisher/xhs-paper-publisher/. ~/.codex/skills/xhs-paper-publisher/
```

Claude Code：

```bash
mkdir -p ~/.claude/skills/xhs-paper-publisher
cp -R Paper-publisher/xhs-paper-publisher/. ~/.claude/skills/xhs-paper-publisher/
```

### 3. 在对话中使用

```text
使用 $xhs-paper-publisher，把 /path/to/paper.pdf 准备到小红书，选择 4-5 张论文原始页面，生成标题、正文和话题，并停在发布前等待确认。
```

第一次使用会自动进入 onboarding。它会先确认小红书创作者页面是否可用，以及 Ego Lite 中是否已经存在有效登录状态。

之后会配置论文图片数量、标题与正文风格、话题偏好、默认合集、原创声明策略和是否生成可选 3:4 封面。

个人配置保存在：

~/.config/xhs-paper-publisher/config.json

个人配置不会写入 Skill 目录。

之后通常只需要提供论文 PDF 路径。当前任务中的明确要求会覆盖个人默认配置。


## 安全边界

- 页面会挂载最终发布按钮硬保护；保护未成功启用时不能返回 `READY`。
- 原创 / 自制声明只会在用户已保存真实的长期原创策略，或本次明确确认权利时启用。
- 每次运行都会核对本地视频和封面的精确路径，避免把相似文件传错。
- Ego Lite 输入通道中断后，调度器会停止后续页面修改，只保留只读检查和可恢复状态。
- 检测到用户接管浏览器时，所有自动化操作会立即停止。

## 已知边界

- 这是基于真实网页的浏览器自动化，依赖平台登录状态，也可能受到平台改版、风控或服务波动影响。
- Skill 当前只负责准备和验证草稿，不负责剪辑、转码或制作封面。
  
## 自定义自己的发布流程

如果你希望增加自己的步骤，例如“抖音填写标签后点击某个设置按钮”，直接把平台、触发时机、按钮文字或附近区域，以及成功后的页面状态告诉 Agent。

项目内的[自定义发布流程扩展规范](video-publisher/references/customizing-workflows.md)会指导 Agent 将这一步实现成可重复运行的 `inspect → action → verify` 流程，并通过真实页面测试，而不是把一次性的坐标点击写死。


进一步了解实现与真实测试边界：

- [Skill 主流程](xhs-paper-publisher/SKILL.md)
- [小红书发布流程](xhs-paper-publisher/references/xiaohongshu-publishing.md)
- [内容生成规范](xhs-paper-publisher/references/content-spec.md)
- [自动化 Prompt 说明](xhs-paper-publisher/references/automation-prompt.md)
- [持续改进机制](xhs-paper-publisher/references/continuous-improvement.md)
- [已学习规则](xhs-paper-publisher/references/learned-rules.json)

## License

