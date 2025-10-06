# REST化总体报告

本文档旨在统一记录项目当前所有模块的REST API接口现状，作为开发和维护的权威参考。报告内容基于对 `routes/*_api.py` 文件的实际代码分析，并整合了原有各模块的REST化指南，确保信息准确反映截至 2025-10-06 的代码库实现。

## 统一约定

所有REST API在设计和实现上遵循以下通用约定：

### 1. 响应结构

API接口统一返回JSON格式的响应体，结构如下：

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": { ... }
}
```

- **success**: `true` 或 `false`，明确表示请求是否成功。
- **data**: 成功时返回的业务数据。若请求成功但无数据返回，可为 `null` 或 `{}`。失败时为 `null`。
- **error**: 失败时返回的错误详情对象，包含 `code` (字符串错误码，如 `USER_NOT_FOUND`) 和 `message` (可读的错误信息)。成功时为 `null`。
- **meta**: 附加信息，如分页 (`pagination`)、筛选器选项 (`filters`, `options`)、统计数据等。

### 2. 权限与安全

- **权限控制**: 所有接口均通过装饰器进行权限校验。
  - `@roles_required('gicho')`: 仅允许管理员访问。
  - `@roles_accepted('gicho', 'kancho')`: 允许管理员和运营人员访问。
- **CSRF防护**: 所有写入操作 (POST, PUT, PATCH, DELETE) 都需要客户端在HTTP请求头中提供 `X-CSRFToken` 字段。后端通过 `validate_csrf_token()` 进行校验。

### 3. 命名与风格

- **路径**: 采用小写字母、复数名词和连字符（kebab-case），例如 `/api/battle-records`。
- **字段**: JSON中的字段名统一使用下划线命名法（snake_case）。

---

## 各模块API详情

### 基础-用户管理 (`users_api.py`)

用户管理模块提供了完整的CRUD操作接口。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 获取用户列表 | GET | `/api/users` | 管理员 | 支持按角色(`role`)、激活状态(`active`)筛选和分页。 |
| 获取用户详情 | GET | `/api/users/<user_id>` | 管理员 | 返回用户详细信息及登录记录。 |
| 获取运营列表 | GET | `/api/users/operators` | 管理员, 运营 | 返回所有激活的运营和管理员，用于其他模块的筛选器。 |
| 创建运营账户 | POST | `/api/users` | 管理员 | 创建新用户，默认为运营角色。 |
| 更新用户信息 | PUT | `/api/users/<user_id>` | 管理员 | 可修改昵称、邮箱、角色。 |
| 切换激活状态 | PATCH | `/api/users/<user_id>/activation` | 管理员 | 启用或停用用户，禁止停用最后一名管理员。 |
| 重置密码 | POST | `/api/users/<user_id>/reset-password` | 管理员 | 为用户重置密码。 |
| 查询角色邮箱 | GET | `/api/users/emails` | 管理员 | 根据角色查询可用邮箱列表。 |

### 基础-开播地点管理 (`battle_areas_api.py`)

管理开播地点的增删改查及批量操作。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 获取地点列表 | GET | `/api/battle-areas` | 管理员, 运营 | 支持按基地(`x`)、场地(`y`)、可用性(`availability`)筛选。 |
| 获取地点详情 | GET | `/api/battle-areas/<id>` | 管理员, 运营 | 返回单个地点的详细信息。 |
| 创建地点 | POST | `/api/battle-areas` | 管理员, 运营 | 创建新的开播地点，会校验坐标唯一性。 |
| 更新地点 | PUT | `/api/battle-areas/<id>` | 管理员, 运营 | 更新地点信息，同样校验坐标唯一性。 |
| 批量生成 | POST | `/api/battle-areas/bulk-generate` | 管理员, 运营 | 根据源地点批量生成坐席，冲突时会返回重复列表。 |
| 获取筛选选项 | GET | `/api/battle-areas/options` | 管理员, 运营 | 返回用于构建筛选器的基地和场地选项。 |

### 基础-仪表盘 (`main.py`, `report.py`)

仪表盘数据通过一系列独立的API接口提供，前端并发加载。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 招募指标 | GET | `/api/dashboard/recruit` | 管理员, 运营 | 返回当日招募统计。 |
| 通告统计 | GET | `/api/dashboard/announcements` | 管理员, 运营 | 返回通告计划统计。 |
| 开播流水 | GET | `/api/dashboard/battle-records` | 管理员, 运营 | 返回开播记录流水统计。 |
| 主播人数 | GET | `/api/dashboard/pilots` | 管理员, 运营 | 返回服役、实习、正式主播的人数。 |
| 候补统计 | GET | `/api/dashboard/candidates` | 管理员, 运营 | 返回候补和试播阶段的人数。 |
| 横幅配置 | GET | `/api/dashboard/feature` | 管理员, 运营 | 返回仪表盘顶部的横幅信息。 |

### 主播-主播管理 (`pilots_api.py`)

提供主播信息的完整管理功能。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 获取主播列表 | GET | `/api/pilots` | 管理员, 运营 | 支持多维度筛选、搜索(`q`)和排序。 |
| 获取主播详情 | GET | `/api/pilots/<pilot_id>` | 管理员, 运营 | 返回主播完整信息，包含当前分成。 |
| 获取主播业绩 | GET | `/api/pilots/<pilot_id>/performance` | 管理员, 运营 | 返回主播的业绩统计数据。 |
| 创建主播 | POST | `/api/pilots` | 管理员, 运营 | 创建新主播并记录变更日志。 |
| 更新主播 | PUT | `/api/pilots/<pilot_id>` | 管理员, 运营 | 整体更新主播信息并记录变更。 |
| 更新状态 | PATCH | `/api/pilots/<pilot_id>/status` | 管理员, 运营 | 单独更新主播状态。 |
| 获取变更记录 | GET | `/api/pilots/<pilot_id>/changes` | 管理员, 运营 | 返回主播信息的历史变更记录。 |
| 获取筛选选项 | GET | `/api/pilots/options` | 管理员, 运营 | 返回用于筛选的枚举值（性别、平台等）。 |
| 导出CSV | GET | `/api/pilots/export` | 管理员, 运营 | 导出筛选后的主播数据为CSV文件。 |

### 主播-分成管理 (`commissions_api.py`)

管理主播的分成比例和记录。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 获取当前分成 | GET | `/api/pilots/<pilot_id>/commission/current` | 管理员, 运营 | 返回当前生效的分成信息和收入计算示例。 |
| 获取分成记录 | GET | `/api/pilots/<pilot_id>/commission/records` | 管理员, 运营 | 返回历史分成调整记录，支持分页。 |
| 创建分成记录 | POST | `/api/pilots/<pilot_id>/commission/records` | 管理员, 运营 | 新增一条分成调整记录。 |
| 更新分成记录 | PUT | `/api/pilots/<pilot_id>/commission/records/<record_id>` | 管理员, 运营 | 修改指定的分成记录。 |
| 停用分成记录 | POST | `/api/pilots/<pilot_id>/commission/records/<record_id>/deactivate` | 管理员, 运营 | 软删除（停用）一条分成记录。 |
| 激活分成记录 | POST | `/api/pilots/<pilot_id>/commission/records/<record_id>/activate` | 管理员, 运营 | 恢复一条已停用的分成记录。 |

### 主播-招募管理 (`recruits_api.py`)

覆盖从创建到结束的整个招募流程。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 获取招募列表 | GET | `/api/recruits` | 管理员, 运营 | 支持筛选、分页和前端搜索。 |
| 获取分组列表 | GET | `/api/recruits/grouped` | 管理员, 运营 | 返回按状态分组的招募列表，用于首页展示。 |
| 获取招募详情 | GET | `/api/recruits/<id>` | 管理员, 运营 | 返回单个招募的详细信息。 |
| 获取变更记录 | GET | `/api/recruits/<id>/changes` | 管理员, 运营 | 返回招募流程中的变更历史。 |
| 获取筛选选项 | GET | `/api/recruits/options` | 管理员, 运营 | 返回用于筛选器的选项数据。 |
| 导出招募数据 | GET | `/api/recruits/export` | 管理员, 运营 | 导出招募数据。 |
| 创建招募 | POST | `/api/recruits` | 管理员, 运营 | 启动一个新的招募流程。 |
| 更新招募 | PUT | `/api/recruits/<id>` | 管理员, 运营 | 更新招募的基础信息。 |
| 状态流转 | POST | `/api/recruits/<id>/<action>` | 管理员, 运营 | 执行状态流转，`action` 包括 `interview-decision`, `schedule-training`, `training-decision`, `schedule-broadcast`, `broadcast-decision`。 |

### 主播-开播记录 (`battle_records_api.py`)

管理主播的每一次开播记录。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 获取记录列表 | GET | `/battle-records/api/battle-records` | 管理员, 运营 | 支持按运营、时间范围等筛选。 |
| 获取记录详情 | GET | `/battle-records/api/battle-records/<record_id>` | 管理员, 运营 | 返回单条记录的详细财务和位置信息。 |
| 创建记录 | POST | `/battle-records/api/battle-records` | 管理员, 运营 | 创建一条新的开播记录。 |
| 更新记录 | PUT | `/battle-records/api/battle-records/<record_id>` | 管理员, 运营 | 修改开播记录的时间、金额等信息。 |
| 删除记录 | DELETE | `/battle-records/api/battle-records/<record_id>` | 管理员, 运营 | 删除一条开播记录及其变更日志。 |
| 获取变更记录 | GET | `/battle-records/api/battle-records/<record_id>/changes` | 管理员, 运营 | 返回该记录的字段变更历史。 |
| 获取辅助数据 | GET | `/battle-records/api/*` | 管理员, 运营 | 提供开播地点、关联通告等辅助数据接口。 |

### 主播-通告 (`announcements_api.py`)

通告模块的REST化程度较低，目前仅提供用于前端下拉框联动的辅助接口。核心的增删改查和冲突检查仍依赖服务端表单逻辑。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 查询场地 | GET | `/announcements/api/areas/<x_coord>` | 管理员, 运营 | 根据基地查询场地列表。 |
| 查询坐席 | GET | `/announcements/api/areas/<x_coord>/<y_coord>` | 管理员, 运营 | 根据基地和场地查询坐席列表。 |
| 按运营筛选主播 | GET | `/announcements/api/pilots/by-owner/<owner_id>` | 管理员, 运营 | 获取指定运营名下的主播列表。 |
| 模糊检索主播 | GET | `/announcements/api/pilots-filtered` | 管理员, 运营 | 根据关键字、运营、分类筛选主播。 |
| 获取筛选选项 | GET | `/announcements/api/pilot-filters` | 管理员, 运营 | 返回通告筛选器所需的选项。 |

**注意**: 通告的导出功能 (`/announcements/export`) 目前完全基于服务端渲染，**没有**对应的REST API。

### 主播-通告日历 (`calendar_api.py`)

为日历视图提供只读的数据聚合接口。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 月视图数据 | GET | `/calendar/api/month-data` | 管理员, 运营 | 按月聚合每日的通告数量。需`year`和`month`参数。 |
| 周视图数据 | GET | `/calendar/api/week-data` | 管理员, 运营 | 按周聚合每日的通告和资源情况。需`date`参数。 |
| 日视图数据 | GET | `/calendar/api/day-data` | 管理员, 运营 | 返回指定日期各坐席的时间轴数据。需`date`参数。 |

### 报告-日报/周报/月报 (`reports_api.py`)

为开播的日、周、月报表提供数据接口。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 开播日报 | GET | `/reports/api/daily` | 管理员, 运营 | 返回指定日期的日报数据。需`date`, `owner`, `mode`参数。 |
| 开播周报 | GET | `/reports/api/weekly` | 管理员, 运营 | 返回指定周的周报数据。需`week_start`, `owner`, `mode`参数。 |
| 开播月报 | GET | `/reports/api/monthly` | 管理员, 运营 | 返回指定月的月报数据。需`month`, `owner`, `mode`参数。 |

### 报告-招募日报 (`recruit_reports_api.py`)

为招募日报提供汇总和详情数据。

| 功能 | HTTP动词 | 路径 | 权限 | 说明 |
| --- | --- | --- | --- | --- |
| 招募日报数据 | GET | `/api/recruit-reports/daily` | 管理员, 运营 | 通过`view`参数区分返回汇总(`summary`)或详情(`detail`)数据。 |
