"""导出开播记录CSV脚本

导出指定时间范围内的开播记录数据到CSV文件。
时间范围：2025年10月1日0点-10月16日2359（GMT+8）

运行：
  PYTHONPATH=. venv/bin/python scripts/export_battle_records.py
"""

import csv
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from app import create_app
from models.battle_record import BattleRecord
from utils.timezone_helper import local_to_utc, utc_to_local


def format_datetime_for_csv(utc_dt):
    """将UTC时间转换为GMT+8并格式化为CSV显示格式"""
    if not utc_dt:
        return ""
    local_dt = utc_to_local(utc_dt)
    return local_dt.strftime('%Y-%m-%d %H:%M:%S') if local_dt else ""


def get_user_display_name(user):
    """获取用户显示名称，优先显示昵称，无昵称时回退到用户名"""
    if not user:
        return ""
    return user.nickname if user.nickname else user.username


def export_battle_records():
    """导出开播记录到CSV文件"""
    # 设置时间范围：2025年10月1日0点-10月16日2359（GMT+8）
    start_local = datetime(2025, 10, 1, 0, 0, 0)  # GMT+8
    end_local = datetime(2025, 10, 16, 23, 59, 59)  # GMT+8

    # 转换为UTC时间用于数据库查询
    start_utc = local_to_utc(start_local)
    end_utc = local_to_utc(end_local)

    print(f"查询时间范围：{start_local} - {end_local} (GMT+8)")
    print(f"UTC时间范围：{start_utc} - {end_utc}")

    # 查询开播记录
    records = BattleRecord.objects(start_time__gte=start_utc, start_time__lte=end_utc).order_by('-start_time')

    print(f"找到 {len(records)} 条开播记录")

    # 准备CSV文件路径
    output_dir = Path('log')
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / 'battle_records_export_20251001_20251016.csv'

    # CSV表头
    headers = [
        '开播记录ID', '主播昵称', '主播真实姓名', '开始时间（GMT+8）', '时长（小时，保留一位小数）', '状态（开播中 / 已下播）', '流水金额', '开播方式', '底薪金额', '主播直属运营昵称', '登记人昵称', '创建时间（GMT+8）', '最后修改时间（GMT+8）'
    ]

    # 写入CSV文件
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(headers)

        for record in records:
            # 获取关联数据
            pilot = record.pilot
            owner = record.owner_snapshot
            registered_by = record.registered_by

            # 计算时长
            duration_hours = record.duration_hours or 0.0

            # 获取状态显示
            if record.status:
                if record.status.value == "live":
                    status_display = "开播中"
                elif record.status.value == "ended":
                    status_display = "已下播"
                else:
                    status_display = "已下播"  # 兼容老数据
            else:
                status_display = "已下播"  # 兼容老数据

            # 获取开播方式显示
            if record.work_mode:
                if record.work_mode.value == "线下":
                    work_mode_display = "线下"
                elif record.work_mode.value == "线上":
                    work_mode_display = "线上"
                else:
                    work_mode_display = "未知"
            else:
                work_mode_display = "未知"

            # 构建行数据
            row = [
                str(record.id),  # 开播记录ID
                pilot.nickname if pilot else "",  # 主播昵称
                pilot.real_name if pilot else "",  # 主播真实姓名
                format_datetime_for_csv(record.start_time),  # 开始时间（GMT+8）
                f"{duration_hours:.1f}",  # 时长（小时，保留一位小数）
                status_display,  # 状态
                str(record.revenue_amount or 0),  # 流水金额
                work_mode_display,  # 开播方式
                str(record.base_salary or 0),  # 底薪金额
                get_user_display_name(owner),  # 主播直属运营昵称
                get_user_display_name(registered_by),  # 登记人昵称
                format_datetime_for_csv(record.created_at),  # 创建时间（GMT+8）
                format_datetime_for_csv(record.updated_at)  # 最后修改时间（GMT+8）
            ]

            writer.writerow(row)

    print(f"导出完成：{output_file}")
    print(f"文件大小：{output_file.stat().st_size} bytes")

    return output_file


def main():
    """主函数"""
    load_dotenv()
    app = create_app()

    with app.app_context():
        try:
            output_file = export_battle_records()
            print(f"\n✅ 导出成功！文件保存在：{output_file}")
        except Exception as e:
            print(f"\n❌ 导出失败：{e}")
            raise


if __name__ == '__main__':
    main()
