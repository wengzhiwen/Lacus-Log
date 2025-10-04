# REST化经验谈

> 这份笔记面向后续负责 REST 改造的 Coding Agent / 开发者，用来统一做法、避免踩坑。内容基于已落地的用户/主播管理 API 与多次复盘总结。

## 1. 目标与适用范围
- 适用于"原有 Flask 模板 + 表单"逐步迁移到"模板保持 UI，数据/动作走 REST API"的场景。
- 强调 **最小必要改动**：布局、交互习惯尽量不变，只替换数据来源和提交流程。
- 适用于新接口设计、旧接口维护、以及尚未 REST 化模块的规划评估。

## 2. 基础规范
### 2.1 响应结构
所有 REST 接口统一使用：
```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": { ... }
}
```
- 成功：`success=true`，结果放在 `data`；需要分页/统计时写入 `meta`。
- 失败：`success=false`，`error={code,message}`，`data=null`。状态码与语义匹配（400 参数错误、401 未登录/CSRF 失败、403 无权限、404 找不到、409 业务冲突）。
- 推荐错误码命名：`USER_NOT_FOUND`、`INVALID_OWNER`、`VALIDATION_ERROR`、`CSRF_ERROR` 等，方便前端做分支处理。

### 2.2 权限约定
- 内部管理功能统一使用 `@roles_accepted('gicho', 'kancho')` 或 `@roles_required('gicho')`。
- 如果接口只允许管理员操作（如创建用户、重置密码），显式改成 `@roles_required('gicho')`。
- 接口里如需进一步校验（例如"不能停用最后一名管理员"），在业务逻辑处返回 409 + 语义化错误信息。

### 2.3 序列化
- 数据出口集中在 `utils/<module>_serializers.py`，保证字段顺序、空值处理一致。
- 模型新增字段 → 同步更新序列化、变更日志映射以及前端解析代码。
- 字段空值统一通过 `safe_strip(value)`/`None` 归一，避免前端出现混合空字符串。

## 3. CSRF 与安全策略
### 3.1 双提交 Cookie 模式
- 生成 token：`generate_csrf()`，写入 cookie（`csrf_token`，`SameSite=Lax`），同时在登录响应或单独的 `/api/auth/csrf` 返回给前端。
- 前端所有写操作在 Header 加 `X-CSRFToken`，值与 cookie 保持一致。
- 中间层编写统一校验函数：比对 cookie 与 header，失败返回 401 并记录日志。

### 3.2 JWT 协同时序（若未来落地）
1. 登录成功：返回 access token（Authorization header）+ refresh/httpOnly cookie + csrf cookie。
2. 后续请求：`Authorization: Bearer <access>` + `X-CSRFToken`。
3. 刷新 token 时复用 refresh cookie 并重新生成 CSRF。

### 3.3 测试要求
- 单元测试可用 `with app.test_client()` + `csrf_disable()` 等方式豁免。
- 集成/端到端测试必须按照真实流程获取 CSRF，避免上线后前端踩坑。

## 4. 日志与审计
- 入口/出口 INFO：记录接口、操作者、关键参数摘要（脱敏）。
- 异常 ERROR：`logger.error('xxx', exc_info=True)` 方便排查。
- 变更记录写入专表（如 `PilotChangeLog`、`RecruitChangeLog`），字段与模型保持同步。

## 5. 前端协作要点
- 初始化阶段用 `Promise.all` 并发拉取字典、列表等接口。
- 错误处理统一：后台返回的 `error.message` → 页面常驻错误区 + toast。
- 导出优先用浏览器直接跳转 `/api/.../export?...`，若必须加 Header 再用 `fetch -> blob`。
- 原模板链接如果指向旧路由（如 `/pilots/export`），新增兼容跳板 302 到 REST 接口，避免 404。

## 6. 测试策略
1. **接口单测**：使用 Flask test client 构造请求，校验 `success/error/meta`；写操作带真实 CSRF。
2. **集成测试**：模拟真实登录 → 存储 cookie + token → 后续请求携带 header。
3. **回归脚本**：覆盖分页、筛选、错误分支（缺字段、非法枚举、冲突等）。

## 7. 典型实施流程（Checklist）
1. **梳理页面数据点**：明确列表、详情、表单字段；UI 保持不变。
2. **只读接口优先**：先实现列表/详情/选项；页面改为 `fetch` 获取数据。
3. **再改写操作**：实现创建/更新/状态变更接口，前端提交改为 AJAX；原表单可保留备用。
4. **补充导出**：处理好响应头、BOM、文件名；确保与筛选条件一致。
5. **审计与 CSRF**：写操作日志、双提交 cookie 校验到位。
6. **移除冗余脚本**：临时 polyfill/调试脚本在上线前删掉。

