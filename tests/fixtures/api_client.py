"""
API 测试客户端

提供统一的API调用接口，自动处理认证、CSRF等
"""
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import httpx


class ApiClient:
    """API集成测试客户端"""

    def __init__(self, base_url: str, client: Any = None):
        """
        初始化API客户端
        
        Args:
            base_url: API基础URL
            client: Flask test_client（可选，用于不启动服务器的测试）
        """
        self.base_url = base_url
        self.client = client
        self.csrf_token: Optional[str] = None
        self.access_token: Optional[str] = None
        self.cookies: Dict[str, str] = {}

    def _build_url(self, path: str) -> str:
        """构建完整URL"""
        if self.client:
            # 使用Flask test_client时，不需要完整URL
            return path
        return urljoin(self.base_url, path)

    def _get_headers(self, extra_headers: Optional[Dict] = None) -> Dict:
        """构建请求头"""
        headers = {
            'Content-Type': 'application/json',
        }

        # 添加CSRF token
        if self.csrf_token:
            headers['X-CSRFToken'] = self.csrf_token

        # 添加JWT token（如果有）
        if self.access_token:
            headers['Authorization'] = f'Bearer {self.access_token}'

        # 合并额外的headers
        if extra_headers:
            headers.update(extra_headers)

        return headers

    def request(self, method: str, path: str, **kwargs) -> Dict:
        """
        发送HTTP请求
        
        Args:
            method: HTTP方法
            path: API路径
            **kwargs: 其他请求参数（json, params等）
        
        Returns:
            响应JSON数据
        """
        url = self._build_url(path)
        headers = self._get_headers(kwargs.pop('headers', None))

        if self.client:
            # 使用Flask test_client（Flask test_client会自动管理session/cookies）
            method_func = getattr(self.client, method.lower())
            response = method_func(url, json=kwargs.get('json'), query_string=kwargs.get('params'), headers=headers)

            # 从Set-Cookie中提取CSRF token（用于后续请求）
            for cookie in response.headers.getlist('Set-Cookie'):
                if 'csrf_token=' in cookie:
                    csrf_value = cookie.split('csrf_token=')[1].split(';')[0]
                    if csrf_value:  # 只在非空时更新
                        self.csrf_token = csrf_value

            # 处理响应
            if response.content_type and 'application/json' in response.content_type:
                json_data = response.get_json() or {}
                # 为兼容性添加status_code
                json_data['_status_code'] = response.status_code
                return json_data
            else:
                # 非JSON响应（如HTML）
                html_content = response.get_data(as_text=True) if response.get_data() else ""

                # 尝试从HTML中提取CSRF token
                if html_content and not self.csrf_token:
                    import re
                    # 查找 data-csrf 属性
                    csrf_match = re.search(r'data-csrf="([^"]+)"', html_content)
                    if csrf_match:
                        self.csrf_token = csrf_match.group(1)
                    else:
                        # 查找 JavaScript 中的 csrfToken
                        csrf_match = re.search(r'csrfToken:\s*["\']([^"\']+)["\']', html_content)
                        if csrf_match:
                            self.csrf_token = csrf_match.group(1)

                return {
                    'success': response.status_code < 400,
                    'data': html_content,
                    '_status_code': response.status_code
                }
        else:
            # 使用httpx客户端（真实HTTP请求）
            response = httpx.request(method, url, headers=headers, cookies=self.cookies, **kwargs)

            # 更新cookies
            if response.cookies:
                self.cookies.update(dict(response.cookies))
                # 提取CSRF token
                if 'csrf_token' in response.cookies:
                    self.csrf_token = response.cookies['csrf_token']

            return response.json()

    def get(self, path: str, **kwargs) -> Dict:
        """GET请求"""
        return self.request('GET', path, **kwargs)

    def post(self, path: str, **kwargs) -> Dict:
        """POST请求"""
        return self.request('POST', path, **kwargs)

    def put(self, path: str, **kwargs) -> Dict:
        """PUT请求"""
        return self.request('PUT', path, **kwargs)

    def delete(self, path: str, **kwargs) -> Dict:
        """DELETE请求"""
        return self.request('DELETE', path, **kwargs)

    def patch(self, path: str, **kwargs) -> Dict:
        """PATCH请求"""
        return self.request('PATCH', path, **kwargs)

    def login(self, username: str, password: str) -> Dict:
        """
        登录并获取JWT token和CSRF token
        
        Args:
            username: 用户名
            password: 密码
        
        Returns:
            登录响应数据
        """
        response = self.post('/api/auth/login', json={'username': username, 'password': password})

        if response.get('success'):
            # 保存access token（用于后续请求的Authorization header）
            self.access_token = response['data'].get('access_token')
            # 保存CSRF token（从meta或cookie中）
            if 'meta' in response and 'csrf_token' in response['meta']:
                self.csrf_token = response['meta']['csrf_token']

        return response

    def logout(self) -> Dict:
        """登出"""
        response = self.post('/api/auth/logout')

        # 清除tokens
        self.access_token = None
        self.csrf_token = None
        self.cookies.clear()

        return response

    def refresh_token(self) -> Dict:
        """
        刷新 Access Token
        
        注意：此方法不发送 Authorization header，仅依赖 cookie 中的 refresh_token。
        这是为了正确模拟生产环境中的 refresh token 行为。
        
        技术背景：
        - Flask-JWT-Extended 要求刷新接口必须使用 refresh token 而非 access token
        - 配置中 JWT_TOKEN_LOCATION=['headers', 'cookies'] 会优先读取 header
        - 如果在 header 中发送 access token，会导致 422 错误
        - 生产环境中前端不会在刷新接口发送 Authorization header
        
        Returns:
            刷新响应数据
        """
        original_token = self.access_token
        self.access_token = None

        try:
            response = self.post('/api/auth/refresh')

            if response.get('success'):
                self.access_token = response['data'].get('access_token')
            else:
                self.access_token = original_token

            return response
        except Exception as exc:
            self.access_token = original_token
            raise exc

    def get_csrf_token(self) -> str:
        """获取CSRF token（用于匿名请求）"""
        response = self.get('/api/auth/csrf')
        if response.get('success'):
            self.csrf_token = response['data'].get('csrf_token')
        return self.csrf_token
