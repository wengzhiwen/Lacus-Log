"""BBS 模块 API 集成测试"""
# pylint: disable=no-member,too-few-public-methods
import uuid

import pytest

from models.bbs import BBSBoard, BBSBoardType, BBSPost


@pytest.mark.integration
@pytest.mark.bbs
class TestBBSBoardsAPI:
    """板块接口测试"""

    def test_list_boards_returns_active_boards(self, admin_client):
        """验证列表接口返回已启用板块"""
        board_code = f"test-board-{uuid.uuid4().hex[:8]}"
        board = BBSBoard(code=board_code, name='测试板块', board_type=BBSBoardType.CUSTOM, is_active=True)
        board.save()

        response = admin_client.get('/api/bbs/boards')

        assert response['success'] is True
        names = [item['name'] for item in response['data']['items']]
        assert '测试板块' in names

        board.delete()


@pytest.mark.integration
@pytest.mark.bbs
class TestBBSPostsAPI:
    """帖子与回复接口测试"""

    def setup_board(self):
        board_code = f"test-board-{uuid.uuid4().hex[:8]}"
        board = BBSBoard(code=board_code, name='帖子测试板块', board_type=BBSBoardType.CUSTOM, is_active=True)
        board.save()
        return board

    def teardown_post(self, post_id):
        try:
            post = BBSPost.objects.get(id=post_id)
            post.delete()
        except Exception:  # pylint: disable=broad-except
            pass

    def test_create_post_and_reply_flow(self, admin_client):
        """验证创建帖子和回复的基本流程"""
        board = self.setup_board()
        post_id = None
        try:
            create_resp = admin_client.post('/api/bbs/posts', json={'board_id': str(board.id), 'title': '测试帖子', 'content': '这是测试内容'})
            assert create_resp['success'] is True
            post_id = create_resp['data']['post']['id']

            detail_resp = admin_client.get(f'/api/bbs/posts/{post_id}')
            assert detail_resp['success'] is True
            assert detail_resp['data']['post']['title'] == '测试帖子'

            reply_resp = admin_client.post(f'/api/bbs/posts/{post_id}/replies', json={'content': '首条回复'})
            assert reply_resp['success'] is True
            assert reply_resp['data']['replies'][0]['content'] == '首条回复'

            list_resp = admin_client.get('/api/bbs/posts', params={'board_id': str(board.id)})
            assert list_resp['success'] is True
            assert any(item['id'] == post_id for item in list_resp['data']['items'])
        finally:
            if post_id:
                self.teardown_post(post_id)
            board.delete()
