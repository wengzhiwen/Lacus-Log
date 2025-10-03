# 主播-主播管理REST接口现状

本文档梳理 `routes/pilots_api.py` 中已经提供的主播管理 REST 接口，帮助前端与服务端在维护和调试时对齐真实实现。后台模板（`routes/pilot.py`）仍存在，但列表、详情、编辑等核心交互已经迁移到 API。

## 响应约定

接口统一通过 `utils/pilot_serializers.py` 的 `create_success_response` / `create_error_response` 输出：

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": { ... }
}
```

- 成功：`success=true`，数据写入 `data`，分页等附加信息放在 `meta`。
- 失败：`success=false`，`error` 内含 `code`、`message`；HTTP 状态码配合错误类型返回（404=未找到、400=参数错误等）。
- 写操作均需在请求头携带 `X-CSRFToken`，并通过 `@roles_accepted('gicho', 'kancho')` 控制权限（创建、更新、状态调整对运营开放）。

## 已实现接口

| 功能 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 主播列表 | GET | `/api/pilots` | 支持 `owner_id`、`rank`、`status`、`platform`、`work_mode`、`created_from`、`created_to`、`q`、`sort`、分页参数。返回 `items`+统计信息。|
| 主播详情 | GET | `/api/pilots/<pilot_id>` | 返回完整字段（含所属、枚举值、分成信息）。|
| 创建主播 | POST | `/api/pilots` | 需要 `X-CSRFToken`；请求体允许填写昵称、真实姓名、枚举字段、直属运营等。保存后写入一条 `PilotChangeLog`。|
| 更新主播 | PUT | `/api/pilots/<pilot_id>` | 需要 `X-CSRFToken`；可一次性覆盖基础信息与枚举字段。会与旧值对比并写入变更记录。|
| 更新状态 | PATCH | `/api/pilots/<pilot_id>/status` | 单独调整 `status` 字段，写入变更日志。|
| 变更记录 | GET | `/api/pilots/<pilot_id>/changes` | 支持分页，返回最近变更的字段、旧值/新值、操作者、时间等。|
| 枚举选项 | GET | `/api/pilots/options` | 输出枚举字典（gender、platform、work_mode、rank、status），用于前端构建筛选器。|
| 导出CSV | GET | `/api/pilots/export` | 导出主播数据为CSV文件，支持筛选参数。|

**注意**：直属运营列表已从 `/api/pilots/options` 迁移到用户管理模块的 `/api/users/operators` 接口。

## 过滤与排序细节

- `owner_id` 可接受多个值（`?owner_id=<id>&owner_id=<id2>`），内部通过 `User.objects(id__in=...)` 过滤。
- `rank`、`status`、`platform`、`work_mode` 参数匹配 `Enum.value`，无效值会被忽略。
- `created_from`/`created_to` 需传 ISO8601（示例 `2025-10-02T00:00:00Z`），`created_to` 包含当日 23:59:59。
- `sort` 默认为 `-created_at`；也可传其他字段（如 `nickname`），非法字段会回退到默认排序。

## CSRF 与权限

- 所有写请求都通过 `validate_csrf_token()` 检查 `X-CSRFToken`；缺失或无效时返回 401 并在日志中记录。
- `@roles_accepted('gicho', 'kancho')` 允许运营和管理员调用全部接口；如需限制创建/删除为管理员，可在装饰器上调整角色。

## 日志与变更追踪

- 变更记录写入 `PilotChangeLog`，字段映射在 `_record_changes()` 中维护。新增字段或业务逻辑时需同步更新映射及序列化器。
- 常规日志通过 `get_logger('pilot')` 输出到 `log/pilot_YYYYMMDD.log`，重要信息（创建/更新/状态变更）记录为 INFO。

## 前端模板REST化状态

所有主播管理相关模板已完成REST化改造（2025-10-03）：

- ✅ `templates/pilots/list.html`: 主播列表页面，通过 `/api/pilots` 和 `/api/pilots/options` 获取数据
- ✅ `templates/pilots/detail.html`: 主播详情页面，通过 `/api/pilots/<id>` 和 `/api/pilots/<id>/changes` 获取数据
- ✅ `templates/pilots/new.html`: 新建主播页面，通过 `POST /api/pilots` 提交数据
- ✅ `templates/pilots/edit.html`: 编辑主播页面，通过 `PUT /api/pilots/<id>` 提交数据

所有前端页面均：
- 使用JavaScript动态加载和渲染数据
- 保持原有UI样式、布局和用户体验不变
- 实现了完整的错误处理和加载状态
- 使用CSRF Token保护所有写操作

## API增强

为支持前端REST化，对以下接口进行了增强：

### GET /api/pilots/<pilot_id>

新增返回字段：
- `commission`: 包含当前分成信息
  - `current_rate`: 当前分成比例
  - `effective_date`: 生效时间
  - `remark`: 备注
  - `calculation_info`: 计算信息（pilot_income, company_income, calculation_formula）

## 已知限制与待办

- `GET /api/pilots/export` 已实现CSV导出功能。
- 没有专门的 Owner/Activation PATCH 接口，前端需使用 `PUT /api/pilots/<id>` 进行整体更新。
- 缺少批量导入、批量更新等高级能力；如需扩展，建议保持现有响应格式。
- 枚举值当前直接返回英文字符串（源自枚举 value），若前端需要本地化标签，可在序列化时追加 `label` 字段。

## 维护建议

1. **新增字段时同步更新序列化与变更日志**：`serialize_pilot`、`serialize_pilot_list` 以及 `_record_changes` 必须保持一致，避免遗漏。
2. **注意直属运营引用**：`owner_id` 为空时会清空负责人；若需要保持原值，前端提交时应显式传递当前 `owner_id`。
3. **导出功能补强**：后续落地时，可在接口内直接生成 CSV 响应，或返回下载任务 ID，但需维持统一的 `success/data` 结构。

## 安全性增强 (2025-10-03)

### 字符串字段处理

为防止前端传递 `null` 值导致的 `AttributeError`，所有API均使用 `safe_strip()` 函数处理字符串字段：

```python
def safe_strip(value):
    """安全地去除字符串两端空格，处理None值"""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None
