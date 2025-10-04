# REST化完成后的 CSRF 管理与 API 集成测试方案

> 前提：所有业务模块均已迁移到 REST API（只读/写入/导出等操作均通过 `/api/...` 实现），传统模板仅负责壳层。本文定义统一的 CSRF 防护策略与自动化测试规范，确保上线后的安全性与可回归性。

## 1. 统一 CSRF 策略

### 1.1 总体原则
- **双提交 Cookie + 自定义 Header**：服务器发放 `csrf_token` cookie（`SameSite=Lax`、生产环境 `Secure`），同时要求写操作在 Header 携带 `X-CSRFToken`，后端校验 cookie 与 header 一致。
- **所有写接口强制校验**：包含 POST/PUT/PATCH/DELETE 及任何产生副作用的自定义动词。无豁免逻辑。
- **GET/HEAD 等只读操作不校验**，但如含敏感信息，仍需登录态和权限控制。
- **WTForms 兼容**：页面表单可继续调用 `{{ csrf_token() }}`；因浏览器会自动携带 cookie，前端提交时只需在 ajax/fetch header 中复制 token。

### 1.2 Token 发放流程
1. **登录成功**：`POST /api/auth/login` 返回：
   - Access Token（Authorization header 或响应体）；
   - Refresh Token（httpOnly cookie）；
   - CSRF Token（`csrf_token` cookie + JSON 响应字段 `csrfToken`，顺便在响应头 `X-CSRFToken` 回传）。
2. **匿名用户获取**：提供 `GET /api/auth/csrf`，在用户登录前也可获取 token（用于如忘记密码、注册等受限场景）。
3. **token 刷新**：`POST /api/auth/refresh` 同样重新签发 Access Token、CSRF Token；刷新后旧 token 作废。

### 1.3 服务器端校验
- 新建 `utils/csrf_helper.py`：
  ```python
  from flask import request
  from flask_wtf import csrf
  
  class CSRFMismatch(ValueError):
      pass
  
  def validate_csrf_header():
      cookie_token = request.cookies.get('csrf_token')
      header_token = request.headers.get('X-CSRFToken')
      if not cookie_token or not header_token or cookie_token != header_token:
          raise CSRFMismatch('CSRF token mismatch')
      csrf.validate_csrf(header_token)
  ```
- 在所有写接口蓝图中调用：
  ```python
  try:
      validate_csrf_header()
  except CSRFMismatch as exc:
      logger.warning('CSRF校验失败: %s', exc)
      return jsonify(create_error_response('CSRF_ERROR', '缺少或无效的CSRF令牌')), 401
  ```
- 失败时记录 INFO（含用户ID、IP、端点），必要时写入安全日志。

### 1.4 JWT 配置（可选）
- Access Token 通过 `Authorization: Bearer <token>`；Refresh Token / CSRF 通过 cookie。
- 前端/移动端每次写请求：
  ```
  Authorization: Bearer <access_token>
  X-CSRFToken: <从 cookie 读取的 token>
  ```
- 自动化脚本同样走该流程，避免与线上行为不一致。

## 2. 前端与客户端约定
- 登录后缓存 `csrfToken`：存于内存或 LocalStorage，写请求从 cookie 读取保证一致。
- 自定义 fetch/axios 拦截器集中附加 `X-CSRFToken` 与 `Authorization`。
- 全局错误处理：若收到 401/`CSRF_ERROR`，自动触发重新获取 CSRF 或跳转登录。

## 3. API 集成测试体系

### 3.1 基础设施
- 测试框架：`pytest + httpx`（或 requests）。
- 在 `tests/api/conftest.py` 提供统一的 `ApiClient` fixture：
  1. 调用 `/api/auth/login`，保存 cookie、token、csrf；
  2. 默认在所有请求 header 加 `Authorization` 与 `X-CSRFToken`；
  3. 提供便捷方法（`post_json`, `patch_json`, `assert_success`, `assert_error`）。

```python
import httpx
import pytest

@pytest.fixture(scope='function')
def api_client(app):
    client = httpx.Client(app=app, base_url='http://testserver', follow_redirects=True)
    res = client.post('/api/auth/login', json={'username': 'admin', 'password': '123456'})
    res.raise_for_status()
    csrf_token = client.cookies.get('csrf_token')
    client.headers['X-CSRFToken'] = csrf_token
    client.headers['Authorization'] = f"Bearer {res.json()['data']['access_token']}"
    return client
```

### 3.2 覆盖范围
| 模块 | 必测场景 |
| --- | --- |
| 用户/主播管理 | 列表（分页/筛选）、详情、创建、更新、状态切换、错误分支（重名、非法角色）。|
| 招募/分成/通告等 | 各自 CRUD + 特殊业务（状态流转、冲突检查、批量生成/导出）。|
| 报表导出 | CSV/Excel 响应头、BOM、筛选条件一致性。|
| 权限 | gicho / kancho / 未登录请求的 403 / 401 场景。|
| CSRF | 缺 header / token 错误 → 401；正确流程 → 2xx。|

### 3.3 数据管理
- 测试库：使用独立数据库（`MONGODB_URI` 指向 Test DB），测试结束后 drop。
- fixture：使用 `@pytest.fixture(scope='function')` 准备数据，结束时清理。
- 如需保留数据用于调试，可增加 `--keep-db` 开关。

### 3.4 CI/流水线
- CI 阶段执行 `pytest tests/api --maxfail=1 --disable-warnings`。
- 如测试依赖外部服务（SMTP、第三方 API），在流水线中通过 docker-compose 模拟或使用 Mock Server。
- 失败日志保存响应体，有助快速定位 `error.code`。

## 4. 迁移步骤建议
1. **落地中间层**：实现 `utils/csrf_helper.py`，登录/刷新接口返回 token，所有写 API 调整校验。
2. **前端改造**：统一 fetch/axios 包装，确保 token 从 cookie 读取并入 header。
3. **旧表单适配**：检查关键页面表单提交流程，引导前端加入 header（必要时在模板内注入 `<script>` 封装）。
4. **编写基础集成测试**：先覆盖用户/主播管理模块，确保流程跑通；后续模块按节奏补齐。
5. **引入CI**：将 `tests/api` 纳入流水线，作为 REST 改造的“回归闸门”。

## 5. 风险与缓解
- **Token 不同步**：确保所有入口（登录、刷新、获取 CSRF）都同步设置 cookie + header；如存在跨域，需要设置 `Access-Control-Allow-Credentials`。
- **脚本忘带 header**：在测试/文档中强调流程，并在 API 返回 401 时给出明确错误码/提示。
- **Cookie 安全**：生产环境统一启用 HTTPS + `Secure`；开发环境保留非安全模式便于调试。
- **时区/导出等业务影响**：在测试中加入具体断言，避免 REST 化后出现统计偏差。

---
该方案实施后，可在完全 REST 的架构下实现统一的 CSRF 防护与可预测的 API 集成测试，支持 SPA、移动端、自动化脚本与未来的 JWT 扩展。
