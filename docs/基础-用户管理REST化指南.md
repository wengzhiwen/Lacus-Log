# 基础-用户管理REST化指南

本指南用于指导开发者将用户管理模块改造为完整的 RESTful API 形态，并确保前端通过统一的 JSON 接口完成数据渲染与交互。本项目仍保留后台模板渲染，但页面数据均来源于 REST 接口。请在改造前完整阅读本文档并结合 `基础-用户系统.md` 中的领域说明。

## 改造目标

- 所有用户管理功能（列表、详情、创建、状态切换、密码重置等）均提供 RESTful API。
- 页面渲染数据完全由前端通过 API 请求获取，不直接依赖 Flask 服务器端模板上下文。
- 接口返回统一的 JSON 响应结构，便于自动化测试与调试。
- 所有需要提交数据的操作均在前端携带 CSRF 令牌调用 RESTful API。

## 统一 JSON 响应规范

### 字段约定

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": { ... }
}
```

- `success`: `true/false`，表示本次请求是否成功。
- `data`: 成功时返回的业务数据；失败时为 `null`。
- `error`: 失败时的错误信息对象，推荐结构：`{"code": "USER_NOT_FOUND", "message": "用户不存在"}`，成功时为 `null`。
- `meta`: 额外的分页或统计信息，默认可返回空对象 `{}`。

### HTTP 状态码

- 成功请求使用 2xx：`200 OK`（查询/更新）、`201 Created`（创建成功）、`204 No Content`（无响应体时）。
- 客户端错误使用 4xx：`400 Bad Request`（参数错误）、`401 Unauthorized`（未登录）、`403 Forbidden`（权限不足）、`404 Not Found`（资源不存在）、`409 Conflict`（用户名重复）。
- 服务器错误统一返回 `500 Internal Server Error`，并记录详细日志。

## 路由与动词设计

| 功能 | HTTP 动词 | 路径 | 说明 |
| --- | --- | --- | --- |
| 获取用户列表 | GET | `/api/users` | 支持 `role`、`active`、分页参数。|
| 获取用户详情 | GET | `/api/users/<user_id>` | 返回用户基础信息与登录追踪。|
| 创建运营账户 | POST | `/api/users` | 请求体包含 `username`、`password`、`nickname`、`email`。默认角色为运营。|
| 更新用户信息 | PUT | `/api/users/<user_id>` | 限制可修改字段：`nickname`、`email`、`roles`。|
| 切换激活状态 | PATCH | `/api/users/<user_id>/activation` | 支持启用/停用，避免停用最后一名管理员。|
| 重置密码 | POST | `/api/users/<user_id>/reset-password` | 仅管理员；返回临时密码或通知信息。|
| 查询角色可用邮箱 | GET | `/api/users/emails` | 可选 `role`、`only_active` 参数，对应现有 `get_emails_by_role`。|

> 注意：保持 Flask-Security-Too 的权限校验，REST 接口仍需 `@roles_required("gicho")` 等装饰器控制访问。

## 前端调用约定

1. 通过页面加载时注入的 `window.CSRF_TOKEN` 或隐藏 `<meta name="csrf-token">` 获取 CSRF。
2. 所有 `POST/PUT/PATCH/DELETE` 请求统一在 `X-CSRFToken` 头中携带令牌。
3. 使用 `fetch` 或现有 AJAX 封装统一处理 JSON 响应：
   - 若 `success === false`，读取 `error.message` 并提示用户。
   - 若接口返回 `meta.pagination`，用于渲染分页组件。
4. 页面初始化时先请求列表接口，填充数据后再渲染模板组件；详情页按需请求详情接口。

示例（以切换激活状态为例）：

```javascript
async function toggleActivation(userId, active) {
  const res = await fetch(`/api/users/${userId}/activation`, {
    method: 'PATCH',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': window.CSRF_TOKEN,
    },
    body: JSON.stringify({ active }),
  });
  const payload = await res.json();
  if (!payload.success) {
    throw new Error(payload.error?.message || '操作失败');
  }
  return payload.data;
}
```

## CSRF 令牌获取与校验

- 继续复用 Flask-WTF / Flask-Security-Too 的 CSRF 机制。
- 为前端提供统一的 CSRF 获取接口，例如：
  - 页面初次渲染时，在模板中写入：`<meta name="csrf-token" content="{{ csrf_token() }}">`；
  - 或提供 `/api/auth/csrf` GET 接口返回 `{"success": true, "data": {"token": "..."}}`。
- 后端 API 使用 `@csrf_protect.exempt` 白名单控制，确保仅对外部接口进行 CSRF 校验。
- 提交接口在视图中调用 `validate_csrf(request.headers.get("X-CSRFToken"))`，校验失败时返回 `401` 并写入安全日志。

## 日志与调试

- 请求失败时，使用 DEBUG 日志记录请求参数、用户信息与失败原因，确保不包含敏感信息。
- 权限拒绝、CSRF 校验失败等安全相关事件记录 INFO 日志，日志文件放置于 `log/security.log`（若尚未建立，请遵循日志目录规范创建）。
- 新接口上线前使用 `curl` 或 Postman 验证成功与失败响应结构是否符合规范。

## 开发建议流程

1. **整理现有视图**：梳理用户管理相关的 Flask 视图函数，将最后的模板渲染逻辑拆分为 `render_template + fetch` 模式。
2. **抽取序列化逻辑**：在 `utils/` 新增序列化函数（如 `serialize_user(user)`）确保统一字段输出。
3. **实现 REST 端点**：在 `routes` 中创建 `users_api.py` 或扩展现有模块，按上述路由实现 API。
4. **编写前端对接代码**：确认模板中仅负责初始化 JS 和挂载组件，所有数据由 API 返回。
5. **测试与文档**：编写接口测试用例（可先使用 `pytest`/`pytest-flask`），并在自动化场景中使用统一响应格式断言。

完成以上步骤后，用户管理模块即可与其他 REST 模块保持一致，也为后续构建纯 API 的集成测试打下基础。
