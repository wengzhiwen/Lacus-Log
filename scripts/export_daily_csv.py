"""离线导出日报CSV脚本

使用应用工厂创建应用，在测试请求上下文中登录默认议长(zala)，
直接调用路由函数导出指定日期的CSV到本地 log/ 目录。

运行：
  PYTHONPATH=. venv/bin/python scripts/export_daily_csv.py 2025-09-26 2025-09-28
无参数时默认导出 2025-09-26 与 2025-09-28。
"""

# pylint: disable=no-member

import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask
from flask_security.utils import login_user

from app import create_app
from models.user import User
from routes.report import export_daily_csv


def export_for_date(app: Flask, date_str: str) -> Path:
    out_dir = Path('log')
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f'daily_report_{date_str.replace("-", "")}.csv'

    user = User.objects(username='zala').first()
    if user is None:
        raise RuntimeError('未找到默认议长用户 zala，无法导出')

    with app.test_request_context(f'/reports/daily/export.csv?date={date_str}'):
        login_user(user)
        resp = export_daily_csv()
        data = resp.get_data()
        out_path.write_bytes(data)
        return out_path


def main():
    load_dotenv()
    app = create_app()

    dates = sys.argv[1:] if len(sys.argv) > 1 else ['2025-09-26', '2025-09-28']
    for d in dates:
        out = export_for_date(app, d)
        print(f'导出完成: {out} ({out.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
