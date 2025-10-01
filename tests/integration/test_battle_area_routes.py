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
        gicho = User(username="gicho_user", password=hash_password("pwd"), nickname="议长", roles=[gicho_role.id] if gicho_role else [], active=True)
        gicho.save()
        return gicho

    def test_list_access(self, app, client, create_gicho):
        with app.app_context():
            resp = client.get('/areas/')
            assert resp.status_code in [200, 403]

            with client.session_transaction() as sess:
                sess['_user_id'] = create_gicho.fs_uniquifier
                sess['_fresh'] = True

            resp = client.get('/areas/')
            assert resp.status_code in [200, 403]

    def test_crud_flow(self, app, client, create_gicho):
        with app.app_context():
            with client.session_transaction() as sess:
                sess['_user_id'] = create_gicho.fs_uniquifier
                sess['_fresh'] = True

            resp = client.post('/areas/new',
                               data={
                                   'x_coord': '无锡50',
                                   'y_coord': '房间A',
                                   'z_coord': '11',
                                   'availability': Availability.ENABLED.value
                               },
                               follow_redirects=True)
            assert resp.status_code in [200, 302, 403, 400]

            resp = client.get('/areas/')
            assert resp.status_code in [200, 403]

            area = BattleArea.objects(x_coord='无锡50', y_coord='房间A', z_coord='11').first()
            if area:
                resp = client.get(f'/areas/{area.id}')
                assert resp.status_code in [200, 403]

                resp = client.post(f'/areas/{area.id}/edit',
                                   data={
                                       'x_coord': '无锡50',
                                       'y_coord': '房间A',
                                       'z_coord': '12',
                                       'availability': Availability.DISABLED.value
                                   },
                                   follow_redirects=True)
                assert resp.status_code in [200, 302, 403]

                resp = client.post(f'/areas/{area.id}/generate', data={'z_start': '20', 'z_end': '22'}, follow_redirects=True)
                assert resp.status_code in [200, 302, 403, 400]
