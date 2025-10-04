# 主播-开播记录 REST 接口一览

开播记录模块已经完成核心 CRUD 的 REST 化改造。页面模板仍负责渲染 UI 与交互动画，但所有数据读取与提交均通过 `/battle-records/api/*` 端点完成，响应使用统一的 `success/data/error/meta` 结构。

## 核心 CRUD 接口

| 功能 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 列表查询 | GET | `/battle-records/api/battle-records` | 支持 `owner`（`all/self/<user_id>`）、`x`、`time`（`two_days/seven_days/today`）、`page`。返回 `data.items`（最新 100 条），附带筛选器选项与分页信息。|
| 详情读取 | GET | `/battle-records/api/battle-records/<record_id>` | 返回单条开播记录的详细信息、地点快照、财务数据、系统字段以及相关通告状态。|
| 创建记录 | POST | `/battle-records/api/battle-records` | 需要 `pilot`、`start_time`、`end_time`、`work_mode`、金额等字段。校验备注必填规则，成功后返回详情数据与提示消息。|
| 更新记录 | PUT | `/battle-records/api/battle-records/<record_id>` | 可更新时间、金额、备注、开播方式及坐标。对变更字段自动记录操作日志并触发詹姆斯告警判定。|
| 删除记录 | DELETE | `/battle-records/api/battle-records/<record_id>` | 删除记录及其变更日志。成功响应附带提示消息。|
| 变更记录 | GET | `/battle-records/api/battle-records/<record_id>/changes` | 返回最近 100 条字段变更，包含时间、操作者、前后值与 IP。|

> **提示**：前端页面会在请求头携带 `X-CSRFToken`，CSRF 令牌来自模板中的 `{{ csrf_token() }}`。若需要在脚本或第三方调用中访问上述接口，请确保遵循相同策略。

## 辅助数据接口

| 功能 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 获取开播地点 | GET | `/battle-records/api/battle-areas` | 返回基地 → 场地 → 坐席的三级映射，Z 坐席自动按数字优先排序。|
| 主播列表 | GET | `/battle-records/api/pilots-filtered` | 支持 `owner`、`rank`、`pilot_id` 筛选，返回包含昵称、真实姓名、分类、所属、默认开播方式的列表。|
| 主播筛选枚举 | GET | `/battle-records/api/pilot-filters` | 返回“直属运营”“主播分类”枚举，用于下拉构建。|
| 通告详情 | GET | `/battle-records/api/announcements/<announcement_id>` | 预填关联通告产生的开始/结束时间、坐标快照与运营信息，默认开播方式为线下。|
| 关联通告候选 | GET | `/battle-records/api/related-announcements?pilot_id=<id>` | 返回昨天/今天/明天的通告列表，标签格式 `YYYY-MM-DD 星期X N小时 @X-Y-Z`，排序为“今天 → 昨天 → 明天”。|

## 前端配合要点

1. **列表页**：`templates/battle_records/list.html` 使用 `fetch('/battle-records/api/battle-records?…')` 渲染卡片，并在前端保留 `allBattleRecords` 以支持昵称/真实姓名搜索。分页通过 `meta.has_more` 控制“加载更多”按钮。
2. **新建 / 编辑**：两页均改为阻止表单默认提交，使用 `fetch` + JSON 向 API 提交。提交期间按钮进入 `⏳` 状态，成功后展示提示并跳转至详情页。
3. **详情页**：删除按钮调用 `DELETE /battle-records/api/battle-records/<id>`，弹窗展示统一提示并返回列表；“变更记录”弹窗访问 `/battle-records/api/battle-records/<id>/changes`。
4. **错误处理**：当接口返回 `success:false` 时，页面统一调用 `showMessage(error.message, 'error')`；网络异常会在控制台记录，并给出用户可见的失败提示。

## 兼容性说明

- 原有的表单路由（`/battle-records/create/update/delete` 等）已经移除；历史链接若仍访问旧地址将收到 404。请确保外部脚本或自动化流程更新到新端点。
- 旧的 JSON 接口路径保持不变，但响应结构已统一为 `success/data/error`，字段命名全部更新为小写下划线风格。
- 列表筛选器仍使用 `persist_and_restore_filters` 记录最近一次选择，API 会在成功响应时写入同名 Cookie，确保页面与对话框之间的过滤条件保持一致。

> 如需扩展新的统计视图或导出能力，建议在 `battle_records_api_bp` 内新增合适的 REST 端点，并复用本指南中的统一响应结构。
