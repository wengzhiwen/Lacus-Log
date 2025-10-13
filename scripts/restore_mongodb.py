"""MongoDB数据库恢复脚本

使用mongorestore工具从备份文件恢复lacus数据库，支持：
- 强制要求通过CLI指定备份文件
- 备份文件可用性检查
- 防呆确认机制
- 详细日志记录
- 恢复后密码重置功能

运行：
  PYTHONPATH=. venv/bin/python scripts/restore_mongodb.py /path/to/backup.tar.gz
  PYTHONPATH=. venv/bin/python scripts/restore_mongodb.py /path/to/backup.tar.gz --drop
  PYTHONPATH=. venv/bin/python scripts/restore_mongodb.py /path/to/backup.tar.gz --resetpassword
  PYTHONPATH=. venv/bin/python scripts/restore_mongodb.py --resetpassword
"""

import argparse
import gzip
import logging
import os
import random
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
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
        subprocess.run(['mongorestore', '--version'], capture_output=True, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def get_mongodb_uri() -> str:
    """从环境变量获取MongoDB连接URI"""
    load_dotenv()
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/lacus')

    return mongodb_uri


def get_database_name(mongodb_uri: str) -> str:
    """从MongoDB URI中提取数据库名称"""
    if '/' in mongodb_uri:
        # 获取最后一个斜杠后的部分作为数据库名
        database_name = mongodb_uri.split('/')[-1]
        # 如果数据库名为空，使用默认值
        if database_name:
            return database_name
    raise ValueError(f"无效的MongoDB URI格式: {mongodb_uri}")


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
            subprocess.run(cmd, capture_output=True, text=True, check=True)

            # 查找解压后的目录
            extracted_dirs = [d for d in temp_dir.iterdir() if d.is_dir()]
            if extracted_dirs:
                extracted_path = extracted_dirs[0]
                logger.info(f"解压完成: {extracted_path}")
                return extracted_path

            logger.error("解压后未找到备份目录")
            return None

        except subprocess.CalledProcessError as e:
            logger.error(f"解压失败: {e}")
            logger.error(f"错误输出: {e.stderr}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

    # 直接使用目录
    if backup_path.is_dir():
        return backup_path

    logger.error(f"备份路径不是有效目录: {backup_path}")
    return None


def verify_backup_content(backup_path: Path, logger: logging.Logger) -> bool:
    """验证备份内容"""
    logger.info(f"验证备份内容: {backup_path}")

    try:
        # backup_path中应该只有一个目录
        backup_dirs = [d for d in backup_path.iterdir() if d.is_dir()]
        if len(backup_dirs) != 1:
            logger.error(f"备份中应该只有一个目录: {backup_path}")
            return False

        # 这个目录就是备份目录
        database_dir = backup_dirs[0]
        logger.info(f"备份中找到目录: {database_dir.name}")

        # 检查是否包含集合文件
        bson_files = list(database_dir.glob('*.bson'))
        if not bson_files:
            logger.error(f"备份中未找到任何集合文件 (目录: {database_dir.name})")
            return False

        logger.info(f"备份验证通过，包含 {len(bson_files)} 个集合 (目录: {database_dir.name})")
        for bson_file in bson_files:
            logger.debug(f"  - {bson_file.name}")

        return True

    except Exception as e:
        logger.error(f"备份内容验证失败: {e}")
        return False


def reset_all_passwords(logger: logging.Logger) -> bool:
    """重置所有用户密码为123456（使用当前环境的加密配置）"""
    logger.info("开始重置所有用户密码...")

    try:
        # 设置Python路径以便导入项目模块
        project_root = Path(__file__).parent.parent
        sys.path.insert(0, str(project_root))

        # 导入Flask应用和用户模型
        from app import create_app
        from models.user import User
        from flask_security.utils import hash_password

        # 创建Flask应用上下文
        app = create_app()

        with app.app_context():
            # 获取所有用户
            users = User.objects()
            user_count = users.count()

            if user_count == 0:
                logger.warning("数据库中没有找到任何用户")
                return True

            logger.info(f"找到 {user_count} 个用户，开始重置密码...")

            reset_count = 0
            for user in users:
                try:
                    # 使用Flask-Security的密码哈希函数
                    new_password = "123456"
                    user.password = hash_password(new_password)
                    user.save()
                    reset_count += 1
                    logger.info(f"已重置用户 '{user.username}' 的密码")
                except Exception as e:
                    logger.error(f"重置用户 '{user.username}' 密码失败: {e}")

            logger.info(f"密码重置完成，成功重置 {reset_count}/{user_count} 个用户的密码")
            return reset_count == user_count

    except Exception as e:
        logger.error(f"重置密码过程中发生错误: {e}")
        return False


def restore_database(backup_path: Path, logger: logging.Logger, drop_existing: bool = False) -> bool:
    """恢复数据库"""
    mongodb_uri = get_mongodb_uri()
    host, port, database, auth_info = parse_mongodb_uri(mongodb_uri)

    logger.info(f"开始恢复数据库: {database}")
    logger.info(f"备份源: {backup_path}")

    # 找到备份目录
    backup_dirs = [d for d in backup_path.iterdir() if d.is_dir()]
    if not backup_dirs:
        logger.error("备份路径中未找到数据库目录")
        return False

    source_db_dir = backup_dirs[0]
    source_db_name = source_db_dir.name

    logger.info(f"备份数据库名: {source_db_name}")
    logger.info(f"目标数据库名: {database}")

    if source_db_name != database:
        logger.info("数据库名不匹配，将进行跨数据库恢复")

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

    # 添加备份路径 - 指向具体的数据库目录而不是父目录
    cmd.append(str(source_db_dir))

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


def generate_random_confirmation_code(length: int = 6) -> str:
    """生成无意义的随机字母组合"""
    return ''.join(random.choices('abcdefghijklmnopqrstuvwxyz', k=length))


def verify_backup_file_integrity(backup_path: Path, logger: logging.Logger) -> bool:
    """深度验证备份文件的完整性"""
    logger.info(f"开始深度验证备份文件: {backup_path}")

    try:
        # 如果是压缩文件，检查文件头
        if backup_path.suffix == '.gz':
            with gzip.open(backup_path, 'rb') as f:
                # 读取文件头验证是否为有效的gzip文件
                header = f.read(10)
                if len(header) < 10:
                    logger.error("备份文件头无效，文件可能损坏")
                    return False
                logger.info("GZIP文件头验证通过")

        # 尝试解压并验证内容结构
        extracted_path = extract_backup(backup_path, logger)
        if not extracted_path:
            logger.error("备份文件解压验证失败")
            return False

        # 验证备份内容
        if not verify_backup_content(extracted_path, logger):
            logger.error("备份内容验证失败")
            return False

        # 备份目录中应该只有一个目录
        backup_dirs = [d for d in extracted_path.iterdir() if d.is_dir()]
        if len(backup_dirs) != 1:
            logger.error(f"备份中应该只有一个目录: {extracted_path}")
            return False

        database_dir = backup_dirs[0]

        critical_collections = ['users.bson', 'pilots.bson', 'announcements.bson']
        missing_collections = []

        logger.info(f"检查备份目录（{database_dir.name}）中的关键集合...")

        for collection in critical_collections:
            if not (database_dir / collection).exists():
                missing_collections.append(collection)

        if missing_collections:
            logger.warning(f"备份文件缺少关键集合: {missing_collections}")
            logger.warning("这可能是不完整的备份，请谨慎操作")

        logger.info(f"备份文件完整性验证通过 (目录: {database_dir.name})")
        return True

    except Exception as e:
        logger.error(f"备份文件完整性验证失败: {e}")
        return False


def confirm_restore_with_code(backup_path: Path, mongodb_uri: str, logger: logging.Logger) -> bool:
    """带防呆确认码的恢复确认"""
    # 显示详细的操作信息
    logger.warning("=" * 80)
    logger.warning("⚠️  警告：此操作将覆盖现有数据库！")
    logger.warning("=" * 80)
    print(f"📍 备份文件路径: {backup_path}")
    print(f"🎯 目标数据库: {mongodb_uri}")
    print(f"📅 当前时间: {logger.handlers[0].formatter.formatTime(logging.LogRecord('', 0, '', 0, '', (), None))}")
    print()

    # 验证备份文件
    print("🔍 正在验证备份文件...")
    if not verify_backup_file_integrity(backup_path, logger):
        print("❌ 备份文件验证失败，不能继续恢复操作")
        return False
    print("✅ 备份文件验证通过")
    print()

    # 显示关键风险提示
    print("🚨 风险提示:")
    print("   • 此操作不可撤销")
    print("   • 现有数据库数据将永久丢失")
    print("   • 建议先备份当前数据库")
    print()

    # 生成并显示确认码
    confirmation_code = generate_random_confirmation_code(random.randint(6, 8))
    print(f"🔐 请输入以下确认码以继续操作: {confirmation_code}")
    print("   (这是6-8个随机字母组合，用于防止误操作)")
    print()

    # 要求用户输入确认码
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            user_input = input(f"请输入确认码 (尝试 {attempt + 1}/{max_attempts}): ").strip().lower()
            if user_input == confirmation_code:
                print("✅ 确认码正确，准备开始恢复...")
                return True

            if attempt < max_attempts - 1:
                print("❌ 确认码错误，请重新输入")
            else:
                print("❌ 确认码错误次数过多，操作已取消")

        except KeyboardInterrupt:
            print("\n\n⚠️  操作被用户中断")
            return False

    print("❌ 防呆验证失败，恢复操作已取消")
    return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='MongoDB数据库恢复脚本 - 带防呆确认机制',
                                     formatter_class=argparse.RawDescriptionHelpFormatter,
                                     epilog="""
使用示例:
  %(prog)s /path/to/backup.tar.gz                    # 标准恢复
  %(prog)s /path/to/backup.tar.gz --drop             # 删除现有数据库后恢复
  %(prog)s /path/to/backup.tar.gz --resetpassword   # 恢复后重置所有用户密码为123456
  %(prog)s --resetpassword                          # 仅重置密码（不恢复数据）

注意:
  • 必须通过命令行参数指定备份文件路径（除非仅重置密码）
  • 脚本会自动验证备份文件完整性
  • 需要输入随机确认码才能执行恢复操作
  • --resetpassword 会将所有用户密码重置为 123456（使用当前环境加密配置）
        """)
    parser.add_argument('backup_path', nargs='?', help='备份文件路径（恢复数据时必需，仅重置密码时可省略）')
    parser.add_argument('--drop', action='store_true', help='恢复前删除现有数据库')
    parser.add_argument('--resetpassword', action='store_true', help='恢复后重置所有用户密码为123456')

    args = parser.parse_args()

    # 检查参数组合
    if not args.backup_path and not args.resetpassword:
        parser.error("必须指定备份文件路径或使用 --resetpassword 选项")

    if args.backup_path and not Path(args.backup_path).exists():
        parser.error(f"备份文件不存在: {args.backup_path}")

    # 设置日志
    logger = setup_logging()

    logger.info("=" * 50)
    if args.resetpassword and not args.backup_path:
        logger.info("MongoDB密码重置脚本启动")
        logger.info("操作: 仅重置密码")
    else:
        logger.info("MongoDB恢复脚本启动 (带防呆确认)")
        logger.info(f"备份路径: {args.backup_path}")
        logger.info(f"删除现有: {args.drop}")
        if args.resetpassword:
            logger.info("恢复后将重置所有用户密码")

    # 获取MongoDB连接信息
    mongodb_uri = get_mongodb_uri()

    # 如果仅重置密码，直接执行
    if args.resetpassword and not args.backup_path:
        logger.info("=" * 50)
        logger.warning("⚠️  警告：此操作将重置所有用户密码为 123456！")
        logger.warning("=" * 50)
        print(f"🎯 目标数据库: {mongodb_uri}")
        print(f"📅 当前时间: {logger.handlers[0].formatter.formatTime(logging.LogRecord('', 0, '', 0, '', (), None))}")
        print()

        # 显示关键风险提示
        print("🚨 风险提示:")
        print("   • 此操作不可撤销")
        print("   • 所有用户密码将被重置为 123456")
        print("   • 用户需要使用新密码重新登录")
        print()

        # 生成并显示确认码
        confirmation_code = generate_random_confirmation_code(random.randint(6, 8))
        print(f"🔐 请输入以下确认码以继续操作: {confirmation_code}")
        print("   (这是6-8个随机字母组合，用于防止误操作)")
        print()

        # 要求用户输入确认码
        max_attempts = 3
        for attempt in range(max_attempts):
            try:
                user_input = input(f"请输入确认码 (尝试 {attempt + 1}/{max_attempts}): ").strip().lower()
                if user_input == confirmation_code:
                    print("✅ 确认码正确，准备开始重置密码...")
                    print("\n🚀 开始执行密码重置操作...")
                    print("-" * 50)

                    if reset_all_passwords(logger):
                        print("-" * 50)
                        logger.info("✅ 所有用户密码重置完成")
                    else:
                        print("-" * 50)
                        logger.error("❌ 密码重置失败")
                        sys.exit(1)
                    return

                if attempt < max_attempts - 1:
                    print("❌ 确认码错误，请重新输入")
                else:
                    print("❌ 确认码错误次数过多，操作已取消")

            except KeyboardInterrupt:
                print("\n\n⚠️  操作被用户中断")
                return

        print("❌ 防呆验证失败，密码重置操作已取消")
        return

    # 以下是恢复数据库的逻辑
    # 检查mongorestore工具
    if not check_mongorestore():
        logger.error("mongorestore工具未找到，请确保MongoDB工具已安装")
        sys.exit(1)

    # 检查备份文件
    backup_path = Path(args.backup_path)

    try:
        # 执行防呆确认
        if not confirm_restore_with_code(backup_path, mongodb_uri, logger):
            logger.info("用户取消恢复操作或确认失败")
            sys.exit(0)

        print("\n🚀 开始执行恢复操作...")
        print("-" * 50)

        # 解压备份文件（如果需要）
        extracted_path = extract_backup(backup_path, logger)
        if not extracted_path:
            logger.error("备份文件解压失败")
            sys.exit(1)

        # 再次验证备份内容（双重保险）
        if not verify_backup_content(extracted_path, logger):
            logger.error("备份内容验证失败")
            sys.exit(1)

        # 恢复数据库
        if not restore_database(extracted_path, logger, args.drop):
            logger.error("数据库恢复失败")
            sys.exit(1)

        print("-" * 50)
        logger.info("✅ 数据库恢复完成")

        # 如果需要重置密码
        if args.resetpassword:
            logger.info("开始重置所有用户密码...")
            print("🔄 开始重置用户密码...")

            if reset_all_passwords(logger):
                logger.info("✅ 密码重置完成")
                print("✅ 所有用户密码已重置为 123456")
            else:
                logger.error("❌ 密码重置失败")
                print("❌ 密码重置失败，请检查日志")

        # 清理临时文件
        if extracted_path.parent.name.startswith('mongodb_restore_'):
            shutil.rmtree(extracted_path.parent, ignore_errors=True)
            logger.info("🧹 临时文件已清理")

    except KeyboardInterrupt:
        print("\n\n⚠️  恢复操作被用户中断")
        logger.info("用户中断恢复操作")
        sys.exit(130)  # 标准的键盘中断退出码
    except Exception as e:
        logger.error(f"恢复过程中发生错误: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