## 8. 常见坑与对策
| 场景 | 症状 | 对策 |
| --- | --- | --- |
| 模板仍引用旧路由 | 页面 500 或跳转 404 | 旧路由只渲染基础页面，要做的是彻底的REST化 |
| 枚举值非法导致 500 | `Enum(value)` 抛异常 | 过滤参数前先校验；忽略非法值或返回 400。|
| 变更记录缺字段 | 序列化 KeyError | 按模型字段更新 `_record_changes`；增加保护逻辑。|
| JS 中字符串模板处理错误 | URL 出现 `${item.id}` | 直接传变量 `getUrl(item.id)`，不要再套字符串。|
| 时区误差 | 统计跨日错误 | 统一使用 `utils/timezone_helper`，业务口径按 GMT+8。|
| 导出乱码 | Excel 中文乱码 | 在 CSV 前加 `\ufeff`，响应头设 `text/csv; charset=utf-8`。|
| ORM 查询 ObjectId 验证失败 | `ValidationError: '' is not a valid ObjectId` | 在后端，对来自前端的 ID 列表进行过滤，剔除空字符串或无效值，再进行数据库查询。`valid_ids = [i for i in id_list if i]` |
| 序列化时枚举字段报错 | `AttributeError: 'str' object has no attribute 'value'` | 数据库中可能存在脏数据（直接存了字符串而非枚举值）。序列化时增加类型检查，`return val if isinstance(val, str) else val.value`，增强代码健壮性。 |
| Jinja2 模板渲染失败 | `UndefinedError: 'my_func' is undefined` | 严格遵守后端传递数据、前端只负责渲染的原则。不要在模板中调用未传递的函数。应在后端路由中计算好变量再传入。 |
| 前端显示时间与预期不符 | 界面显示22:00，但后端计算的是14:00 | 检查Jinja2过滤器或JS格式化函数。很可能过滤器期望UTC时间，但被传入了本地时间，导致重复时区转换。确保传入过滤器的时间对象时区正确，或直接在后端格式化为字符串。 |
| 后端出现循环导入 | `ImportError: cannot import name 'X' from 'Y'` | 模块功能要内聚。避免API模块和模板路由模块互相导入。应将共享的业务逻辑或查询逻辑下沉到独立的 `utils` 或 `services` 模块。 |
| ORM/ODM 方法调用失败 | `TypeError: unexpected keyword argument 'flat'` | 不同ORM/ODM（如Django ORM vs MongoEngine）的API有差异。使用 `values_list()` 等方法时，应查阅具体框架的文档，不能想当然。MongoEngine获取ID列表应使用 `[obj.id for obj in queryset]`。 |
| 前端未正确展示后端筛选结果 | 选择了"鸽"筛选，但列表仍显示其他分组 | 前端逻辑应与后端API解耦。前端只负责**展示**后端返回的数据。如果API已经按"鸽"过滤，前端就不应再对结果进行二次分组，而是直接渲染"鸽"分组。 |
| 模板中None值显示为字符串"None" | 备注字段、其他可选字段在数据库中为None时，前端显示"None" | 在Jinja2模板中使用 `{{ field or '' }}` 而不是 `{{ field }}`，确保None值显示为空字符串。序列化器中也应处理None值：`field if field else ''`。 |
| 默认时间计算错误 | 期望显示14:00，实际显示22:00 | 检查时区转换逻辑。`local_datetime_for_input` 过滤器期望UTC时间，如果传入本地时间会重复转换。应先计算本地时间，再转换为UTC传给模板。 |
| 路由路径错误导致404 | 按钮链接指向错误路径 | 检查蓝图注册的url_prefix，确保模板中的链接路径与蓝图前缀一致。如蓝图前缀为`/recruits`，链接应为`/recruits/action`而不是`/recruit/action`。 |

## 9. 可复用代码片段
```python
# CSRF 校验示例
from flask import request
from flask_wtf import csrf

def validate_csrf_header():
    token_header = request.headers.get('X-CSRFToken')
    token_cookie = request.cookies.get('csrf_token')
    if not token_header or token_header != token_cookie:
        raise ValueError('CSRF token mismatch')
    csrf.validate_csrf(token_header)
```

```python
# 统一成功/失败响应
from flask import jsonify

def create_success_response(data=None, meta=None):
    return {'success': True, 'data': data or {}, 'error': None, 'meta': meta or {}}

def create_error_response(code, message):
    return {'success': False, 'data': None, 'error': {'code': code, 'message': message}, 'meta': {}}

# 使用
return jsonify(create_success_response(payload, meta)), 200
```

```javascript
// fetch 封装示例
async function apiRequest(url, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    'X-CSRFToken': getCsrfTokenFromCookie(),
    ...options.headers,
  };
  const res = await fetch(url, { ...options, headers });
  const payload = await res.json();
  if (!payload.success) throw new Error(payload.error?.message || '操作失败');
  return payload;
}
```

## 10. 通告模块 REST 化对照指南

