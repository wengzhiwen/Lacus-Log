# S1-S9 集成测试套件

## 概述

本项目包含9个完整的集成测试套件（S1-S9），覆盖了Lacus-Log系统的核心业务功能。每个测试套件都专注于特定的业务领域，确保系统各模块的正确性和可靠性。

## 测试套件结构

### 📁 文件组织

```
tests/
├── README.md                              # 本文档
├── conftest.py                            # 全局pytest配置
├── fixtures/                              # 测试工具和数据工厂
│   ├── __init__.py
│   ├── api_client.py                      # API客户端封装
│   └── factories.py                       # 测试数据工厂
└── integration/                           # 集成测试套件
    ├── __init__.py
    ├── conftest.py                        # 集成测试专用配置
    ├── test_suite_s1_auth_security.py     # S1: 认证与安全
    ├── test_suite_s2_user_role_management.py  # S2: 用户角色管理
    ├── test_suite_s3_recruitment_pipeline.py   # S3: 招募流程
    ├── test_suite_s4_pilot_broadcast_salary.py # S4: 主播开播与底薪
    ├── test_suite_s5_announcement_calendar.py # S5: 通告与日历
    ├── test_suite_s6_settlement_commission.py # S6: 结算与佣金
    ├── test_suite_s7_bbs_operations.py    # S7: BBS操作
    ├── test_suite_s8_calculation_accuracy.py  # S8: 计算准确性
    ├── test_suite_s8_dashboard_reports.py     # S8: 仪表盘报告
    ├── test_suite_s9_alerts_notifications.py  # S9: 告警通知
    └── test_suite_s9_mail_generation.py      # S9: 邮件生成
```

## 🧪 测试套件详情

### S1: 认证与安全基线测试
**文件**: `test_suite_s1_auth_security.py`
**测试数量**: 7个测试用例
**覆盖范围**:
- JWT token生命周期管理
- CSRF验证机制
- 角色权限控制
- 会话隔离
- 刷新token机制

### S2: 用户角色管理测试
**文件**: `test_suite_s2_user_role_management.py`
**测试数量**: 7个测试用例
**覆盖范围**:
- 用户创建和角色分配
- 用户信息更新
- 激活/停用和最后管理员保护
- 密码重置和登录验证
- 用户验证和错误处理
- 用户搜索和过滤
- 用户完整生命周期

### S3: 招募流程测试
**文件**: `test_suite_s3_recruitment_pipeline.py`
**测试数量**: 7个测试用例
**覆盖范围**:
- 完整招募流程
- 面试拒绝流程
- 培训拒绝流程
- 异常流程阻塞
- 鸽子检测和过滤
- 操作日志SSE
- 招募统计和指标

### S4: 主播开播与底薪测试
**文件**: `test_suite_s4_pilot_broadcast_salary.py`
**测试数量**: 10个测试用例
**覆盖范围**:
- 主播基础数据管理
- 开播记录创建和BBS触发
- 底薪申请审批链路
- 开播记录编辑冲突
- BBS回复链路
- 主播状态工作流
- 主播重复昵称验证
- 主播所有权转移
- 开播记录时间验证
- 批量从通告创建开播记录

### S5: 通告与日历测试
**文件**: `test_suite_s5_announcement_calendar.py`
**测试数量**: 7个测试用例
**覆盖范围**:
- 创建每日重复通告
- 创建每周重复通告
- 编辑当前实例
- 编辑未来所有实例
- 删除当前实例
- 删除未来所有实例
- 相关通告管理

### S6: 结算与佣金测试
**文件**: `test_suite_s6_settlement_commission.py`
**测试数量**: 17个测试用例
**覆盖范围**:
- 结算计划创建和查询
- 结算修改和历史跟踪
- 删除限制
- 佣金记录管理
- 佣金修改和跟踪
- 结算和佣金集成
- 验证测试（类型、格式、边界、字段等）
- 一致性测试（日期重叠、记录顺序、跨模块关系）
- 错误测试（HTTP方法、缺失字段、不存在资源、格式错误）

### S7: BBS操作测试
**文件**: `test_suite_s7_bbs_operations.py`
**测试数量**: 5个测试用例
**覆盖范围**:
- 管理员发帖和关联主播
- 权限控制
- 嵌套回复树
- 关联开播记录缺失时的回退
- 帖子搜索和过滤

