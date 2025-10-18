#!/usr/bin/env python3
"""底薪申请记录导入脚本

根据CSV文件创建底薪申请记录。CSV文件应包含开播记录信息，脚本会：
1. 解析CSV文件，识别需要创建底薪申请记录的行
2. 验证开播记录是否存在
3. 检查是否已存在底薪申请记录
4. 显示预览信息，等待用户确认
5. 创建底薪申请记录

运行：
  PYTHONPATH=. venv/bin/python scripts/import_base_salary_applications.py /path/to/battle_records_export.csv
"""

import csv
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flask import Flask
from flask_security.utils import login_user

from app import create_app
from models.battle_record import BaseSalaryApplication, BaseSalaryApplicationStatus, BaseSalaryApplicationChangeLog, BattleRecord
from models.user import User
from utils.timezone_helper import local_to_utc


class BaseSalaryApplicationImporter:
    """底薪申请记录导入器"""

    def __init__(self, app: Flask):
        self.app = app
        self.operator_user_id = "68d8bf64a22c00f9b94e4b3b"  # 指定的操作人ID

    def parse_csv_file(self, csv_path: Path) -> List[Dict]:
        """解析CSV文件，返回需要处理的记录列表"""
        records = []

        with open(csv_path, 'r', encoding='utf-8-sig') as f:  # 使用utf-8-sig处理BOM
            reader = csv.DictReader(f)

            for row_num, row in enumerate(reader, start=2):  # 从第2行开始（跳过标题行）
                try:
                    # 提取关键字段
                    battle_record_id = row.get('开播记录ID', '').strip()
                    base_salary_amount_str = row.get('申请底薪金额', '').strip()
                    settlement_type_str = row.get('结算方式', '').strip()
                    start_time_str = row.get('开始时间（GMT+8）', '').strip()

                    # 跳过申请底薪金额为0或空的记录
                    if not base_salary_amount_str or base_salary_amount_str == '0':
                        continue

                    # 跳过开播记录ID为空的记录
                    if not battle_record_id:
                        print(f"警告：第{row_num}行开播记录ID为空，跳过")
                        continue

                    # 解析申请底薪金额
                    try:
                        base_salary_amount = Decimal(base_salary_amount_str)
                    except (ValueError, TypeError):
                        print(f"警告：第{row_num}行申请底薪金额格式错误：{base_salary_amount_str}，跳过")
                        continue

                    # 解析结算方式
                    settlement_type = self._parse_settlement_type(settlement_type_str)
                    if not settlement_type:
                        print(f"警告：第{row_num}行结算方式无效：{settlement_type_str}，跳过")
                        continue

                    # 解析开始时间
                    try:
                        start_time_local = datetime.strptime(start_time_str, '%Y/%m/%d %H:%M')
                        start_time_utc = local_to_utc(start_time_local)
                    except (ValueError, TypeError):
                        print(f"警告：第{row_num}行开始时间格式错误：{start_time_str}，跳过")
                        continue

                    records.append({
                        'row_num': row_num,
                        'battle_record_id': battle_record_id,
                        'base_salary_amount': base_salary_amount,
                        'settlement_type': settlement_type,
                        'start_time_utc': start_time_utc,
                        'pilot_nickname': row.get('主播昵称', '').strip(),
                        'pilot_real_name': row.get('主播真实姓名', '').strip(),
                        'revenue_amount': row.get('流水金额', '').strip(),
                    })

                except Exception as e:
                    print(f"错误：第{row_num}行解析失败：{e}")
                    continue

        return records

    def _parse_settlement_type(self, settlement_type_str: str) -> Optional[str]:
        """解析结算方式字符串为枚举值"""
        mapping = {
            '日结底薪': 'daily_base',
            '月结底薪': 'monthly_base',
            '无底薪': 'none',
        }
        return mapping.get(settlement_type_str)

    def validate_records(self, records: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """验证记录，返回有效记录和无效记录"""
        valid_records = []
        invalid_records = []

        for record in records:
            battle_record_id = record['battle_record_id']

            # 检查开播记录是否存在
            try:
                battle_record = BattleRecord.objects.get(id=battle_record_id)  # pylint: disable=no-member
                record['battle_record'] = battle_record
                record['pilot'] = battle_record.pilot
            except Exception:
                invalid_records.append({**record, 'error': f"开播记录不存在：{battle_record_id}"})
                continue

            # 检查是否已存在底薪申请记录
            existing_application = BaseSalaryApplication.objects(  # pylint: disable=no-member
                battle_record_id=battle_record_id).first()

            if existing_application:
                invalid_records.append({**record, 'error': f"已存在底薪申请记录：{existing_application.id}"})
                continue

            valid_records.append(record)

        return valid_records, invalid_records

    def preview_import(self, valid_records: List[Dict], invalid_records: List[Dict]) -> None:
        """显示导入预览信息"""
        print("\n" + "=" * 80)
        print("底薪申请记录导入预览")
        print("=" * 80)

        print(f"\n总计CSV记录数：{len(valid_records) + len(invalid_records)}")
        print(f"有效记录数：{len(valid_records)}")
        print(f"无效记录数：{len(invalid_records)}")

        if invalid_records:
            print("\n无效记录详情：")
            for record in invalid_records:
                print(f"  第{record['row_num']}行：{record['error']}")

        if valid_records:
            print("\n将创建以下底薪申请记录：")
            print("-" * 80)

            # 按结算方式分组统计
            daily_count = 0
            monthly_count = 0
            total_amount = Decimal('0')

            for record in valid_records:
                if record['settlement_type'] == 'daily_base':
                    daily_count += 1
                elif record['settlement_type'] == 'monthly_base':
                    monthly_count += 1
                total_amount += record['base_salary_amount']

            print(f"日结底薪申请：{daily_count}条")
            print(f"月结底薪申请：{monthly_count}条")
            print(f"总申请金额：{total_amount}元")

            print("\n详细记录：")
            for record in valid_records[:10]:  # 只显示前10条
                print(f"  开播记录ID：{record['battle_record_id']}")
                print(f"  主播：{record['pilot_nickname']} ({record['pilot_real_name']})")
                print(f"  结算方式：{record['settlement_type']}")
                print(f"  申请金额：{record['base_salary_amount']}元")
                print(f"  开播时间：{record['start_time_utc']}")
                print()

            if len(valid_records) > 10:
                print(f"  ... 还有{len(valid_records) - 10}条记录")

    def create_applications(self, valid_records: List[Dict]) -> List[str]:
        """创建底薪申请记录"""
        created_ids = []

        try:
            operator_user = User.objects.get(id=self.operator_user_id)  # pylint: disable=no-member
        except Exception as exc:
            raise RuntimeError(f"未找到操作人用户：{self.operator_user_id}") from exc

        for record in valid_records:
            try:
                # 创建底薪申请记录
                application = BaseSalaryApplication(
                    pilot_id=record['pilot'],
                    battle_record_id=record['battle_record'],
                    settlement_type=record['settlement_type'],
                    base_salary_amount=record['base_salary_amount'],
                    applicant_id=operator_user,
                    status=BaseSalaryApplicationStatus.APPROVED,  # 直接设为已发放
                    created_at=record['start_time_utc'],  # 使用开播时间
                    updated_at=record['start_time_utc'],
                )

                application.save()
                created_ids.append(str(application.pk))

                # 创建变更日志
                change_log = BaseSalaryApplicationChangeLog(
                    application_id=application,
                    user_id=operator_user,
                    field_name='status',
                    old_value='',
                    new_value=BaseSalaryApplicationStatus.APPROVED.value,
                    remark='从CSV导入，直接设为已发放',
                    change_time=record['start_time_utc'],
                )
                change_log.save()

                print(f"✓ 创建底薪申请记录：{str(application.pk)} (开播记录：{record['battle_record_id']})")

            except Exception as e:
                print(f"✗ 创建底薪申请记录失败 (开播记录：{record['battle_record_id']})：{e}")
                continue

        return created_ids

    def import_from_csv(self, csv_path: Path) -> None:
        """从CSV文件导入底薪申请记录"""
        print(f"开始处理CSV文件：{csv_path}")

        # 解析CSV文件
        records = self.parse_csv_file(csv_path)
        print(f"解析完成，共找到{len(records)}条需要处理的记录")

        if not records:
            print("没有找到需要处理的记录")
            return

        # 验证记录
        valid_records, invalid_records = self.validate_records(records)

        # 显示预览
        self.preview_import(valid_records, invalid_records)

        if not valid_records:
            print("\n没有有效的记录可以导入")
            return

        # 用户确认
        print("\n" + "=" * 80)
        try:
            confirm = input("是否确认创建以上底薪申请记录？(y/N): ").strip().lower()
        except EOFError:
            print("\n检测到非交互式环境，跳过用户确认，直接执行导入...")
            confirm = 'y'

        if confirm != 'y':
            print("用户取消操作")
            return

        # 创建记录
        print("\n开始创建底薪申请记录...")
        created_ids = self.create_applications(valid_records)

        print("\n导入完成！")
        print(f"成功创建：{len(created_ids)}条底薪申请记录")
        print(f"失败：{len(valid_records) - len(created_ids)}条")


def main():
    """主函数"""
    if len(sys.argv) != 2:
        print("用法：python scripts/import_base_salary_applications.py <csv_file_path>")
        sys.exit(1)

    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"错误：CSV文件不存在：{csv_path}")
        sys.exit(1)

    # 加载环境变量并创建应用
    load_dotenv()
    app = create_app()

    # 登录默认用户
    with app.app_context():
        try:
            user = User.objects(username='zala').first()  # pylint: disable=no-member
            if user is None:
                raise RuntimeError('未找到默认管理员用户 zala')

            # 执行导入
            importer = BaseSalaryApplicationImporter(app)
            with app.test_request_context():
                login_user(user)
                try:
                    importer.import_from_csv(csv_path)
                except Exception as e:
                    print(f"导入失败：{e}")
                    sys.exit(1)
        except Exception as e:
            print(f"登录失败：{e}")
            sys.exit(1)


if __name__ == '__main__':
    main()