### 10.1 业务与体验约束
- 参照 `docs/主播-通告.md`：所有操作仍需保留“日历工具式”体验，循环通告在编辑/删除时必须提供“仅本次/全部/未来”选项。
- 新建流程先点“检查”再启用“登录通告”按钮，冲突列表需展示**所有**拟生成的通告实例（而非只列冲突项），以便用户确认。
- 列表默认筛选“两天内”，筛选项需持久化在 session（`persist_and_restore_filters`）；任何 REST 改造都不能破坏默认筛选口径与快速检索体验。
- 通告默认写入基地/场地/坐席快照，后端仍以 UTC 存储时间，页面展示沿用 `utils.timezone_helper`，避免时区漂移。

### 10.2 现有 JSON / REST 接口
| 功能 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 通告列表 | GET | `/announcements/api/announcements` | 复用 session 筛选，返回 `items` 与当前筛选、可选项元信息。|
| 通告详情 | GET | `/announcements/api/announcements/<id>` | 返回通告基础信息、循环信息、审计信息及相关事件列表。|
| 新建通告 | POST | `/announcements/api/announcements` | 统一 JSON 提交，落库前执行冲突校验，返回重定向地址与提示文案。|
| 更新通告 | PATCH | `/announcements/api/announcements/<id>` | 支持 `edit_scope`=`this_only`/`future_all`，复用循环拆分逻辑并写入变更记录。|
| 删除通告 | DELETE | `/announcements/api/announcements/<id>` | 接受 `delete_scope`，返回影响数量与提示信息。|
| 冲突预检查 | POST | `/announcements/api/check-conflicts` | 返回计划实例与冲突列表；编辑循环时需要传入 `exclude_id`、`edit_scope`。|
| 通告变更记录 | GET | `/announcements/api/announcements/<id>/changes` | 返回最近 100 条字段变更，字段名、操作者、IP 等字段齐备。|
| 基地选项 | GET | `/announcements/api/areas/options` | 返回可用基地列表及默认值。|
| 获取场地联动 | GET | `/announcements/api/areas/<x_coord>` | 返回指定基地下的可用场地列表。|
| 获取坐席联动 | GET | `/announcements/api/areas/<x_coord>/<y_coord>` | 返回指定基地+场地下的坐席与 `battle_area_id`。|
| 主播筛选器枚举 | GET | `/announcements/api/pilot-filters` | 返回直属运营、主播分类枚举，用于本地搜索。|
| 条件过滤主播列表 | GET | `/announcements/api/pilots-filtered` | 支持 `owner`、`rank` 筛选，返回昵称、真实姓名、状态等信息。|
| 按所属筛选主播 | GET | `/announcements/api/pilots/by-owner/<owner_id>` | 快速列出指定运营/无所属名下的主播，供选择器使用。|

所有接口统一使用 `success/data/error/meta` 结构，并通过 `utils/announcement_serializers` 提供字段收敛。

### 10.3 模板与 API 协作方式
- `/announcements/`：页面骨架由模板渲染，数据加载完全依赖 `GET /announcements/api/announcements`，筛选、搜索均在前端处理。
- `/announcements/new`、`/announcements/<id>/edit`：表单展示由模板负责（含默认值），校验与提交改为调用 REST API，仍要求先运行冲突检查再提交。
- `/announcements/<id>`：详情信息继续由模板渲染，但删除、变更记录等操作均使用 REST API（变更记录弹窗、删除按钮）。
- `/announcements/cleanup`、`/announcements/export`：暂保持模板同步流程，后续可视需求补充 API。

### 10.4 实施重点与注意事项
1. **冲突检查仍是第一道闸**：无论新建还是编辑接口，均需在落库前调度 `check-conflicts` 逻辑，返回冲突明细与计划实例。
2. **循环组操作复用模型方法**：更新/删除时仍调用 `split_recurrence_group_from_current()`、`get_future_announcements_in_group()` 等方法，确保循环组数据一致。
3. **序列化集中维护**：所有通告相关响应通过 `utils/announcement_serializers` 出口，新增字段需同步更新序列化与前端解析。
4. **前端统一 fetch 封装**：提交请求时默认带上 `X-CSRFToken`，错误信息通过 `showMessage` 提示，加载态使用全局 overlay。
5. **审计链路不可缺席**：API 层更新/删除操作必须写 INFO 日志并调用 `_record_changes`，维持与历史操作一致的审计记录。

### 10.5 后续优化方向
1. **清理与导出 API 化**：参考现有模式补充 `/announcements/api/cleanup`、`/announcements/api/export`，逐步下线同步表单。
2. **详情页数据切换**：后续可将详情主体也迁移到 REST 数据源，模板仅保留骨架。
3. **批量操作封装**：复用通用的 `fetchJson` 封装，减少各页面重复代码，统一错误与 loading 体验。
4. **复杂校验下沉服务层**：随着接口扩展，可将冲突校验、循环拆分抽离到 `services/announcement_service.py`，降低 API 函数复杂度。

---
保持这份经验谈的及时更新，可以显著降低后续 REST 改造的沟通与排错成本。
