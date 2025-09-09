#!/usr/bin/env python3
"""
测试运行脚本
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
    print("Lacus-Log 测试套件")
    print("=" * 50)

    # 检查是否在虚拟环境中
    if not hasattr(sys, 'real_prefix') and not (hasattr(sys, 'base_prefix') and
                                                sys.base_prefix != sys.prefix):
        print("警告: 建议在虚拟环境中运行测试")

    # 安装测试依赖
    if not run_command("pip install -r requirements.txt", "安装依赖"):
        print("❌ 依赖安装失败")
        return 1

    # 运行单元测试
    if not run_command("pytest tests/unit/ -v", "运行单元测试"):
        print("❌ 单元测试失败")
        return 1

    # 运行集成测试（需要数据库）
    print("\n注意: 集成测试需要 MongoDB 运行在 localhost:27017")
    if not run_command("pytest tests/integration/ -v", "运行集成测试"):
        print("⚠️  集成测试失败（可能需要数据库连接）")

    # 运行测试覆盖率
    if not run_command("pytest --cov=. --cov-report=html --cov-report=term",
                       "生成测试覆盖率报告"):
        print("⚠️  覆盖率报告生成失败")

    print("\n" + "=" * 50)
    print("测试完成！")
    print("覆盖率报告: htmlcov/index.html")
    print("=" * 50)

    return 0


if __name__ == '__main__':
    sys.exit(main())
