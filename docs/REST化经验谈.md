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
| 模板仍引用旧路由 | 页面 500 或跳转 404 | 保留兼容路由或改链接直指新流转 |
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

## 10. 尚未 REST 化模块（现状提醒）
- 招募管理、分成管理、通告主流程、通告导出、开播记录 CRUD、开播日报/周报/月报、招募日报、仪表板、开播地点、邮件发送/报告等仍以传统表单或模板为主。任何任务若要使用 REST 接口，需要先落地对应蓝图，再更新模块专属指南。

## 11. 后续改造建议
- 建议以模块为单位逐步推进：先"补充只读 API + 统一序列化"，再"改写写入逻辑 + CSRF 中间件"。
- 每落地一组接口，同时更新对应的 `docs/模块-REST化指南.md`，保持文档与实现一致。
- 在同一个 PR 中同步新增集成测试（真实 CSRF + 权限 + 业务场景），为后续重构打下回归基础。

---
保持这份经验谈的及时更新，可以显著降低后续 REST 改造的沟通与排错成本。