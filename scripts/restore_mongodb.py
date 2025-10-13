"""MongoDB数据库恢复脚本

使用mongorestore工具从备份文件恢复lacus数据库，支持：
- 从压缩备份文件恢复
- 备份文件验证
- 恢复前确认
- 详细日志记录

运行：
  PYTHONPATH=. venv/bin/python scripts/restore_mongodb.py backups/lacus_backup_20250101_120000.tar.gz
  PYTHONPATH=. venv/bin/python scripts/restore_mongodb.py backups/lacus_backup_20250101_120000 --force
"""

import argparse
import gzip
import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def setup_logging() -> logging.Logger:
    """设置日志记录"""
    log_dir = Path('log')
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger('mongodb_restore')
    logger.setLevel(logging.INFO)

    # 避免重复添加handler
    if not logger.handlers:
        # 文件handler
        log_file = log_dir / f'mongodb_restore_{datetime.now().strftime("%Y%m%d")}.log'
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setLevel(logging.INFO)

        # 控制台handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # 格式化
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger


def check_mongorestore() -> bool:
    """检查mongorestore工具是否可用"""
    try:
        result = subprocess.run(['mongorestore', '--version'], capture_output=True, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_mongodb_uri() -> str:
    """从环境变量获取MongoDB连接URI"""
    load_dotenv()
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/lacus')

    # 确保URI包含数据库名
    if not mongodb_uri.endswith('/lacus'):
        if mongodb_uri.endswith('/'):
            mongodb_uri += 'lacus'
        else:
            mongodb_uri += '/lacus'

    return mongodb_uri


def parse_mongodb_uri(uri: str) -> tuple[str, str, str, str]:
    """解析MongoDB URI，返回host, port, database, auth_info"""
    # 简单解析mongodb://[username:password@]host[:port]/database格式
    if not uri.startswith('mongodb://'):
        raise ValueError(f"无效的MongoDB URI格式: {uri}")

    # 移除mongodb://前缀
    uri = uri[10:]

    # 分离认证信息和主机信息
    if '@' in uri:
        auth_part, host_part = uri.split('@', 1)
        if ':' in auth_part:
            username, password = auth_part.split(':', 1)
        else:
            username, password = auth_part, ''
    else:
        username, password = '', ''
        host_part = uri

    # 分离主机和数据库
    if '/' in host_part:
        host_port, database = host_part.split('/', 1)
    else:
        host_port, database = host_part, 'lacus'

    # 分离主机和端口
    if ':' in host_port:
        host, port = host_port.split(':', 1)
    else:
        host, port = host_port, '27017'

    return host, port, database, f"{username}:{password}" if username else ""


def extract_backup(backup_path: Path, logger: logging.Logger) -> Optional[Path]:
    """解压备份文件"""
    if backup_path.suffix == '.gz':
        logger.info(f"解压备份文件: {backup_path}")

        # 创建临时目录
        temp_dir = Path(tempfile.mkdtemp(prefix='mongodb_restore_'))

        try:
            # 解压tar.gz文件
            cmd = ['tar', '-xzf', str(backup_path), '-C', str(temp_dir)]
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

            # 查找解压后的目录
            extracted_dirs = [d for d in temp_dir.iterdir() if d.is_dir()]
            if extracted_dirs:
                extracted_path = extracted_dirs[0]
                logger.info(f"解压完成: {extracted_path}")
                return extracted_path
            else:
                logger.error("解压后未找到备份目录")
                return None

        except subprocess.CalledProcessError as e:
            logger.error(f"解压失败: {e}")
            logger.error(f"错误输出: {e.stderr}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None
    else:
        # 直接使用目录
        if backup_path.is_dir():
            return backup_path
        else:
            logger.error(f"备份路径不是有效目录: {backup_path}")
            return None


def verify_backup_content(backup_path: Path, logger: logging.Logger) -> bool:
    """验证备份内容"""
    logger.info(f"验证备份内容: {backup_path}")

    try:
        # 检查是否包含lacus数据库目录
        lacus_dir = backup_path / 'lacus'
        if not lacus_dir.exists() or not lacus_dir.is_dir():
            logger.error("备份中未找到lacus数据库目录")
            return False

        # 检查是否包含集合文件
        bson_files = list(lacus_dir.glob('*.bson'))
        if not bson_files:
            logger.error("备份中未找到任何集合文件")
            return False

        logger.info(f"备份验证通过，包含 {len(bson_files)} 个集合")
        for bson_file in bson_files:
            logger.debug(f"  - {bson_file.name}")

        return True

    except Exception as e:
        logger.error(f"备份内容验证失败: {e}")
        return False


def restore_database(backup_path: Path, logger: logging.Logger, drop_existing: bool = False) -> bool:
    """恢复数据库"""
    mongodb_uri = get_mongodb_uri()
    host, port, database, auth_info = parse_mongodb_uri(mongodb_uri)

    logger.info(f"开始恢复数据库: {database}")
    logger.info(f"备份源: {backup_path}")

    # 构建mongorestore命令
    cmd = ['mongorestore']

    # 添加认证信息
    if auth_info:
        username, password = auth_info.split(':', 1)
        cmd.extend(['--username', username])
        if password:
            cmd.extend(['--password', password])

    # 添加连接信息
    cmd.extend(['--host', f"{host}:{port}"])
    cmd.extend(['--db', database])

    # 添加其他选项
    if drop_existing:
        cmd.append('--drop')

    # 添加备份路径
    cmd.append(str(backup_path))

    try:
        logger.info(f"执行命令: {' '.join(cmd[:2])} [认证信息已隐藏] {' '.join(cmd[4:])}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        logger.info("恢复命令执行成功")
        logger.debug(f"命令输出: {result.stdout}")

        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"恢复失败: {e}")
        logger.error(f"错误输出: {e.stderr}")
        return False


def confirm_restore(logger: logging.Logger) -> bool:
    """确认恢复操作"""
    logger.warning("=" * 60)
    logger.warning("警告：此操作将覆盖现有数据库！")
    logger.warning("请确保您已经备份了当前数据库。")
    logger.warning("=" * 60)

    while True:
        response = input("确认要继续恢复吗？(yes/no): ").strip().lower()
        if response in ['yes', 'y']:
            return True
        elif response in ['no', 'n']:
            return False
        else:
            print("请输入 'yes' 或 'no'")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='MongoDB数据库恢复脚本')
    parser.add_argument('backup_path', help='备份文件或目录路径')
    parser.add_argument('--force', '-f', action='store_true', help='跳过确认提示')
    parser.add_argument('--drop', action='store_true', help='恢复前删除现有数据库')

    args = parser.parse_args()

    # 设置日志
    logger = setup_logging()

    logger.info("=" * 50)
    logger.info("MongoDB恢复脚本启动")
    logger.info(f"备份路径: {args.backup_path}")
    logger.info(f"强制模式: {args.force}")
    logger.info(f"删除现有: {args.drop}")

    # 检查mongorestore工具
    if not check_mongorestore():
        logger.error("mongorestore工具未找到，请确保MongoDB工具已安装")
        sys.exit(1)

    # 检查备份文件
    backup_path = Path(args.backup_path)
    if not backup_path.exists():
        logger.error(f"备份文件不存在: {backup_path}")
        sys.exit(1)

    try:
        # 确认操作
        if not args.force and not confirm_restore(logger):
            logger.info("用户取消恢复操作")
            sys.exit(0)

        # 解压备份文件（如果需要）
        extracted_path = extract_backup(backup_path, logger)
        if not extracted_path:
            logger.error("备份文件解压失败")
            sys.exit(1)

        # 验证备份内容
        if not verify_backup_content(extracted_path, logger):
            logger.error("备份内容验证失败")
            sys.exit(1)

        # 恢复数据库
        if not restore_database(extracted_path, logger, args.drop):
            logger.error("数据库恢复失败")
            sys.exit(1)

        logger.info("数据库恢复完成")

        # 清理临时文件
        if extracted_path.parent.name.startswith('mongodb_restore_'):
            shutil.rmtree(extracted_path.parent, ignore_errors=True)
            logger.info("临时文件已清理")

    except Exception as e:
        logger.error(f"恢复过程中发生错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    from datetime import datetime
    main()

