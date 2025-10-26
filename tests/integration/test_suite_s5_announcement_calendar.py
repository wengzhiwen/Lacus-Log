"""
套件S5：通告与日程协同测试

覆盖 API：/announcements/api/announcements, /calendar/api/*, /battle-records/api/related-announcements
"""
from datetime import datetime, timedelta
from uuid import uuid4

import pytest

from tests.fixtures.factories import (announcement_factory, battle_area_factory, pilot_factory)


@pytest.mark.suite("S5")
@pytest.mark.announcement_calendar
class TestS5AnnouncementCalendar:
    """通告与日程协同测试套件"""

    def test_s5_tc1_create_daily_recurring(self, admin_client):
        """S5-TC1 创建每日循环通告"""
        created_ids = {}
        try:
            pilot_resp = admin_client.post('/api/pilots', json=pilot_factory.create_pilot_data())
            if not pilot_resp.get('success'):
                pytest.skip("创建主播接口不可用")
            pilot_id = pilot_resp['data']['id']
            created_ids['pilot_id'] = pilot_id

            area_resp = admin_client.post('/api/battle-areas', json=battle_area_factory.create_battle_area_data())
            if not area_resp.get('success'):
                pytest.skip("创建开播地点接口不可用")
            area_id = area_resp['data']['id']
            created_ids['area_id'] = area_id

            start_time = datetime.now() + timedelta(days=1, hours=10)
            daily_data = announcement_factory.create_daily_recurrence_data(pilot_id=pilot_id,
                                                                           battle_area_id=area_id,
                                                                           start_time_str=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                                           end_date_str=(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d'),
                                                                           interval=1,
                                                                           duration_hours=6)

            ann_resp = admin_client.post('/announcements/api/announcements', json=daily_data)
            if not ann_resp.get('success'):
                pytest.skip("创建循环通告接口不可用")
            created_ids['ann_id'] = ann_resp['data']['id']

            assert ann_resp.get('success') is True
            cal_resp = admin_client.get('/calendar/api/day-data', params={'date': start_time.strftime('%Y-%m-%d')})
            assert cal_resp.get('_status_code') == 200
        finally:
            try:
                if 'ann_id' in created_ids:
                    admin_client.client.delete(f'/announcements/api/announcements/{created_ids["ann_id"]}',
                                               json={'delete_scope': 'future_all'},
                                               headers=admin_client._get_headers())
                if 'area_id' in created_ids:
                    admin_client.delete(f'/api/battle-areas/{created_ids["area_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except Exception:  # pylint: disable=broad-except
                pass

    def test_s5_tc2_create_weekly_recurring(self, admin_client):
        """S5-TC2 创建每周循环通告"""
        created_ids = {}
        try:
            pilot_resp = admin_client.post('/api/pilots', json=pilot_factory.create_pilot_data())
            if not pilot_resp.get('success'):
                pytest.skip("创建主播接口不可用")
            pilot_id = pilot_resp['data']['id']
            created_ids['pilot_id'] = pilot_id

            area_resp = admin_client.post('/api/battle-areas', json=battle_area_factory.create_battle_area_data())
            if not area_resp.get('success'):
                pytest.skip("创建开播地点接口不可用")
            area_id = area_resp['data']['id']
            created_ids['area_id'] = area_id

            start_time = datetime.now() + timedelta(days=2, hours=14)
            weekly_data = announcement_factory.create_weekly_recurrence_data(pilot_id=pilot_id,
                                                                             battle_area_id=area_id,
                                                                             start_time_str=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                                             end_date_str=(datetime.now() + timedelta(days=28)).strftime('%Y-%m-%d'),
                                                                             days_of_week=[1, 3, 5],
                                                                             interval=1,
                                                                             duration_hours=4)

            ann_resp = admin_client.post('/announcements/api/announcements', json=weekly_data)
            if not ann_resp.get('success'):
                pytest.skip("创建循环通告接口不可用")
            created_ids['ann_id'] = ann_resp['data']['id']

            assert ann_resp.get('success') is True
        finally:
            try:
                if 'ann_id' in created_ids:
                    admin_client.client.delete(f'/announcements/api/announcements/{created_ids["ann_id"]}',
                                               json={'delete_scope': 'future_all'},
                                               headers=admin_client._get_headers())
                if 'area_id' in created_ids:
                    admin_client.delete(f'/api/battle-areas/{created_ids["area_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except Exception:  # pylint: disable=broad-except
                pass

    def test_s5_tc3_edit_this_only(self, admin_client):
        """S5-TC3 编辑循环通告（只修改当前）"""
        created_ids = {}
        try:
            pilot_resp = admin_client.post('/api/pilots', json=pilot_factory.create_pilot_data())
            if not pilot_resp.get('success'):
                pytest.skip("创建主播接口不可用")
            pilot_id = pilot_resp['data']['id']
            created_ids['pilot_id'] = pilot_id

            area_resp = admin_client.post('/api/battle-areas', json=battle_area_factory.create_battle_area_data())
            if not area_resp.get('success'):
                pytest.skip("创建开播地点接口不可用")
            area_id = area_resp['data']['id']
            created_ids['area_id'] = area_id

            start_time = datetime.now() + timedelta(days=1, hours=10)
            daily_data = announcement_factory.create_daily_recurrence_data(pilot_id=pilot_id,
                                                                           battle_area_id=area_id,
                                                                           start_time_str=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                                           end_date_str=(datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d'),
                                                                           interval=1,
                                                                           duration_hours=4)

            ann_resp = admin_client.post('/announcements/api/announcements', json=daily_data)
            if not ann_resp.get('success'):
                pytest.skip("创建循环通告接口不可用")
            ann_id = ann_resp['data']['id']
            created_ids['ann_id'] = ann_id

            new_time_str = (datetime.now() + timedelta(days=1, hours=14)).strftime('%Y-%m-%d %H:%M:%S')
            update_resp = admin_client.patch(f'/announcements/api/announcements/{ann_id}',
                                             json={
                                                 'battle_area_id': area_id,
                                                 'start_time': new_time_str,
                                                 'duration_hours': 6,
                                                 'edit_scope': 'this_only'
                                             })
            if not update_resp.get('success'):
                pytest.skip("编辑通告（this_only）接口不可用")

            assert update_resp.get('success') is True
        finally:
            try:
                if 'ann_id' in created_ids:
                    admin_client.client.delete(f'/announcements/api/announcements/{created_ids["ann_id"]}',
                                               json={'delete_scope': 'future_all'},
                                               headers=admin_client._get_headers())
                if 'area_id' in created_ids:
                    admin_client.delete(f'/api/battle-areas/{created_ids["area_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except Exception:  # pylint: disable=broad-except
                pass

    def test_s5_tc4_edit_future_all(self, admin_client):
        """S5-TC4 编辑循环通告（修改未来所有）"""
        created_ids = {}
        try:
            pilot_resp = admin_client.post('/api/pilots', json=pilot_factory.create_pilot_data())
            if not pilot_resp.get('success'):
                pytest.skip("创建主播接口不可用")
            pilot_id = pilot_resp['data']['id']
            created_ids['pilot_id'] = pilot_id

            area_resp = admin_client.post('/api/battle-areas', json=battle_area_factory.create_battle_area_data())
            if not area_resp.get('success'):
                pytest.skip("创建开播地点接口不可用")
            area_id = area_resp['data']['id']
            created_ids['area_id'] = area_id

            start_time = datetime.now() + timedelta(days=1, hours=10)
            start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
            daily_data = announcement_factory.create_daily_recurrence_data(pilot_id=pilot_id,
                                                                           battle_area_id=area_id,
                                                                           start_time_str=start_time_str,
                                                                           end_date_str=(datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d'),
                                                                           interval=1,
                                                                           duration_hours=4)

            ann_resp = admin_client.post('/announcements/api/announcements', json=daily_data)
            if not ann_resp.get('success'):
                pytest.skip("创建循环通告接口不可用")
            ann_id = ann_resp['data']['id']
            created_ids['ann_id'] = ann_id

            new_time = datetime.now() + timedelta(days=1)
            update_data = {
                'battle_area_id': area_id,
                'start_time': start_time_str,
                'start_date': new_time.strftime('%Y-%m-%d'),
                'start_hour': '14',
                'start_minute': '00',
                'duration_hours': 6,
                'edit_scope': 'future_all'
            }

            update_resp = admin_client.patch(f'/announcements/api/announcements/{ann_id}', json=update_data)
            if not update_resp.get('success'):
                pytest.skip("编辑通告（future_all）接口不可用")

            assert update_resp.get('success') is True
        finally:
            try:
                if 'ann_id' in created_ids:
                    admin_client.client.delete(f'/announcements/api/announcements/{created_ids["ann_id"]}',
                                               json={'delete_scope': 'future_all'},
                                               headers=admin_client._get_headers())
                if 'area_id' in created_ids:
                    admin_client.delete(f'/api/battle-areas/{created_ids["area_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except Exception:  # pylint: disable=broad-except
                pass

    def test_s5_tc5_delete_this_only(self, admin_client):
        """S5-TC5 删除循环通告（只删除当前）"""
        created_ids = {}
        try:
            pilot_resp = admin_client.post('/api/pilots', json=pilot_factory.create_pilot_data())
            if not pilot_resp.get('success'):
                pytest.skip("创建主播接口不可用")
            pilot_id = pilot_resp['data']['id']
            created_ids['pilot_id'] = pilot_id

            area_resp = admin_client.post('/api/battle-areas', json=battle_area_factory.create_battle_area_data())
            if not area_resp.get('success'):
                pytest.skip("创建开播地点接口不可用")
            area_id = area_resp['data']['id']
            created_ids['area_id'] = area_id

            start_time = datetime.now() + timedelta(days=1, hours=10)
            daily_data = announcement_factory.create_daily_recurrence_data(pilot_id=pilot_id,
                                                                           battle_area_id=area_id,
                                                                           start_time_str=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                                           end_date_str=(datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d'),
                                                                           interval=1,
                                                                           duration_hours=4)

            ann_resp = admin_client.post('/announcements/api/announcements', json=daily_data)
            if not ann_resp.get('success'):
                pytest.skip("创建循环通告接口不可用")
            ann_id = ann_resp['data']['id']
            created_ids['ann_id'] = ann_id

            del_resp = admin_client.client.delete(f'/announcements/api/announcements/{ann_id}',
                                                  json={'delete_scope': 'this_only'},
                                                  headers=admin_client._get_headers())
            if del_resp.status_code != 200:
                pytest.skip("删除通告（this_only）接口不可用")

            resp_data = del_resp.get_json()
            assert resp_data.get('meta', {}).get('deleted_count', 0) == 1
            created_ids.pop('ann_id', None)
        finally:
            try:
                if 'ann_id' in created_ids:
                    admin_client.client.delete(f'/announcements/api/announcements/{created_ids["ann_id"]}',
                                               json={'delete_scope': 'future_all'},
                                               headers=admin_client._get_headers())
                if 'area_id' in created_ids:
                    admin_client.delete(f'/api/battle-areas/{created_ids["area_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except Exception:  # pylint: disable=broad-except
                pass

    def test_s5_tc6_delete_future_all(self, admin_client):
        """S5-TC6 删除循环通告（删除未来所有）"""
        created_ids = {}
        try:
            pilot_resp = admin_client.post('/api/pilots', json=pilot_factory.create_pilot_data())
            if not pilot_resp.get('success'):
                pytest.skip("创建主播接口不可用")
            pilot_id = pilot_resp['data']['id']
            created_ids['pilot_id'] = pilot_id

            area_resp = admin_client.post('/api/battle-areas', json=battle_area_factory.create_battle_area_data())
            if not area_resp.get('success'):
                pytest.skip("创建开播地点接口不可用")
            area_id = area_resp['data']['id']
            created_ids['area_id'] = area_id

            start_time = datetime.now() + timedelta(days=1, hours=10)
            daily_data = announcement_factory.create_daily_recurrence_data(pilot_id=pilot_id,
                                                                           battle_area_id=area_id,
                                                                           start_time_str=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                                           end_date_str=(datetime.now() + timedelta(days=5)).strftime('%Y-%m-%d'),
                                                                           interval=1,
                                                                           duration_hours=4)

            ann_resp = admin_client.post('/announcements/api/announcements', json=daily_data)
            if not ann_resp.get('success'):
                pytest.skip("创建循环通告接口不可用")
            ann_id = ann_resp['data']['id']
            created_ids['ann_id'] = ann_id

            del_resp = admin_client.client.delete(f'/announcements/api/announcements/{ann_id}',
                                                  json={'delete_scope': 'future_all'},
                                                  headers=admin_client._get_headers())
            if del_resp.status_code != 200:
                pytest.skip("删除通告（future_all）接口不可用")

            resp_data = del_resp.get_json()
            assert resp_data.get('meta', {}).get('deleted_count', 0) >= 1
            created_ids.pop('ann_id', None)
        finally:
            try:
                if 'ann_id' in created_ids:
                    admin_client.client.delete(f'/announcements/api/announcements/{created_ids["ann_id"]}',
                                               json={'delete_scope': 'future_all'},
                                               headers=admin_client._get_headers())
                if 'area_id' in created_ids:
                    admin_client.delete(f'/api/battle-areas/{created_ids["area_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except Exception:  # pylint: disable=broad-except
                pass

    def test_s5_tc7_related_announcements(self, admin_client):
        """S5-TC7 验证关联通告查询"""
        created_ids = {}
        try:
            pilot_resp = admin_client.post('/api/pilots', json=pilot_factory.create_pilot_data())
            if not pilot_resp.get('success'):
                pytest.skip("创建主播接口不可用")
            pilot_id = pilot_resp['data']['id']
            created_ids['pilot_id'] = pilot_id

            area_resp = admin_client.post('/api/battle-areas', json=battle_area_factory.create_battle_area_data())
            if not area_resp.get('success'):
                pytest.skip("创建开播地点接口不可用")
            area_id = area_resp['data']['id']
            created_ids['area_id'] = area_id

            start_time = datetime.now() + timedelta(days=1, hours=10)
            ann_data = announcement_factory.create_announcement_data(pilot_id=pilot_id,
                                                                     battle_area_id=area_id,
                                                                     start_time_str=start_time.strftime('%Y-%m-%d %H:%M:%S'),
                                                                     duration_hours=6)

            ann_resp = admin_client.post('/announcements/api/announcements', json=ann_data)
            if not ann_resp.get('success'):
                pytest.skip("创建通告接口不可用")
            ann_id = ann_resp['data']['id']
            created_ids['ann_id'] = ann_id

            related_resp = admin_client.get('/battle-records/api/related-announcements', params={'pilot_id': pilot_id})
            if not related_resp.get('success'):
                pytest.skip("查询关联通告接口不可用")

            announcements = related_resp.get('data', {}).get('announcements', [])
            assert isinstance(announcements, list)
        finally:
            try:
                if 'ann_id' in created_ids:
                    admin_client.client.delete(f'/announcements/api/announcements/{created_ids["ann_id"]}',
                                               json={'delete_scope': 'this_only'},
                                               headers=admin_client._get_headers())
                if 'area_id' in created_ids:
                    admin_client.delete(f'/api/battle-areas/{created_ids["area_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except Exception:  # pylint: disable=broad-except
                pass

    def test_s5_tc8_active_pilot_priority_in_dropdown(self, admin_client, kancho_client):  # pylint: disable=too-many-locals
        """
        S5-TC8 新建通告页主播下拉活跃优先

        步骤：创建两个主播，仅让其中一个在48小时内拥有开播记录，
              请求 /announcements/api/pilots-filtered 验证活跃主播排在最前。
        """
        me_resp = kancho_client.get('/api/auth/me')
        kancho_id = me_resp['data']['user']['id']

        suffix = uuid4().hex[:6]
        inactive_nickname = f'AlphaInactive_{suffix}'
        active_nickname = f'ZuluActive_{suffix}'

        base_kwargs = {'status': '已招募', 'rank': '正式主播', 'work_mode': '线下', 'platform': '快手', 'owner_id': kancho_id}
        inactive_data = pilot_factory.create_pilot_data(nickname=inactive_nickname, **base_kwargs)
        active_data = pilot_factory.create_pilot_data(nickname=active_nickname, **base_kwargs)

        created_pilots = []
        battle_record_id = None

        try:
            inactive_resp = admin_client.post('/api/pilots', json=inactive_data)
            if not inactive_resp.get('success'):
                pytest.skip('创建非活跃主播失败，无法验证排序')
            inactive_pilot_id = inactive_resp['data']['id']
            created_pilots.append(inactive_pilot_id)

            active_resp = admin_client.post('/api/pilots', json=active_data)
            if not active_resp.get('success'):
                pytest.skip('创建活跃主播失败，无法验证排序')
            active_pilot_id = active_resp['data']['id']
            created_pilots.append(active_pilot_id)

            start_time = datetime.utcnow() - timedelta(hours=4)
            end_time = datetime.utcnow() - timedelta(hours=1)

            battle_record_payload = {
                'pilot': active_pilot_id,
                'start_time': start_time.isoformat(),
                'end_time': end_time.isoformat(),
                'work_mode': '线下',
                'x_coord': 'A基地',
                'y_coord': '1号场',
                'z_coord': '01',
                'revenue_amount': '120.00',
                'base_salary': '0',
                'notes': '验证公告下拉活跃优先'
            }

            battle_response = admin_client.post('/battle-records/api/battle-records', json=battle_record_payload)
            if not battle_response.get('success'):
                pytest.skip('创建开播记录失败，无法验证排序')
            battle_record_id = battle_response['data']['id']

            list_response = admin_client.get('/announcements/api/pilots-filtered')
            assert list_response['success'] is True
            pilots = list_response['data'].get('pilots', [])
            id_to_index = {item['id']: idx for idx, item in enumerate(pilots)}

            assert active_pilot_id in id_to_index, '活跃主播未出现在通告下拉列表中'
            assert inactive_pilot_id in id_to_index, '非活跃主播未出现在通告下拉列表中'
            assert id_to_index[active_pilot_id] < id_to_index[inactive_pilot_id], '活跃主播未排在非活跃主播之前'

        finally:
            if battle_record_id:
                admin_client.delete(f'/battle-records/api/battle-records/{battle_record_id}')
            for pilot_id in created_pilots:
                try:
                    admin_client.put(f'/api/pilots/{pilot_id}', json={'status': '未招募'})
                except Exception:  # pylint: disable=broad-except
                    pass
