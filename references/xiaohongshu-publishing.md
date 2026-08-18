# 小红书图文发布契约

本契约借鉴经过真实页面验证的视频发布工作流，但只适用于论文图文笔记。页面结构和平台限制可能变化，每次运行都要以当前页面证据为准。

## 1. 发布包

浏览器工作前必须存在 `publish_package.json`。使用 `assets/publish-package-template.json` 作为字段参考，使用 `scripts/validate_publish_package.py <package> --sync-state` 做预检。人工修改包字段后使用 `--write-fingerprint --sync-state` 刷新指纹并重置预检状态。

核心字段：

```json
{
  "schema_version": 2,
  "platform": "xiaohongshu",
  "content_type": "image",
  "media_mode": "source_pages",
  "package_fingerprint": "sha256...",
  "source": {
    "paper_pdf": "绝对路径",
    "paper_title": "论文题目",
    "selection_file": "selection.md 的绝对路径"
  },
  "media": [
    {"order": 1, "path": "01-pdf-page-001.png", "ratio": "original", "presentation": "source_page", "source_page": 1}
  ],
  "form": {
    "title": "不超过当前平台限制的标题",
    "body": "正文",
    "topics": ["论文速读", "计算机视觉"],
    "publish_mode": "draft",
    "scheduled_at": null,
    "timezone": "Asia/Shanghai",
    "visibility": "public",
    "collection": {"enabled": true, "name": "论文分享"},
    "originality": {
      "enabled": false,
      "requested_default": true,
      "rights_confirmed": false,
      "basis": "paper commentary with cited figures"
    }
  },
  "safety": {"final_submit_authorized": false}
}
```

规则：

- 把话题存成不带 `#` 的名称数组，去空、去重并保留可读形式。
- 标题预检按参考实现的 20 个 Unicode 码点上限执行；实际发布时再次读取平台计数器。若当前平台限制不同，以更严格者为准并回写发布包。
- `media` 必须是连续排序的 4-5 张图片，路径存在且没有重复。`cards` 模式必须 3:4；`source_pages` 模式保持 PDF 原页比例并带有原始页码。
- `scheduled_at` 使用带时区的 ISO 8601。`publish_mode=scheduled` 时必须是未来时间。
- 不在发布包中持久化最终发布授权；`final_submit_authorized` 必须保持 `false`。动作时确认只存在于当前对话。
- 默认 `collection={"enabled":true,"name":"论文分享"}`；用户明确指定其他合集时替换。
- 原创声明默认计划开启，但权利确认前保持 `enabled=false`。只有用户明确确认当前素材和内容满足平台原创要求，才能把 `enabled` 与 `rights_confirmed` 同时设为 `true` 并刷新指纹；偏好“默认打开”不能替代具体权利确认。

## 2. 双确认状态机

使用以下阶段，不把“尝试过”当作成功：

```text
prepare -> preview -> [用户“确认”] -> adapt/preflight -> inspect -> upload -> mutate -> verify
                                                                                   |-> draft_saved
                                                                                   `-> [用户“提交”] -> submit
