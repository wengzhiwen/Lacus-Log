#!/usr/bin/env python3
"""清空底薪申请记录脚本

清空数据库中的底薪申请记录（base_salary_applications表），不影响其他表。
这是一个危险操作，需要用户确认。

运行：
  PYTHONPATH=. venv/bin/python scripts/clear_base_salary_applications.py
  PYTHONPATH=. venv/bin/python scripts/clear_base_salary_applications.py --force  # 跳过确认直接删除
"""

# pylint: disable=no-member
import sys
from dotenv import load_dotenv

from app import create_app
from models.battle_record import BaseSalaryApplication


def clear_base_salary_applications(force=False):
    """清空所有底薪申请记录"""
    # 先查询当前记录数量
    total_count = BaseSalaryApplication.objects.count()
    print(f"当前底薪申请记录总数：{total_count}")

    if total_count == 0:
        print("✅ 底薪申请记录表已经是空的，无需清空")
        return

    # 显示前几条记录作为确认
    print("\n前5条记录预览：")
    sample_records = BaseSalaryApplication.objects.limit(5)
    for i, record in enumerate(sample_records, 1):
        pilot_name = record.pilot_id.nickname if record.pilot_id else "未知主播"
        print(f"  {i}. ID: {record.pk}, 主播: {pilot_name}, 状态: {record.status_display}, 金额: {record.base_salary_amount}")

    # 用户确认
    if not force:
        print(f"\n⚠️  警告：即将删除 {total_count} 条底薪申请记录！")
        print("此操作不可逆，请确认是否继续？")

        confirm = input("请输入 'YES' 确认删除（区分大小写）: ")

        if confirm != 'YES':
            print("❌ 操作已取消")
            return
    else:
        print(f"\n⚠️  强制模式：即将删除 {total_count} 条底薪申请记录！")

    # 执行删除
    print("\n正在删除底薪申请记录...")
    deleted_count = BaseSalaryApplication.objects.delete()

    print(f"✅ 删除完成！共删除 {deleted_count} 条记录")

    # 验证删除结果
    remaining_count = BaseSalaryApplication.objects.count()
    print(f"剩余记录数：{remaining_count}")


def main():
    """主函数"""
    load_dotenv()
    app = create_app()

    # 检查命令行参数
    force = '--force' in sys.argv

    with app.app_context():
        try:
            clear_base_salary_applications(force=force)
        except Exception as e:
            print(f"\n❌ 操作失败：{e}")
            raise


if __name__ == '__main__':
    main()
