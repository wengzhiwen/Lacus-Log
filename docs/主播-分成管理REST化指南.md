# 主播-分成管理REST接口

本模块已提供分成管理的 REST 接口，页面保持原有布局与样式，仅替换数据来源为 API。变更记录相关接口暂不作为对外承诺（后续再启用）。

## 已有模型

- **数据模型**：`PilotCommission` / `PilotCommissionChangeLog` 已经定义，并在视图中使用。
- **页面流程**：
  - 列表页展示当前有效分成、历史调整记录；
  - 新建/编辑通过表单提交，WTForms/Flask 负责 CSRF；
  - 软删除/恢复使用 POST 表单请求完成；
  - 变更记录通过 `/commission/<id>/changes` 返回 HTML。
- **辅助函数**：`_get_pilot_current_commission_rate()`、`_calculate_commission_distribution()` 等可在未来拆分为服务层。

## 已实现的 REST 接口

- 读取
  - GET `/api/pilots/<pilot_id>/commission/current`
    - 返回字段：`current_rate`、`effective_date`、`remark`、`calculation_info`（`pilot_income`、`company_income`、`calculation_formula`）。
  - GET `/api/pilots/<pilot_id>/commission/records`
    - 查询参数：`page`、`page_size`，默认 `page=1&page_size=20`，上限 `page_size<=100`。
    - 返回：`data.items=[{id, adjustment_date, commission_rate, remark, is_active, created_at, updated_at}]`，`meta={page,page_size,total}`。

- 写入（需 `X-CSRFToken` 且 `@roles_accepted('gicho','kancho')`）
  - POST `/api/pilots/<pilot_id>/commission/records`
    - 请求体：`{adjustment_date:'YYYY-MM-DD', commission_rate: float, remark?: string}`。
  - PUT `/api/pilots/<pilot_id>/commission/records/<record_id>`
    - 请求体：可包含 `adjustment_date`、`commission_rate`、`remark` 任意组合。
  - POST `/api/pilots/<pilot_id>/commission/records/<record_id>/deactivate`（软删除）
  - POST `/api/pilots/<pilot_id>/commission/records/<record_id>/activate`（恢复）

统一响应：`success/data/error/meta`；错误码：`VALIDATION_ERROR/CSRF_ERROR/PILOT_NOT_FOUND/RECORD_NOT_FOUND/INTERNAL_ERROR`。

## 维护提示

- 页面仍保留原有模板路由，但数据改为通过上述 API 读取/写入。
- 写操作统一从请求头 `X-CSRFToken` 校验；失败返回 `CSRF_ERROR`。
- 权限沿用主播管理：`@roles_accepted('gicho','kancho')`。

## 前端对接说明（不改布局/样式）

1) 主播详情页中的分成信息，已由 `GET /api/pilots/<pilot_id>` 聚合返回；无需额外调用。
2) 分成管理页的“当前分成/记录列表”已对接：
   - 当前分成：`GET /api/pilots/<pilot_id>/commission/current`
   - 记录列表：`GET /api/pilots/<pilot_id>/commission/records?page=1&page_size=50`
3) 新增/编辑/停用/恢复：前端后续可在不改UI的前提下调用相应写接口实现交互。

1. **抽象服务层**：将 `_get_pilot_current_commission_rate`、`_record_commission_changes`、软删除等逻辑迁移到独立服务，方便 REST 端点调用。
2. **统一响应结构**：复用用户、主播管理的 `create_success_response` / `create_error_response`，保持一致的 `success/data/error/meta` 结构。
3. **权限策略**：当前视图要求运营与管理员均可访问，REST 化时可沿用 `@roles_accepted('gicho', 'kancho')`。
4. **渐进迁移**：可先提供只读接口（当前分成、历史记录），确认前端逻辑稳定后再替换创建/编辑流程。

> 说明：变更记录的 JSON 接口已具备雏形，但当前不对前端暴露/对接；页面内“变更记录”弹窗暂维持占位或隐藏处理。