```

- `prepare`：生成卡片、正文、证据表和发布包。
- `preview`：向用户展示当前版本的图片顺序、标题、完整正文、标签、原创声明和模式；未确认时状态为 `AWAITING_CONTENT_CONFIRMATION`。
- `adapt/preflight`：用户确认后执行平台格式适配并校验文件、比例、数量、标题、话题、发布时间和原创声明依据；可见内容发生变化时回到 `preview`。
- `inspect`：只读检查登录态、页面类型、现有草稿身份和阻塞弹窗。
- `upload`：只上传目标图片；已有同一发布包的完整素材时不重复上传。
- `mutate`：采用 dependency-aware bounded batching（依赖感知的有界批处理）修复标题、正文、话题、合集、可见性、原创声明和定时设置。
- `verify`：重新读取所有表单与素材状态，不依赖之前动作的返回值；草稿任务必须回读草稿已保存证据。
- `submit`：上传完成后重新展示最终摘要，只有用户在该状态下明确回复“提交”才点击发布或定时发布，再验证结果页。

内容确认和最终提交确认是两次独立授权。第一次“确认”只授权适配、上传、填写和保存草稿；不能把它延用为公开发布授权。用户尚未确认当前预览版本时，禁止进入 `upload`、`mutate`、`verify` 或 `submit`。

每次运行通过 `scripts/record_publish_state.py` 把阶段、时间和页面证据写入 `publish_state.json`。包指纹变化时必须视为新版本，不能沿用旧版本的 `ready` 或提交结果。

## 3. 页面检查门禁

进入 `READY_TO_SUBMIT` 前必须全部满足：

```text
contentConfirmed      用户已确认当前版本的图片、标题、正文和标签
authenticated       已登录且没有验证码/安全验证
contentType          位于“上传图文”流程
draftIdentity        当前编辑器为空或与本发布包一致
media                4-5 张目标图片完整、顺序正确、无上传进度或失败提示
title                页面值与发布包完全一致
body                 规范化换行后的正文与发布包一致
topics               每个话题是真实提交的候选实体，没有纯文本残留或重复
collection           已选择发布包指定合集，页面回读名称完全一致
originality          保持关闭，或已具备当前内容的明确权利确认
schedule             草稿/立即/定时时间与发布包一致
noBlockingDialog     没有未处理弹窗
finalButton          最终按钮可见且可用
safety               最终按钮尚未点击
```

## 4. 表单操作

1. 只有 `contentConfirmed=true` 后才打开 `https://creator.xiaohongshu.com/publish/publish?from=menu&target=image`。
2. 先检查页面，再执行任何写入。优先使用可访问名称、占位文本和当前 DOM；历史选择器只能作为限定范围内的回退。
3. 上传前运行 `python scripts/stage_upload_media.py <publish_package.json>`。只使用脚本返回的短英文绝对路径；它们必须与发布包媒体逐文件 SHA-256 一致。这个暂存只解决浏览器文件桥接问题，不得重新编码、缩放、裁剪或改变论文原页。
4. 文件选择必须先创建 `filechooser` 等待，再立即点击当前页面可见的“上传图片”按钮；点击 promise 与 chooser 等待并发推进，不能先等待点击返回后才获取 chooser。确认 `chooser.isMultiple()` 后一次传入全部有序文件。隐藏的 `Choose File`/`input[type=file]` 只能作为页面证据支持的回退，不能在可见按钮成功路径之后重复注入。
5. `setFiles` 成功只是动作回执。重新读取页面，等待缩略图数量稳定为目标数量（例如 `5/18`），并确认不再显示上传中、处理中、失败或重试提示，才把 `upload` 标记成功。
6. 标题字段用包含“填写标题”的占位文本定位；写入后重新读取完整 `value`。不能依赖“第一个文本框”。
7. 正文使用当前页面唯一可见的 `div[contenteditable="true"]` 或等价语义编辑器；不要直接注入内部 HTML，也不能依赖 `getByRole("textbox").nth(...)` 等动态序号。一次初始检查后，可把标题、正文、合集、可见性、原创声明和定时设置等互不依赖的字段合并执行；每批最多 2-3 个写动作且预计不超过 60 秒。常规点击和输入使用 3-5 秒短超时，不等待无关的整页网络稳定；批尾只等待与本批目标直接相关的控件状态。无需每写一个字段就做整页验证，全部写入后统一回读。
8. 添加话题时，逐个使用平台原生“话题”入口，并在每次选择前重新获取候选或唯一正文编辑器，因为下一组候选依赖上一项。选择名称完全匹配的候选项后可直接继续下一话题，不做整页快照；不能把正文中的 `#话题` 纯文本当作已选择话题，所有话题在最终 `verify` 中一次性核验为真实实体。
9. 如果候选面板为空或半成品话题残留，清空本轮话题实体并进行有限次数的整组重建；最多 3 轮，随后返回阻塞状态。
10. 打开“加入合集”，选择与 `form.collection.name` 完全匹配的合集，默认 `论文分享`；重新读取已选名称。没有匹配项时返回 `COLLECTION_NOT_FOUND`，不要创建新合集或选择近似项。
11. 只有 `form.originality.enabled=true` 且 `rights_confirmed=true` 时才打开原创声明，并重新读取开关状态；否则保持关闭并返回 `ORIGINALITY_RIGHTS_REQUIRED`，不能绕过声明条件。
12. 定时发布时设置日期时间后重新读取控件显示值，必须与 `scheduled_at` 在指定时区下相同。
13. 若页面出现验证码、风险控制或用户接管，立即停止自动操作并保留状态。
14. 任一批次中断、超时或候选变化后先做一次只读检查，只补齐页面中缺失的字段；禁止重传已验证图片或重写已正确字段。批处理只减少中间快照，不能减少最终 `verify` 的门禁项目。
15. 同一批动作应在一次浏览器控制调用中连续执行；不要在常规点击、输入之间插入固定等待、整页快照或全页加载等待。只有话题候选出现、上传完成、控件已选或草稿已保存这类直接后置条件可以作为批尾等待，达到条件立即继续。动态话题以“打开入口、输入、选择精确候选”三个动作为一批，单次浏览器控制调用只处理一个动态话题；下一话题另起短调用，不把多个依赖候选批次塞进一次长调用。
16. 实测当前页面可见动作常先于高层动作回执完成。常规可恢复输入优先使用 Browser 的 DOM-CUA 直接通道；用一次可见 DOM 读取取得唯一节点后，连续执行本批直接输入/点击，减少高层 Playwright 回执等待。不能通过丢弃或不等待动作 promise 来推进依赖步骤：上一话题没有回读为真实实体时，下一话题不得开始，否则会把两个查询串成纯文本残留。该优化不用于 `setFiles`、删除、最终发布/定时发布或任何不可逆动作。
17. 采用参考发布器的“一个调度器、一个 UI 串行队列、一次最终独立验收”框架：本 Skill 的单平台运行先由一次 `inspect` 生成缺项计划，再由一个维护过的 mutation runner 连续修复，不在每个字段之间重新进入高层 Agent 循环。常规话题动作优先调用 `scripts/xhs_browser_batch.mjs`；每个动态话题独立成批，并在候选提交屏障后才开始下一个，最后由独立 `verify` 统一裁决成功。视频平台、Ego Lite、并行多平台上传等细节不迁移到本图文流程。
18. 当前页面的“暂存离开/发布”可能封装在 `xhs-publish-btn` 特殊控件中，语义 DOM 不暴露内部按钮。草稿模式只依据当前截图和控件矩形点击左侧“暂存离开”区域，绝不点击右侧红色“发布”；点击回执或 URL 未变化都不能证明保存失败或成功。随后返回上传页打开 `草稿箱(n)`，切到 `图文笔记(n)`，以目标标题完全匹配且出现保存时间作为 `draftSaved=true` 的权威证据。无法取得该证据时返回 `DRAFT_SAVE_UNVERIFIED`。