### S8: 计算准确性与仪表盘测试
**文件**: `test_suite_s8_calculation_accuracy.py`, `test_suite_s8_dashboard_reports.py`
**测试数量**: 8个测试用例
**覆盖范围**:
- 基本统计计算准确性
- 边界情况计算准确性
- 转化率计算准确性
- 仪表盘API可用性
- 报告API可用性
- 邮件报告API可用性
- 数据创建和基本工作流
- 参数验证和错误处理

### S9: 告警通知与邮件生成测试
**文件**: `test_suite_s9_alerts_notifications.py`, `test_suite_s9_mail_generation.py`
**测试数量**: 8个测试用例
**覆盖范围**:
- James关注告警触发
- 邮件通知黑名单
- SSE长轮询通知
- 告警规则和配置
- 通知偏好和过滤器
- 基础邮件文件生成
- 复杂计算邮件生成
- 边界情况邮件生成

## 🚀 快速开始

### 环境要求
- Python 3.8+
- MongoDB
- 依赖包：`pip install -r requirements.txt`

### 运行测试

#### 1. 运行所有测试套件
```bash
pytest tests/integration/
```

#### 2. 运行特定测试套件
```bash
# 运行S1测试套件
pytest tests/integration/test_suite_s1_auth_security.py

# 运行S4测试套件
pytest tests/integration/test_suite_s4_pilot_broadcast_salary.py
```

#### 3. 运行特定测试用例
```bash
# 运行S4套件中的第5个测试用例
pytest tests/integration/test_suite_s4_pilot_broadcast_salary.py::TestS4PilotBroadcastSalary::test_s4_tc5_complaint_reply_chain
```

#### 4. 显示详细输出
```bash
pytest tests/integration/ -v -s
```

#### 5. 运行特定标记的测试
```bash
# 运行所有认证相关测试
pytest tests/integration/ -m "auth_security"

# 运行所有BBS相关测试
pytest tests/integration/ -m "bbs_operations"
```

## 🔧 配置说明

### 数据库隔离
每个测试会话使用独立的随机数据库，确保测试间的完全隔离：
- 自动生成数据库名：`lacus_test_<8位随机字符>`
- 自动创建默认角色和账户
- 测试结束后自动清理数据库

### 默认账户
测试环境中自动创建：
- **用户名**: `zala`
- **密码**: `plant4ever`
- **角色**: `gicho`（管理员）

### Fixtures
- `admin_client`: 已登录的管理员客户端
- `kancho_client`: 已登录的运营客户端
- `pilot_factory`: 主播数据工厂
- `battle_record_factory`: 开播记录数据工厂

## 📊 测试统计

- **总测试套件**: 9个（S1-S9）
- **总测试用例**: 76个
- **覆盖率**: 核心业务功能全覆盖
- **通过率**: 通常 >95%

## 🛠️ 开发指南

### 添加新测试用例
1. 确定测试属于哪个套件（S1-S9）
2. 在相应的测试文件中添加测试方法
3. 使用现有的fixtures和工具函数
4. 遵循命名规范：`test_sX_tcY_description`

### 调试技巧
```bash
# 显示print输出
pytest tests/integration/test_suite_s4_pilot_broadcast_salary.py -s

# 只运行失败的测试
pytest tests/integration/ --lf

# 在第一个失败时停止
pytest tests/integration/ -x

# 显示详细错误信息
pytest tests/integration/ -v --tb=long
```

### 常见问题

#### CSRF Token问题
BBS相关测试需要CSRF token，参考S7测试套件的实现：
```python
# 先访问BBS页面获取CSRF token
bbs_page_response = admin_client.client.get('/bbs/')
# 解析HTML获取token
# 在请求中使用token
```

#### 数据库连接问题
确保MongoDB服务正在运行：
```bash
# macOS
brew services start mongodb-community

# 或直接启动
mongod --config /usr/local/etc/mongod.conf
```

## 📚 相关文档

- [集成测试发现的问题记录](../docs/集成测试发现的问题记录.md) - 测试修复过程和问题解决
- [pytest集成测试补充计划](../docs/pytest集成测试补充计划.md) - 测试计划文档
- [项目开发约定](../.claude/CLAUDE.md) - 项目开发规范

## 🤝 贡献

在修改测试套件时，请：
1. 保持测试的独立性
2. 使用适当的fixtures
3. 添加清晰的文档和注释
4. 确保所有相关测试通过
5. 更新相关文档

---

*最后更新: 2025-10-24*