# 基础-开播地点管理 REST 接口说明

开播地点管理模块已完成 REST 化改造。页面沿用原有 UI，但所有数据读取与写入均通过以下接口完成。响应结构遵循《REST化经验谈》中约定的 `success/data/error/meta` 格式。

## 1. 已实现能力

| 能力 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 列表与筛选 | GET | `/api/battle-areas` | 支持按基地(`x`)、场地(`y`)、可用性(`availability`)筛选，默认仅返回“可用”状态。接口会将有效筛选条件写入 session，返回值的 `meta.filters` 与 `meta.options` 可直接驱动前端筛选器。|
| 详情 | GET | `/api/battle-areas/<id>` | 返回单个开播地点的基础信息与创建/更新时间。|
| 创建 | POST | `/api/battle-areas` | 根据 `x_coord`/`y_coord`/`z_coord`/`availability` 创建新开播地点。需在 Header 携带 `X-CSRFToken`。存在重复坐席时返回 409。|
| 更新 | PUT | `/api/battle-areas/<id>` | 更新基础信息及可用性。仍需 `X-CSRFToken`。更新前会校验复合坐标唯一性。|
| 批量生成 | POST | `/api/battle-areas/bulk-generate` | 基于源开播地点批量生成坐席范围。请求体需包含 `source_id`、`z_start`、`z_end`。若发现重复坐席，返回 409 并在 `meta.duplicates` 标注冲突列表。|
| 筛选选项 | GET | `/api/battle-areas/options` | 返回当前可选的基地/场地列表以及默认筛选值。前端在选择基地后可再次调用并携带 `x` 参数获取对应场地集合。|

## 2. 请求与响应要点

- **CSRF**：所有写操作必须读取 cookie 中的 `csrf_token`，并放入 `X-CSRFToken` 请求头。
- **唯一性约束**：创建和更新接口均会检查 `基地+场地+坐席` 是否重复，冲突时返回 `DUPLICATED_COORDINATE`。
- **默认筛选**：当请求未显式携带筛选条件时，后端会将 `availability` 默认设置为“可用”，并把结果写入 session，保证刷新后保持同样的筛选状态。
- **时间字段**：`created_at`、`updated_at` 以 GMT+8 ISO 字符串返回，前端按需格式化。

## 3. 接口示例

### 3.1 列表
```http
GET /api/battle-areas?x=无锡50&availability=可用
```

成功返回：
```json
{
  "success": true,
  "data": {
    "items": [
      {
        "id": "...",
        "x_coord": "无锡50",
      "y_coord": "房间A",
      "z_coord": "11",
      "availability": "可用",
      "created_at": "2025-10-04T10:03:21+08:00",
      "updated_at": "2025-10-04T10:03:21+08:00"
      }
    ]
  },
  "meta": {
    "filters": {"x": "无锡50", "y": "", "availability": "可用"},
    "options": {
      "x_choices": ["无锡50"],
      "y_choices": ["房间A", "房间B"],
      "availability_choices": ["可用", "禁用"]
    },
    "total": 1
  },
  "error": null
}
```

### 3.2 创建
```http
POST /api/battle-areas
Content-Type: application/json
X-CSRFToken: <token>

{
  "x_coord": "无锡50",
  "y_coord": "房间A",
  "z_coord": "12",
  "availability": "可用"
}
```

### 3.3 批量生成
```http
POST /api/battle-areas/bulk-generate
Content-Type: application/json
X-CSRFToken: <token>

{
  "source_id": "652f...",
  "z_start": "1",
  "z_end": "5"
}
```

若坐席区间有效且无冲突，返回 201，并附带 `source` 与 `created` 列表；若包含重复，返回 409：
```json
{
  "success": false,
  "error": {
    "code": "DUPLICATED_COORDINATE",
    "message": "存在已存在的开播地点，未执行生成"
  },
  "meta": {
    "duplicates": [
      {"x": "无锡50", "y": "房间A", "z": "3"}
    ]
  }
}
```

## 4. 前端集成提示

- 列表页首次加载时可直接调用 `/api/battle-areas`，随后根据 `meta.options` 填充筛选器；筛选变更时携带全部键值以保证 session 状态更新。
- 生成结果页面使用 `sessionStorage` 暂存一次性数据；用户刷新后若缓存失效，需要回到生成表单重新提交。
- 重复坐席提示已在返回的 `meta.duplicates` 中提供明细，可直接渲染给管理员查看。

以上内容保持与当前实现同步，后续如接口行为调整，请同步更新本指南。
