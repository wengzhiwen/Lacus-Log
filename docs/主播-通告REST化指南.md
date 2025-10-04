# 主播-通告REST接口现状

当前代码中的通告管理主要依赖 `routes/announcement.py` 的服务端模板；REST 接口仅覆盖少量下拉选项和联动查询。此前编写的“REST 化指南”与现状差异较大，现更新如下，供维护与后续改造参考。

## 现有接口

| 功能 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 查询基地下场地 | GET | `/announcements/api/areas/<x_coord>` | 返回指定基地下的场地列表（JSON）。|
| 查询场地下坐席 | GET | `/announcements/api/areas/<x_coord>/<y_coord>` | 返回坐席列表，用于三联动。|
| 按直属运营筛选主播 | GET | `/announcements/api/pilots/by-owner/<owner_id>` | 返回该运营名下可选主播列表。|
| 获取筛选器选项 | GET | `/announcements/api/pilot-filters` | 输出运营、分类等筛选器数据（JSON）。|
| 模糊检索主播 | GET | `/announcements/api/pilots-filtered` | 根据运营/分类/关键字返回可选主播。|

除此之外，新增、编辑、删除、循环处理、冲突检查等核心流程仍依赖 HTML 表单及后端同步渲染，并没有 `POST /api/announcements` 等 REST 端点。

## 与预期 REST 化功能的差距

| 能力 | 现状 | 缺口 |
| --- | --- | --- |
| 列表/分页 API | 无 | 列表页使用服务端渲染，未向前端暴露 JSON 列表接口。|
| 详情 / 变更记录 API | 无 | 模板直接读取数据库，缺少 `GET /api/announcements/<id>` / `/changes`。|
| 创建 / 编辑 / 冲突检查 | 表单 + 同步校验 | 冲突校验在视图内部处理，没有独立的 REST 接口；创建/编辑 API 尚未编写。|
| 批量操作 / 清理 | 表单提交 | 缺少 `DELETE` / `POST cleanup` 等 JSON 接口。|

## 维护建议

1. **继续沿用现有表单流程**：在未引入新接口前，任何前端改动都应配合模板逻辑，避免破坏当前功能。
2. **谨慎使用现有 JSON 辅助接口**：上述 `/api/areas/...` 等接口仅服务于下拉联动，参数校验有限，若扩展使用场景需加强校验与权限控制。
3. **如需 REST 化**：建议先抽离冲突检查、循环生成等逻辑至服务层，再逐步对外暴露 `GET/POST/PATCH/DELETE` 端点，复用统一的 JSON 响应结构和 CSRF 校验方式。
4. **文档同步**：未来每落地一个新的 REST 端点，请及时更新本文件，避免旧信息误导开发者。

> 总结：目前通告模块只提供少量辅助 JSON 接口，尚未完成真正意义的 REST 化。开发者应以 `routes/announcement.py` 的表单逻辑为准。

## 未来 REST 化建议

- **接口收敛**：根据《主播-通告》需求，若改造为 REST，应将创建/编辑/启停等操作归并为 `PATCH /api/announcements/<id>`，由请求体的字段驱动状态流转。特殊操作（如循环设置）可使用名词化子资源，例如 `PUT /api/announcements/<id>/schedule`，避免出现 `/edit`、`/activate` 等动词路径。
- **视图/导出**：现有 `/api/areas/...`、`/api/pilots-filtered`、`/export`、`/grouped` 趋向动作式命名。REST 化后建议改为 `GET /api/announcements?view=grouped`、`?format=csv` 或在统一响应的 `meta` 中附带聚合数据，减少端点扩散。
