#!/usr/bin/env python3
"""
简化测试运行脚本 - 只运行不需要数据库的测试
"""
import subprocess
import sys


def run_command(cmd, description):
    """运行命令并显示结果"""
    print(f"\n{'='*50}")
    print(f"运行: {description}")
    print(f"命令: {cmd}")
    print(f"{'='*50}")

    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, check=False)

    if result.stdout:
        print("输出:")
        print(result.stdout)

    if result.stderr:
        print("错误:")
        print(result.stderr)

    print(f"返回码: {result.returncode}")
    return result.returncode == 0


def main():
    """主函数"""
    print("Lacus-Log 简化测试套件")
    print("=" * 50)
    print("注意: 此脚本只运行不需要数据库连接的测试")

    # 检查是否在虚拟环境中
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and
                                                sys.base_prefix != sys.prefix):
        print("警告: 建议在虚拟环境中运行测试")

    # 运行基础测试（不需要数据库）
    if not run_command(
            "./venv/bin/pytest tests/unit/test_imports.py tests/unit/test_logging.py -v",
            "运行基础测试"):
        print("❌ 基础测试失败")
        return 1

    # 运行用户模型测试（不需要数据库的部分）
    test_cmd = (
        "./venv/bin/pytest "
        "tests/unit/test_models.py::TestUserModel::test_role_creation "
        "tests/unit/test_models.py::TestUserModel::test_role_get_permissions "
        "tests/unit/test_models.py::TestUserModel::test_user_creation "
        "tests/unit/test_models.py::TestUserModel::test_user_properties "
        "tests/unit/test_models.py::TestUserModel::test_user_get_id "
        "tests/unit/test_models.py::TestUserModel::test_user_has_role -v"
    )
    if not run_command(test_cmd, "运行用户模型基础测试"):
        print("❌ 用户模型测试失败")
        return 1

    # 运行工具函数测试（不需要数据库的部分）
    utils_cmd = (
        "./venv/bin/pytest "
        "tests/unit/test_utils.py::TestSecurityUtils::test_create_user_datastore "
        "tests/unit/test_utils.py::TestLoggingUtils -v"
    )
    if not run_command(utils_cmd, "运行工具函数基础测试"):
        print("❌ 工具函数测试失败")
        return 1

    print("\n" + "=" * 50)
    print("✅ 所有基础测试通过！")
    print("=" * 50)
    print("\n要运行完整测试（包括需要数据库的测试），请确保 MongoDB 运行在 localhost:27017")
    print("然后运行: pytest tests/ -v")

    return 0


if __name__ == '__main__':
    sys.exit(main())
