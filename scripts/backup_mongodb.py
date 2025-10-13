"""MongoDB数据库备份脚本

使用mongodump工具对lacus数据库进行完整备份，支持：
- 全库备份
- 备份文件压缩
- 自动清理过期备份
- 备份验证
- 详细日志记录

运行：
  PYTHONPATH=. venv/bin/python scripts/backup_mongodb.py
  PYTHONPATH=. venv/bin/python scripts/backup_mongodb.py --keep-days 7
  PYTHONPATH=. venv/bin/python scripts/backup_mongodb.py --output-dir /path/to/backup
"""

import argparse
import gzip
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv


def setup_logging() -> logging.Logger:
    """设置日志记录"""
    log_dir = Path('log')
    log_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger('mongodb_backup')
    logger.setLevel(logging.INFO)

    # 避免重复添加handler
    if not logger.handlers:
        # 文件handler
        log_file = log_dir / f'mongodb_backup_{datetime.now().strftime("%Y%m%d")}.log'
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


def check_mongodump() -> bool:
    """检查mongodump工具是否可用"""
    try:
        _ = subprocess.run(['mongodump', '--version'], capture_output=True, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_mongodb_uri() -> str:
    """从环境变量获取MongoDB连接URI"""
    load_dotenv()
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/lacus')

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


def create_backup(backup_dir: Path, logger: logging.Logger) -> Optional[Path]:
    """创建MongoDB备份"""
    mongodb_uri = get_mongodb_uri()
    host, port, database, auth_info = parse_mongodb_uri(mongodb_uri)

    # 创建备份目录
    backup_dir.mkdir(parents=True, exist_ok=True)

    # 生成备份文件名（包含时间戳）
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_name = f"lacus_backup_{timestamp}"
    backup_path = backup_dir / backup_name

    logger.info(f"开始备份数据库: {database}")
    logger.info(f"备份目标: {backup_path}")

    # 构建mongodump命令
    cmd = ['mongodump']

    # 添加认证信息
    if auth_info:
        username, password = auth_info.split(':', 1)
        cmd.extend(['--username', username])
        if password:
            cmd.extend(['--password', password])

    # 添加连接信息
    cmd.extend(['--host', f"{host}:{port}"])
    cmd.extend(['--db', database])
    cmd.extend(['--out', str(backup_path)])

    try:
        logger.info(f"执行命令: {' '.join(cmd[:2])} [认证信息已隐藏] {' '.join(cmd[4:])}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)

        logger.info("备份命令执行成功")
        logger.debug(f"命令输出: {result.stdout}")

        # 检查备份文件是否生成
        if backup_path.exists() and (backup_path / database).exists():
            logger.info(f"备份完成: {backup_path}")
            return backup_path
        else:
            logger.error(f"备份文件未生成: {backup_path}")
            return None

    except subprocess.CalledProcessError as e:
        logger.error(f"备份失败: {e}")
        logger.error(f"错误输出: {e.stderr}")
        return None


def compress_backup(backup_path: Path, logger: logging.Logger) -> Optional[Path]:
    """压缩备份文件"""
    logger.info(f"开始压缩备份: {backup_path}")

    compressed_path = backup_path.with_suffix('.tar.gz')

    try:
        # 使用tar命令压缩
        cmd = ['tar', '-czf', str(compressed_path), '-C', str(backup_path.parent), backup_path.name]
        _ = subprocess.run(cmd, capture_output=True, text=True, check=True)

        # 删除原始备份目录
        shutil.rmtree(backup_path)

        logger.info(f"压缩完成: {compressed_path}")
        logger.info(f"压缩文件大小: {compressed_path.stat().st_size / 1024 / 1024:.2f} MB")

        return compressed_path

    except subprocess.CalledProcessError as e:
        logger.error(f"压缩失败: {e}")
        logger.error(f"错误输出: {e.stderr}")
        return None


def verify_backup(backup_path: Path, logger: logging.Logger) -> bool:
    """验证备份文件"""
    logger.info(f"验证备份文件: {backup_path}")

    try:
        if backup_path.suffix == '.gz':
            # 压缩文件验证
            with gzip.open(backup_path, 'rb') as f:
                # 尝试读取文件头
                header = f.read(1024)
                if len(header) > 0:
                    logger.info("压缩文件验证通过")
                    return True
                else:
                    logger.error("压缩文件为空")
                    return False
        else:
            # 目录验证
            if backup_path.is_dir():
                # 检查是否包含数据库目录
                db_dirs = [d for d in backup_path.iterdir() if d.is_dir()]
                if db_dirs:
                    logger.info(f"备份目录验证通过，包含 {len(db_dirs)} 个数据库")
                    return True
                else:
                    logger.error("备份目录为空")
                    return False
            else:
                logger.error("备份路径不是有效目录")
                return False

    except Exception as e:
        logger.error(f"备份验证失败: {e}")
        return False


def cleanup_old_backups(backup_dir: Path, keep_days: int, logger: logging.Logger) -> None:
    """清理过期备份文件"""
    logger.info(f"清理 {keep_days} 天前的备份文件")

    cutoff_date = datetime.now() - timedelta(days=keep_days)
    deleted_count = 0

    try:
        for backup_file in backup_dir.glob('lacus_backup_*'):
            if backup_file.is_file() or backup_file.is_dir():
                # 从文件名提取时间戳
                try:
                    timestamp_str = backup_file.name.replace('lacus_backup_', '').replace('.tar.gz', '')
                    file_date = datetime.strptime(timestamp_str, '%Y%m%d_%H%M%S')

                    if file_date < cutoff_date:
                        if backup_file.is_dir():
                            shutil.rmtree(backup_file)
                        else:
                            backup_file.unlink()
                        deleted_count += 1
                        logger.info(f"删除过期备份: {backup_file.name}")

                except ValueError:
                    # 文件名格式不匹配，跳过
                    continue

        logger.info(f"清理完成，删除了 {deleted_count} 个过期备份文件")

    except Exception as e:
        logger.error(f"清理备份文件时出错: {e}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='MongoDB数据库备份脚本')
    parser.add_argument('--output-dir', '-o', default='backups', help='备份输出目录 (默认: backups)')
    parser.add_argument('--keep-days', '-k', type=int, default=30, help='保留备份文件的天数 (默认: 30)')
    parser.add_argument('--no-compress', action='store_true', help='不压缩备份文件')
    parser.add_argument('--no-cleanup', action='store_true', help='不清理过期备份文件')

    args = parser.parse_args()

    # 设置日志
    logger = setup_logging()

    logger.info("=" * 50)
    logger.info("MongoDB备份脚本启动")
    logger.info(f"备份目录: {args.output_dir}")
    logger.info(f"保留天数: {args.keep_days}")
    logger.info(f"压缩备份: {not args.no_compress}")
    logger.info(f"清理过期: {not args.no_cleanup}")

    # 检查mongodump工具
    if not check_mongodump():
        logger.error("mongodump工具未找到，请确保MongoDB工具已安装")
        sys.exit(1)

    # 创建备份目录
    backup_dir = Path(args.output_dir)

    try:
        # 创建备份
        backup_path = create_backup(backup_dir, logger)
        if not backup_path:
            logger.error("备份创建失败")
            sys.exit(1)

        # 验证备份
        if not verify_backup(backup_path, logger):
            logger.error("备份验证失败")
            sys.exit(1)

        # 压缩备份（如果需要）
        if not args.no_compress:
            compressed_path = compress_backup(backup_path, logger)
            if compressed_path:
                backup_path = compressed_path
            else:
                logger.warning("压缩失败，保留未压缩的备份")

        # 清理过期备份
        if not args.no_cleanup:
            cleanup_old_backups(backup_dir, args.keep_days, logger)

        logger.info("备份任务完成")
        logger.info(f"最终备份文件: {backup_path}")

    except Exception as e:
        logger.error(f"备份过程中发生错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