```

**影响的字段**：
- `nickname`: 主播昵称
- `real_name`: 真实姓名
- `hometown`: 籍贯

**修复的问题**：
- ✅ 杜绝 `'NoneType' object has no attribute 'strip'` 错误
- ✅ 统一处理空字符串和None值
- ✅ 确保数据库中不存储空字符串（统一为None）

### 只读字段处理

`Pilot` 模型中的某些字段是通过 `@property` 定义的计算属性，**不能直接赋值**：

- `age`: 通过 `birth_year` 自动计算，不可设置
- `gender_display`: 性别显示名称，不可设置
- `rank_display`: 主播分类显示名称，不可设置
- `status_display`: 状态显示名称，不可设置
- `work_mode_display`: 开播方式显示名称，不可设置
- `platform_display`: 开播平台显示名称，不可设置

**可直接设置的模型字段**：
- `nickname`, `real_name`, `gender`, `hometown`, `birth_year`
- `owner`, `platform`, `work_mode`, `rank`, `status`
- `created_at`, `updated_at`（自动维护）

**修复内容**：
- ✅ 移除所有对 `age` 字段的直接赋值操作
- ✅ 从 `field_mapping` 和 `old_data` 中移除 `age` 字段
- ✅ `age` 字段仅用于展示，通过 `birth_year` 自动计算

4. **错误码语义化**：当前常见错误码包括 `PILOT_NOT_FOUND`、`INVALID_OWNER`、`VALIDATION_ERROR` 等，新增错误码时保持命名规范，便于前端识别。
5. **日志脱敏**：日志中避免输出身份证、手机号等敏感字段，必要时可在保存前做遮挡。

如需进一步扩展 API（例如批量导入、更多筛选维度），请以上述现有实现为基线，保持 JSON 结构和权限策略的一致性。
