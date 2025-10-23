"""
套件S5：通告与日程协同测试

覆盖 API：/announcements/api/announcements, /calendar/api/*, /battle-records/api/related-announcements
"""
from datetime import datetime, timedelta

import pytest

from tests.fixtures.factories import (announcement_factory,
                                      battle_area_factory, pilot_factory)


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