### 幂等 `ensure` 契约

每一个上传或表单动作都实现为“确保目标状态”，而不是“点击某个控件”：

1. 先读取当前页面真相；目标已经满足时返回 no-op，不重复上传或点击。
2. 只在正确页面区域内按可访问名称、角色、可见文字或稳定语义定位唯一控件；不保存固定坐标、随机类名或个人账号数据。
3. 使用有限等待和有限重试；不能使用无界循环或为了掩盖隐藏页面而不断延长盲等。
4. 动作完成后独立重新检查页面。文件选择、点击成功或候选面板打开都只是动作回执，不是成功后置条件。
5. 无法证明目标状态时返回稳定阻塞代码和证据；下一次运行先 `inspect`，能够安全地继续或保持 no-op。

同一任务只能有一个浏览器控制者。不得让多个 Agent、多个浏览器工具或重复任务同时控制同一小红书草稿；检测到用户接管时立即停止所有自动写入。

## 5. 草稿身份与恢复

- 只有页面为空，或标题、图片数量/顺序和包指纹证据共同指向当前发布包时才可复用编辑器。
- 当前页面存在其他笔记草稿时返回 `FOREIGN_DRAFT`；不要覆盖、清空或删除它。
- 上传中断后，若同一目标图片仍在上传，只等待完成，不重复注入文件。
- 浏览器重启或标签页丢失后，重新执行 `inspect`；旧状态只能提供线索，不能代替当前页面验证。
- 已完成 `mutate` 但未通过 `verify` 的任务继续修复缺失门禁，不重做已验证的上传。
- 小红书图文草稿存储在当前浏览器本地；草稿箱计数、`图文笔记(n)`、精确标题和保存时间必须在同一浏览器中核验。不能用“编辑于刚刚”、按钮点击回执或无导航来代替草稿箱证据。
- `record_publish_state.py` 每次成功写入前把上一份有效状态保存为 `publish_state.backup.json`。主状态损坏时，仅恢复 `package_fingerprint` 与当前发布包一致的备份，把损坏主文件保留为 `publish_state.corrupt-<timestamp>.json`，清除旧的页面门禁并返回 `STATE_RECOVERED_REQUIRES_INSPECT`；恢复本身不能产生 `READY_TO_SUBMIT` 或 `DRAFT_SAVED`。
- 备份缺失、无效或属于另一发布包时失败关闭，返回 `STATE_CORRUPT_NO_VALID_BACKUP`，不得进入浏览器写入。

