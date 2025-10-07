"""
API 测试客户端

提供统一的API调用接口，自动处理认证、CSRF等
"""
import httpx
from typing import Dict, Any, Optional
from urllib.parse import urljoin


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
                # 非JSON响应（如HTML重定向）
                return {
                    'success': False,
                    'error': {
                        'code': 'NON_JSON_RESPONSE',
                        'message': f'HTTP {response.status_code}'
                    },
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

    def get_csrf_token(self) -> str:
        """获取CSRF token（用于匿名请求）"""
        response = self.get('/api/auth/csrf')
        if response.get('success'):
            self.csrf_token = response['data'].get('csrf_token')
        return self.csrf_token
