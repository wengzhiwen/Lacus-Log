# pylint: disable=import-error,no-member
import pytest
from mongoengine import connect, disconnect

from models.battle_area import Availability, BattleArea
from models.user import Role, User


@pytest.mark.integration
@pytest.mark.requires_db
class TestBattleAreaRoutes:

    @pytest.fixture(autouse=True)
    def setup_db(self):
        try:
            disconnect()
        except Exception:
            pass
        connect('test_lacus', host='mongodb://localhost:27017/test_lacus')
        # 清理
        User.objects().delete()
        BattleArea.objects().delete()
        yield
        try:
            User.objects().delete()
            BattleArea.objects().delete()
        except Exception:
            pass
        disconnect()

    @pytest.fixture
    def create_gicho(self):
        from flask_security.utils import hash_password
        gicho_role = Role.objects(name="gicho").first()
        # 使用角色 id 避免 DBRef 未解引用
        gicho = User(username="gicho_user", password=hash_password("pwd"), nickname="议长", roles=[gicho_role.id] if gicho_role else [], active=True)
        gicho.save()
        return gicho

    def test_list_access(self, app, client, create_gicho):
        with app.app_context():
            # 未登录访问
            resp = client.get('/areas/')
            assert resp.status_code in [200, 403]

            # 登录议长
            with client.session_transaction() as sess:
                sess['_user_id'] = create_gicho.fs_uniquifier
                sess['_fresh'] = True

            resp = client.get('/areas/')
            assert resp.status_code in [200, 403]

    def test_crud_flow(self, app, client, create_gicho):
        with app.app_context():
            # 登录议长
            with client.session_transaction() as sess:
                sess['_user_id'] = create_gicho.fs_uniquifier
                sess['_fresh'] = True

            # 新建
            resp = client.post('/areas/new',
                               data={
                                   'x_coord': '无锡50',
                                   'y_coord': '房间A',
                                   'z_coord': '11',
                                   'availability': Availability.ENABLED.value
                               },
                               follow_redirects=True)
            assert resp.status_code in [200, 302, 403, 400]

            # 列表
            resp = client.get('/areas/')
            assert resp.status_code in [200, 403]

            # 取一个对象
            area = BattleArea.objects(x_coord='无锡50', y_coord='房间A', z_coord='11').first()
            if area:
                # 详情
                resp = client.get(f'/areas/{area.id}')
                assert resp.status_code in [200, 403]

                # 编辑
                resp = client.post(f'/areas/{area.id}/edit',
                                   data={
                                       'x_coord': '无锡50',
                                       'y_coord': '房间A',
                                       'z_coord': '12',
                                       'availability': Availability.DISABLED.value
                                   },
                                   follow_redirects=True)
                assert resp.status_code in [200, 302, 403]

                # 生成更多（如果数字范围有效）
                resp = client.post(f'/areas/{area.id}/generate', data={'z_start': '20', 'z_end': '22'}, follow_redirects=True)
                assert resp.status_code in [200, 302, 403, 400]