## 6. 阻塞代码

稳定使用以下代码并在 `publish_state.json` 中记录证据：

```text
CONTENT_CONFIRMATION_REQUIRED  当前版本尚未获得上传前内容确认
AUTH_REQUIRED          需要登录、验证码或安全验证
USER_CONTROL           用户正在控制浏览器
FOREIGN_DRAFT          当前编辑器属于其他笔记
FILE_MISSING           素材路径不存在
ASSET_INVALID          图片格式、比例、数量或顺序不合格
UPLOAD_NOT_STARTED     文件选择后没有出现上传信号
UPLOAD_STALLED         上传/处理没有在窗口内完成
TOPIC_NOT_COMMITTED    话题候选没有成为真实实体
COLLECTION_NOT_FOUND   发布包指定的合集不存在或无法验证
ORIGINALITY_RIGHTS_REQUIRED  计划开启原创声明但缺少当前素材与文案的明确权利确认
FORM_MISMATCH          表单回读与发布包不一致
SCHEDULE_INVALID       时间无时区、已过期或页面不接受
RISK_CONTROL           平台风控或验证码
SELECTOR_DRIFT         当前页面结构与已知表单不一致
PLATFORM_RULE_CHANGED  页面明确规则与当前预检规则不一致
INPUT_CHANNEL_BROKEN   浏览器控制通道中断
STATE_RECOVERED_REQUIRES_INSPECT  已从匹配备份恢复，必须重新检查真实页面
STATE_CORRUPT_NO_VALID_BACKUP     状态损坏且没有当前包可用备份
ACTION_FAILED          其他已验证失败
DRAFT_SAVE_UNVERIFIED  已请求暂存，但草稿箱没有目标标题与保存时间证据
```

出现 `PLATFORM_RULE_CHANGED` 时先停止写入，按 `continuous-improvement.md` 保存平台提示和当前字段证据；修复验证器/生成器并重做预检后才能恢复浏览器流程。

## 7. 最终提交

`verify` 成功后向用户展示：账号、图片文件顺序、标题、正文、话题、原创声明状态、发布模式和准确时间。此处必须等待新的“提交”指令；较早的内容“确认”不能复用。取得动作时确认后才进入 `submit`。

点击最终按钮后必须寻找明确成功证据，例如成功提示、笔记管理中的新条目或定时列表中的目标时间。没有成功证据时状态为 `SUBMIT_UNVERIFIED`，不能报告“已发布”。
