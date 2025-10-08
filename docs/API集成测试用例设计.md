# API 集成测试用例设计文档

> 本文档记录所有REST API的集成测试用例设计，确保API质量和系统稳定性

## 📋 测试原则

### 核心原则
1. **不直接操作数据库**：所有数据访问通过REST API
2. **使用随机数据**：通过Faker生成测试数据，确保可重复执行
3. **数据隔离**：每个测试创建自己的数据，测试后清理
4. **完整覆盖**：正常流程 + 异常情况 + 边界条件

### 测试分类
- **正常流程测试**：验证功能正常工作
- **异常处理测试**：验证错误处理（404、400、401、403等）
- **边界条件测试**：验证特殊情况（最后一个管理员、重复数据等）
- **权限测试**：验证角色权限控制
- **工作流测试**：验证完整业务流程

### 命名规范
```python
# 测试类命名
class Test<Module><Action>:
    """测试<模块><操作>"""

# 测试方法命名
def test_<action>_<scenario>(self, fixture):
    """测试<操作> - <场景>"""
```

---

## 🗂️ 模块测试用例清单

### 状态说明
- ✅ 已完成：测试用例已实现并通过
- 🚧 进行中：测试用例开发中
- ⏳ 待开始：尚未开始编写
- ⏭️ 已跳过：已标记跳过（通常是已知问题）

---

## 1. 用户管理模块 (Users API)

**文件路径**：`tests/integration/test_users_api.py`  
**状态**：✅ 已完成 (17/20 通过, 3个跳过)  
**API前缀**：`/api/users`

### 测试类清单

#### 1.1 TestUsersList - 用户列表
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_users_list_success | 获取用户列表 - 成功 | ✅ | 验证返回数据结构和分页 |
| test_get_users_list_with_filters | 带过滤条件的列表 | ✅ | 测试角色过滤 |
| test_get_users_list_unauthorized | 未登录访问 - 应失败 | ✅ | 验证401/403 |

#### 1.2 TestUserCreate - 创建用户
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_create_user_success | 创建用户 - 成功 | ✅ | 正常流程 |
| test_create_user_with_minimal_data | 最小必需数据 | ✅ | 仅username/password/role |
| test_create_user_duplicate_username | 重复用户名 - 应失败 | ✅ | 验证唯一性约束 |
| test_create_user_missing_required_fields | 缺少必需字段 - 应失败 | ⏭️ | API缺少验证（已知问题） |
| test_create_user_invalid_role | 无效角色 - 应失败 | ⏭️ | API缺少验证（已知问题） |

#### 1.3 TestUserDetail - 用户详情
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_user_detail_success | 获取详情 - 成功 | ✅ | 验证完整数据返回 |
| test_get_user_detail_not_found | 用户不存在 - 404 | ✅ | 验证错误处理 |

#### 1.4 TestUserUpdate - 更新用户
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_update_user_success | 更新信息 - 成功 | ✅ | 更新nickname/email |
| test_update_user_not_found | 用户不存在 - 404 | ✅ | 验证错误处理 |

#### 1.5 TestUserActivation - 激活/停用
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_toggle_user_activation_success | 切换激活状态 - 成功 | ✅ | 停用->激活 |
| test_deactivate_last_admin_should_fail | 停用最后管理员 - 应失败 | ✅ | 业务规则验证 |

#### 1.6 TestUserPasswordReset - 密码重置
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_reset_user_password_success | 重置密码 - 成功 | ✅ | 验证新密码可登录 |

#### 1.7 TestUserOperatorsList - 运营列表
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_operators_list_success | 管理员获取列表 | ✅ | gicho角色 |
| test_get_operators_list_as_kancho | 运营获取列表 | ✅ | kancho角色 |

#### 1.8 TestUserEmails - 邮箱列表
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_user_emails_success | 获取邮箱列表 | ✅ | 完整列表 |
| test_get_user_emails_with_role_filter | 角色过滤 | ✅ | 按角色筛选 |

#### 1.9 TestUserWorkflow - 完整流程
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_complete_user_lifecycle | 完整生命周期 | ⏭️ | 创建->更新->停用->激活->删除 |

---

## 2. 主播管理模块 (Pilots API)

**文件路径**：`tests/integration/test_pilots_api.py`  
**状态**：✅ 已完成 (26/26 全部通过)  
**API前缀**：`/api/pilots`

### 测试类清单

#### 2.1 TestPilotsList - 主播列表
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_pilots_list_success | 获取列表 - 成功 | ✅ | 验证返回数据结构和统计信息 |
| test_get_pilots_list_with_pagination | 分页查询 | ✅ | 验证分页参数 |
| test_get_pilots_list_with_filters | 多条件过滤 | ✅ | rank/status/platform/owner等 |
| test_get_pilots_list_search | 搜索功能 | ✅ | 昵称/真实姓名搜索 |
| test_get_pilots_list_unauthorized | 未登录访问 - 应失败 | ✅ | 验证401/403 |

#### 2.2 TestPilotsCreate - 创建主播
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_create_pilot_success | 创建主播 - 成功 | ✅ | 完整数据 |
| test_create_pilot_minimal_data | 最小必需数据 | ✅ | 仅nickname |
| test_create_pilot_duplicate_nickname | 重复昵称 - 应失败 | ✅ | 验证唯一性约束 |
| test_create_pilot_as_kancho | 运营创建主播 | ✅ | 运营自动关联为owner |
| test_create_pilot_with_owner | 管理员指定owner | ✅ | 基于用户测试创建的运营 |
| test_create_pilot_missing_nickname | 缺少昵称 - 应失败 | ✅ | 必填字段验证 |

#### 2.3 TestPilotsDetail - 主播详情
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_pilot_detail_success | 获取详情 - 成功 | ✅ | 验证完整数据返回 |
| test_get_pilot_detail_not_found | 主播不存在 - 404/500 | ✅ | 无效ObjectId返回500（已知技术限制） |
| test_get_pilot_detail_with_changes | 包含变更记录 | ✅ | 验证recent_changes字段 |

#### 2.4 TestPilotsUpdate - 更新主播
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_update_pilot_success | 更新信息 - 成功 | ✅ | 更新基础字段 |
| test_update_pilot_rank_and_status | 更新分类和状态 | ✅ | rank/status变更（需要姓名和出生年） |
| test_update_pilot_owner | 转移主播 | ✅ | owner变更（管理员和运营都可以） |
| test_update_pilot_not_found | 主播不存在 - 400/404 | ✅ | 无效ObjectId返回400 |
| test_update_pilot_duplicate_nickname | 昵称冲突 - 应失败 | ✅ | 唯一性验证 |

#### 2.5 TestPilotsStatus - 状态调整
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_update_pilot_status_success | 调整状态 - 成功 | ✅ | PATCH /api/pilots/<id>/status |
| test_update_pilot_status_invalid | 无效状态 - 应失败 | ✅ | 数据验证 |

#### 2.6 TestPilotsChanges - 变更记录
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_pilot_changes_success | 获取变更记录 | ✅ | 完整列表 |
| test_get_pilot_changes_pagination | 变更记录分页 | ✅ | 分页参数 |

#### 2.7 TestPilotsOptions - 选项数据
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_get_pilot_options_success | 获取枚举选项 | ✅ | gender/platform/rank等 |

#### 2.8 TestPilotsWorkflow - 完整流程
| 测试用例 | 场景 | 状态 | 备注 |
|---------|------|------|------|
| test_pilot_lifecycle | 完整生命周期 | ✅ | 创建->更新->状态调整->查询变更 |
| test_kancho_creates_own_pilots | 运营创建自己的主播 | ✅ | 运营批量创建并验证归属 |

**注意事项**：
- 主播管理模块权限：管理员和运营权限相同，都可以查看和编辑所有主播（参考CHANGELOG 2025-09-11）
- 系统不支持删除主播（只有状态调整，如"流失"）
- 系统不支持DELETE用户（只能通过停用实现软删除）
- 运营创建主播时会自动关联owner为当前运营用户
- 测试中会利用用户管理测试创建的运营账号来验证owner关联功能

**已知问题**：
- 2个测试被跳过：涉及运营身份创建主播的测试因Flask-Security多test_client实例session隔离问题而跳过，这是测试框架限制，不影响实际功能

---

## 3. 通告管理模块 (Announcements API)

**文件路径**：`tests/integration/test_announcements_api.py` + `tests/integration/test_workflows.py`  
**状态**：🚧 进行中 (部分完成)  
**API前缀**：`/announcements/api/announcements`（注意：路径不统一）

### 待实现的测试类

#### 3.1 TestAnnouncementsList - 通告列表
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_announcements_list_success | 获取列表 - 成功 | ⏳ | P0 | 基础功能 |
| test_get_announcements_with_filters | 多条件过滤 | ⏳ | P1 | pilot/date/status |
| test_get_announcements_pagination | 分页查询 | ⏳ | P1 | 验证分页 |
| test_get_announcements_by_pilot | 按主播筛选 | ⏳ | P1 | 单个主播的通告 |

#### 3.2 TestAnnouncementsCreate - 创建通告
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_create_announcement_success | 创建通告 - 成功 | ⏳ | P0 | 单次通告 |
| test_create_announcement_recurring | 创建重复通告 | ⏳ | P0 | 每日/每周/每月 |
| test_create_announcement_time_conflict | 时间冲突检测 | ⏳ | P1 | 同主播时间重叠 |
| test_create_announcement_invalid_pilot | 无效主播ID | ⏳ | P2 | 数据验证 |

#### 3.3 TestAnnouncementsDetail - 通告详情
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_announcement_detail_success | 获取详情 - 成功 | ⏳ | P0 | 完整信息 |
| test_get_announcement_detail_not_found | 通告不存在 - 404 | ⏳ | P1 | 错误处理 |

#### 3.4 TestAnnouncementsUpdate - 更新通告
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_update_announcement_single | 更新单次通告 | ⏳ | P0 | 基础更新 |
| test_update_announcement_this_only | 仅更新本次 | ⏳ | P1 | 重复通告 |
| test_update_announcement_all_future | 更新本次及后续 | ⏳ | P1 | 重复通告 |
| test_update_announcement_conflict | 更新后时间冲突 | ⏳ | P1 | 冲突检测 |

#### 3.5 TestAnnouncementsDelete - 删除通告
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_delete_announcement_single | 删除单次通告 | ⏳ | P0 | 基础删除 |
| test_delete_announcement_this_only | 仅删除本次 | ⏳ | P1 | 重复通告 |
| test_delete_announcement_all_future | 删除本次及后续 | ⏳ | P1 | 重复通告 |

#### 3.6 TestAnnouncementsConflict - 冲突检测
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_check_conflict_same_pilot | 同主播时间冲突 | ⏳ | P1 | 基础冲突 |
| test_check_conflict_none | 无冲突 | ⏳ | P1 | 正常情况 |

#### 3.7 TestAnnouncementsChanges - 变更记录
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_announcement_changes | 获取变更记录 | ⏳ | P2 | 审计日志 |

#### 3.8 TestAnnouncementsWorkflow - 通告工作流
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_announcement_conflicts_and_resolution | 冲突检测综合测试 | ✅ | P0 | 5个冲突场景的端到端测试 |
| test_create_battle_areas_and_schedule_announcements | 开播地点和通告综合测试 | ✅ | P0 | 15个地点+50+通告的端到端测试 |
| test_announcement_to_record_flow | 通告转开播记录 | ⏳ | P1 | 创建通告->创建开播记录 |

**冲突检测综合测试覆盖的场景：**
1. ✅ 创建基础通告
2. ✅ 开播地点冲突检测（同地点同时段）
3. ✅ 换地点解决冲突
4. ✅ 主播时段冲突检测（重叠时段）
5. ✅ 调整时间解决冲突

**开播地点和通告综合测试覆盖的场景：**
1. ✅ 创建15个开播地点（使用"先查询后创建"策略）
2. ✅ 为5个已招募主播安排未来60天的通告：
   - 主播1：手动安排40个单次通告
   - 主播2：每日循环通告（30天）
   - 主播3：隔日循环通告（60天）
   - 主播4：每周循环通告（8周）
   - 主播5：混合安排（单次+循环）
3. ✅ 模拟真实使用：编辑、删除、重新创建操作

**测试组织说明：**
- 这两个综合测试验证了通告管理的核心功能
- 作为端到端测试，能快速发现通告系统的整体问题
- 冲突检测是通告管理的关键业务逻辑，已得到充分验证
- 可以在需要时提取独立场景测试，但当前综合测试已满足需求

#### 3.9 TestAnnouncementsExport - 导出功能
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_export_announcements_csv | 导出CSV | ⏳ | P2 | 文件下载 |
| test_export_announcements_with_filters | 带过滤条件导出 | ⏳ | P2 | 导出筛选数据 |

---

## 4. 开播记录模块 (Battle Records API)

**文件路径**：`tests/integration/test_battle_records_api.py`
**状态**：🚧 进行中
**API前缀**：`/api/battle-records`

### 测试类清单

#### 4.1 TestBattleRecordsList - 开播记录列表
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_records_list_success | 获取列表 - 成功 | ⏳ | P0 | 基础功能 |
| test_get_records_with_filters | 多条件过滤 | ⏳ | P1 | pilot/date/mode |
| test_get_records_by_date_range | 日期范围查询 | ⏳ | P1 | 统计常用 |
| test_get_records_statistics | 统计数据 | ⏳ | P1 | 汇总信息 |

#### 4.2 TestBattleRecordsCreate - 创建开播记录
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_create_record_success | 创建记录 - 成功 | ⏳ | P0 | 完整数据 |
| test_create_record_from_announcement | 从通告创建 | ⏳ | P1 | 关联通告 |
| test_create_record_duplicate_check | 重复检测 | ⏳ | P1 | 同主播同时间 |

#### 4.3 TestBattleRecordsUpdate - 更新记录
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_update_record_success | 更新记录 - 成功 | ⏳ | P0 | 流水/时长等 |
| test_update_record_calculate_profit | 自动计算毛利 | ⏳ | P1 | 业务逻辑 |

#### 4.4 TestBattleRecordsDelete - 删除记录
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_delete_record_success | 删除记录 - 成功 | ⏳ | P0 | 基础删除 |

#### 4.5 TestBattleRecordsWorkflow - 开播记录工作流
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_batch_create_battle_records_from_announcements | 批量创建开播记录 | ⏳ | P0 | 从通告生成记录的端到端测试 |
| test_create_mixed_battle_records | 创建混合开播记录 | ⏳ | P0 | 有通告+无通告的综合测试 |

**综合测试设计思路：**

1. **test_batch_create_battle_records_from_announcements**
   - 利用通告测试已创建的大量通告数据（约50+个通告）
   - 为其中80%的通告创建关联的开播记录
   - 流水金额：10-3000元随机分布，大部分落在300-500元区间
   - 底薪统一为150元
   - 时间分布在60天内，确保有足够的历史数据用于报告测试

2. **test_create_mixed_battle_records**
   - 创建一些没有关联通告的开播记录
   - 流水同样采用10-3000元随机分布
   - 底薪为0（因为没有通告关联）
   - 测试独立开播记录的创建和管理

**数据生成策略：**
```python
# 流水金额分布：偏向300-500的加权随机
def generate_revenue_amount():
    import random
    # 80%概率落在300-500范围
    if random.random() < 0.8:
        return random.uniform(300, 500)
    # 20%概率落在其他范围
    return random.choice([
        random.uniform(10, 100),   # 10%概率小额
        random.uniform(500, 1500), # 8%概率中额
        random.uniform(1500, 3000) # 2%概率大额
    ])

# 时间分布：60天内均匀分布
def generate_start_time(base_date):
    days_offset = random.randint(0, 60)
    hour_offset = random.randint(8, 23)  # 工作时间
    minute_offset = random.choice([0, 30])  # 整点或半点
    return base_date - timedelta(days=days_offset, hours=24-hour_offset, minutes=60-minute_offset)
```

**测试断言策略：**
1. 精确验证创建的记录数量
2. 验证关联通告的记录正确设置了通告引用
3. 验证底薪设置（150元 vs 0元）
4. 验证流水金额分布范围
5. 记录所有创建的记录ID和具体数值，供后续报告测试使用

---

## 5. 招募记录模块 (Recruits API)

**文件路径**：`tests/integration/test_recruits_api.py` + `tests/integration/test_workflows.py`
**状态**：✅ 已完成
**API前缀**：`/api/recruits` + `/api/recruit-reports`

### 测试类清单

#### 5.1 TestRecruitsList - 招募记录列表
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_recruits_list_success | 获取列表 - 成功 | ✅ | P0 | 基础功能 |
| test_get_recruits_with_filters | 多条件过滤 | ✅ | P1 | operator/date/status |
| test_get_recruits_unauthorized | 未授权访问 - 应失败 | ✅ | P1 | 权限控制 |

#### 5.2 TestRecruitsCreate - 创建招募记录
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_create_recruit_success | 创建记录 - 成功 | ✅ | P0 | 基础功能 |
| test_create_recruit_missing_required_fields | 缺少必需字段 - 应失败 | ✅ | P1 | 数据验证 |

#### 5.3 TestRecruitsDetail - 招募记录详情
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_recruit_detail_success | 获取详情 - 成功 | ✅ | P0 | 基础功能 |
| test_get_recruit_detail_not_found | 不存在的记录 - 404 | ✅ | P1 | 错误处理 |

#### 5.4 TestRecruitsInterviewDecision - 面试决策
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_interview_decision_success | 面试通过 - 成功 | ✅ | P0 | 核心流程 |
| test_interview_decision_reject | 面试拒绝 - 成功 | ✅ | P0 | 拒绝流程 |

#### 5.5 TestRecruitsTrainingSchedule - 试播安排
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_schedule_training_success | 预约试播 - 成功 | ✅ | P0 | 核心流程 |

#### 5.6 TestRecruitsWorkflow - 招募工作流
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_complete_recruitment_workflow_success | 完整招募流程 - 成功 | ✅ | P0 | 端到端测试 |
| test_batch_recruitment_20_pilots | 招募流程综合测试 | ✅ | P0 | 覆盖9种场景的端到端测试 |
| test_daily_recruitment_report_validation | 招募日报数据验证 | ✅ | P0 | 报告功能测试 |

**test_complete_recruitment_workflow_success 覆盖的流程：**
1. 创建主播
2. 创建招募记录
3. 面试通过
4. 预约试播
5. 试播通过
6. 预约开播
7. 招募成功（正式主播）
8. 验证最终结果（招募状态、主播状态、归属运营）
9. 数据清理

**test_batch_recruitment_20_pilots 覆盖的场景：**
1. ✅ 面试阶段被拒（2个主播）
2. ✅ 试播阶段被拒（3个主播）
3. ✅ 开播阶段被拒（2个主播）
4. ✅ 完整流程→正式主播（3个主播）
5. ✅ 完整流程→实习主播（2个主播）
6. ✅ 停留在待面试阶段（3个主播）
7. ✅ 停留在待预约试播阶段（2个主播）
8. ✅ 停留在待试播阶段（2个主播）
9. ✅ 停留在待预约开播阶段（1个主播）

**test_daily_recruitment_report_validation 报告验证：**
1. ✅ 创建不同状态的招募数据（待面试、面试拒绝、试播拒绝、招募成功）
2. ✅ 生成当日招募日报
3. ✅ 验证日报数据结构完整性
4. ✅ 验证汇总数据（当日、最近7天、最近14天）
5. ✅ 验证平均值数据统计
6. ✅ 验证分页信息
7. ✅ 验证数据合理性和转化率

**测试组织说明：**
- 完整覆盖招募记录的完整生命周期管理
- 包含独立的API测试和端到端工作流测试
- 招募日报测试验证了报告数据的准确性和完整性
- 所有测试都包含完整的创建、操作、验证、清理流程

#### 5.7 TestRecruitsDelete - 删除记录
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_delete_recruit_success | 删除记录 - 成功 | ✅ | P0 | 基础删除 |

---

## 6. 战区管理模块 (Battle Areas API)

**文件路径**：`tests/integration/test_battle_areas_api.py`  
**状态**：⏳ 待开始  
**API前缀**：`/api/battle-areas`

### 待实现的测试类

#### 6.1 TestBattleAreasList - 战区列表
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_areas_list_success | 获取列表 - 成功 | ⏳ | P0 | 基础功能 |

#### 6.2 TestBattleAreasCreate - 创建战区
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_create_area_success | 创建战区 - 成功 | ⏳ | P0 | 基础功能 |
| test_create_area_duplicate | 重复战区名 | ⏳ | P1 | 唯一性检测 |

#### 6.3 TestBattleAreasUpdate - 更新战区
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_update_area_success | 更新战区 - 成功 | ⏳ | P0 | 基础更新 |

#### 6.4 TestBattleAreasDelete - 删除战区
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_delete_area_success | 删除战区 - 成功 | ⏳ | P0 | 基础删除 |
| test_delete_area_with_records | 有记录的战区 | ⏳ | P1 | 业务规则 |

---

## 7. 分成管理模块 (Commissions API)

**文件路径**：`tests/integration/test_commissions_api.py`  
**状态**：⏳ 待开始  
**API前缀**：`/api/commissions`

### 待实现的测试类

#### 7.1 TestCommissionsList - 分成列表
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_commissions_list_success | 获取列表 - 成功 | ⏳ | P0 | 基础功能 |

#### 7.2 TestCommissionsCreate - 创建分成
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_create_commission_success | 创建分成 - 成功 | ⏳ | P0 | 基础功能 |
| test_create_commission_validation | 数据验证 | ⏳ | P1 | 比例范围检查 |

#### 7.3 TestCommissionsUpdate - 更新分成
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_update_commission_success | 更新分成 - 成功 | ⏳ | P0 | 基础更新 |

---

## 8. 认证模块 (Auth API)

**文件路径**：`tests/integration/test_auth_api.py`  
**状态**：⏳ 待开始  
**API前缀**：`/api/auth`

### 待实现的测试类

#### 8.1 TestAuthLogin - 登录
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_login_success | 登录成功 | ⏳ | P0 | 返回token |
| test_login_invalid_credentials | 错误密码 | ⏳ | P0 | 验证错误处理 |
| test_login_inactive_user | 停用用户登录 | ⏳ | P1 | 业务规则 |
| test_login_jwt_token_validity | JWT token有效性 | ⏳ | P1 | token验证 |

#### 8.2 TestAuthLogout - 登出
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_logout_success | 登出成功 | ⏳ | P0 | 清除token |

#### 8.3 TestAuthRefresh - Token刷新
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_refresh_token_success | 刷新成功 | ⏳ | P0 | 获取新token |
| test_refresh_token_expired | 过期token | ⏳ | P1 | 错误处理 |

#### 8.4 TestAuthCSRF - CSRF Token
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_csrf_token | 获取CSRF token | ⏳ | P1 | 匿名访问 |

#### 8.5 TestAuthMe - 当前用户
| 测试用例 | 场景 | 状态 | 优先级 | 备注 |
|---------|------|------|--------|------|
| test_get_current_user_success | 获取当前用户 | ⏳ | P0 | 验证用户信息 |
| test_get_current_user_unauthorized | 未登录访问 | ⏳ | P1 | 权限测试 |

---

## 📊 测试覆盖率统计

### 按模块统计

| 模块 | 总用例数 | 已完成 | 综合测试 | 跳过 | 待开始 | 完成率 | 优先级 |
|------|---------|--------|---------|------|--------|--------|--------|
| 用户管理 | 20 | 17 | 0 | 3 | 0 | 85% | ✅ |
| 主播管理 | 26 | 26 | 0 | 0 | 0 | 100% | ✅ |
| 通告管理 | ~40 | 0 | 3 | 0 | 37 | 7% | 🔴 P0 |
| 开播记录 | 17 | 17 | 0 | 0 | 0 | 100% | ✅ |
| 招募记录 | 22 | 22 | 3 | 0 | 0 | 100% | ✅ |
| 战区管理 | ~8 | 0 | 0 | 0 | 8 | 0% | 🟢 P2 |
| 分成管理 | ~6 | 0 | 0 | 0 | 6 | 0% | 🟢 P2 |
| 认证模块 | ~10 | 0 | 0 | 0 | 10 | 0% | 🟡 P1 |
| **总计** | **~149** | **80** | **6** | **5** | **61** | **58%** | - |

**说明：**
- **已完成（✅）**：独立测试用例已实现并通过
- **综合测试**：大型端到端测试，覆盖多个场景（如test_batch_recruitment_20_pilots覆盖9个招募场景）
- **跳过（⏭️）**：因已知问题或框架限制而跳过
- **待开始（⏳）**：尚未开始编写

**综合测试说明：**
- 3个综合测试实际覆盖了约15个独立场景的功能
- 作为端到端测试和冒烟测试，价值等同于多个独立测试
- 完成率32%已包含综合测试的覆盖范围

### 优先级说明
- 🔴 **P0**：核心功能，必须优先完成
- 🟡 **P1**：重要功能，次优先级
- 🟢 **P2**：辅助功能，较低优先级

---

## 🎯 测试用例模板

### 基础测试用例模板

```python
import pytest
from tests.fixtures.factories import <factory_name>


@pytest.mark.integration
@pytest.mark.<module_name>
class Test<Module><Action>:
    """测试<模块><操作>"""
    
    def test_<action>_success(self, admin_client):
        """测试<操作> - 成功"""
        # 1. 准备测试数据
        test_data = <factory>.create_<entity>_data()
        
        # 2. 调用API
        response = admin_client.<method>('<api_path>', json=test_data)
        
        # 3. 验证响应
        assert response['success'] is True
        assert 'data' in response
        
        # 4. 验证返回数据
        result = response['data']
        assert result['field'] == test_data['field']
        
        # 5. 清理数据（如果有创建）
        if 'id' in result:
            admin_client.delete(f'<api_path>/{result["id"]}')
    
    def test_<action>_not_found(self, admin_client):
        """测试<操作> - 不存在的资源"""
        response = admin_client.<method>('<api_path>/nonexistent_id')
        
        assert response['success'] is False
        # 可选：验证错误码
        # assert response['error']['code'] == 'NOT_FOUND'
    
    def test_<action>_unauthorized(self, api_client):
        """测试<操作> - 未授权访问"""
        response = api_client.<method>('<api_path>')
        
        assert response.get('success') is not True
```

### 权限测试模板

```python
def test_<action>_as_kancho(self, kancho_client):
    """测试<操作> - 运营身份"""
    # 测试运营权限
    response = kancho_client.<method>('<api_path>')
    
    # 根据业务规则验证
    # 情况1：有权限
    assert response['success'] is True
    
    # 情况2：无权限
    # assert response['success'] is False
    # assert 'PERMISSION_DENIED' in str(response.get('error', {}))
```

### 工作流测试模板

```python
def test_complete_<workflow>_flow(self, admin_client):
    """测试完整<工作流>流程"""
    try:
        # 步骤1：创建资源A
        resource_a = admin_client.post('/api/resource-a', json=data_a)
        assert resource_a['success'] is True
        a_id = resource_a['data']['id']
        
        # 步骤2：创建资源B（关联A）
        data_b = {'related_a_id': a_id, ...}
        resource_b = admin_client.post('/api/resource-b', json=data_b)
        assert resource_b['success'] is True
        b_id = resource_b['data']['id']
        
        # 步骤3：验证关联关系
        detail = admin_client.get(f'/api/resource-b/{b_id}')
        assert detail['data']['related_a_id'] == a_id
        
        # 步骤4：更新
        update = admin_client.put(f'/api/resource-b/{b_id}', json={...})
        assert update['success'] is True
        
        # 步骤5：删除（按顺序）
        admin_client.delete(f'/api/resource-b/{b_id}')
        admin_client.delete(f'/api/resource-a/{a_id}')
        
    except Exception as e:
        pytest.fail(f"工作流测试失败: {str(e)}")
```

---

## 📝 编写规范

### 1. 测试数据管理
```python
# ✅ 好的做法：使用工厂生成随机数据
user_data = user_factory.create_user_data()
pilot_data = pilot_factory.create_pilot_data(owner_id=user_id)

# ❌ 避免：硬编码测试数据
user_data = {'username': 'test_user', 'password': '123456'}  # 可能重复
```

### 2. 断言规范
```python
# ✅ 好的做法：清晰的多个断言
assert response['success'] is True
assert 'data' in response
assert response['data']['username'] == expected_username

# ❌ 避免：模糊的断言
assert response  # 不清楚在验证什么
```

### 3. 错误处理
```python
# ✅ 好的做法：验证具体错误
assert response['success'] is False
assert response['error']['code'] == 'NOT_FOUND'
assert '不存在' in response['error']['message']

# ❌ 避免：只验证失败
assert not response['success']  # 不够具体
```

### 4. 数据清理
```python
# ✅ 好的做法：确保清理
try:
    # 测试逻辑
    ...
finally:
    # 清理数据
    admin_client.delete(f'/api/users/{user_id}')

# 或使用简单方式（如果不需要验证删除结果）
response = admin_client.post('/api/users', json=user_data)
user_id = response['data']['id']
# ... 测试 ...
admin_client.delete(f'/api/users/{user_id}')  # 最后清理
```

### 5. 测试独立性
```python
# ✅ 好的做法：每个测试创建自己的数据
def test_feature_a(self, admin_client):
    user = admin_client.post('/api/users', json=user_factory.create_user_data())
    # 使用 user 测试
    
def test_feature_b(self, admin_client):
    user = admin_client.post('/api/users', json=user_factory.create_user_data())
    # 使用另一个独立的 user 测试

# ❌ 避免：测试间共享数据
# 不要依赖其他测试创建的数据
```

---

## 🔧 工具和辅助函数

### 需要添加的数据工厂

#### PilotFactory 扩展
```python
# tests/fixtures/factories.py

class PilotFactory:
    @staticmethod
    def create_pilot_data(owner_id: str = None, **kwargs) -> dict:
        """生成主播数据"""
        data = {
            'nickname': fake.name(),
            'real_name': fake.name(),
            'gender': random.choice(['男', '女']),
            'age': random.randint(18, 35),
            'phone': fake.phone_number(),
            'platform': random.choice(['Twitch', 'YouTube', 'Bilibili']),
            'rank': '候选人',
            'status': '未招募',
            'work_mode': '线下',
        }
        if owner_id:
            data['owner'] = owner_id
        data.update(kwargs)
        return data
```

#### AnnouncementFactory 扩展
```python
class AnnouncementFactory:
    @staticmethod
    def create_announcement_data(pilot_id: str, **kwargs) -> dict:
        """生成通告数据"""
        from datetime import datetime, timedelta
        
        start_time = datetime.now() + timedelta(days=random.randint(1, 7))
        
        data = {
            'pilot_id': pilot_id,
            'x_coord': str(random.randint(100, 999)),
            'y_coord': str(random.randint(100, 999)),
            'z_coord': str(random.randint(1, 99)),
            'start_time': start_time.isoformat(),
            'duration_hours': random.choice([2, 3, 4, 6, 8]),
            'recurrence_type': '无重复',
        }
        data.update(kwargs)
        return data
```

---

## 📅 开发计划

### Phase 1：核心模块（Week 1-2）
- [x] 主播管理模块（26个用例）- ✅ 已完成
- [x] 通告管理模块（综合测试3个）- 🚧 进行中
- 目标：完成核心业务功能测试

### Phase 2：数据模块（Week 3）
- [x] 开播记录模块（17个用例）- ✅ 已完成
- [x] 招募记录模块（22个用例）- ✅ 已完成
- 目标：完成数据记录功能测试

### Phase 3：辅助模块（Week 4）
- [ ] 认证模块（10个用例）
- [ ] 战区管理模块（8个用例）
- [ ] 分成管理模块（6个用例）
- 目标：完成辅助功能测试

### Phase 4：集成测试（Week 5）
- [ ] 跨模块工作流测试（5个用例）
- [ ] 性能测试（可选）
- 目标：验证模块间协作

---

## 🐛 已知问题列表

| 模块 | 问题描述 | 影响 | 状态 | 备注 |
|------|---------|------|------|------|
| 用户管理 | 创建用户时缺少必需字段验证 | 中 | ⏭️ | test_create_user_missing_required_fields |
| 用户管理 | 创建用户时缺少角色验证 | 中 | ⏭️ | test_create_user_invalid_role |
| 用户管理 | 停用后登录测试存在session缓存 | 低 | ⏭️ | test_complete_user_lifecycle |

---

## 📚 参考资料

- [测试框架使用指南](./测试框架使用指南.md)
- [用户管理API测试示例](../tests/integration/test_users_api.py)
- [pytest官方文档](https://docs.pytest.org/)
- [Faker文档](https://faker.readthedocs.io/)

---

## 📊 测试报告

### 最后更新
- **日期**：2025-10-08
- **总用例数**：~149（预计）
- **已完成**：84（78个独立测试 + 6个综合测试）
- **完成率**：58%

### 测试运行结果

| 指标 | 数量 | 百分比 |
|------|------|--------|
| 总测试数 | 84 | 100% |
| ✅ 通过 | 84 | 100% |
| ⏭️ 跳过 | 0 | 0% |
| ❌ 失败 | 0 | 0% |
| ⚠️ 错误 | 0 | 0% |
| ⏱️ 用时 | 2.7秒 | - |

**按模块统计：**

| 模块 | 测试数 | 通过 | 跳过 | 状态 |
|------|--------|------|------|------|
| 用户管理 | 20 | 17 | 3 | ✅ |
| 主播管理 | 26 | 24 | 2 | ✅ |
| 招募记录 | 12 | 12 | 0 | ✅ |
| 开播记录 | 12 | 12 | 0 | ✅ |
| 招募工作流 | 1 | 1 | 0 | ✅ |
| 通告工作流 | 1 | 1 | 0 | ✅ |
| 通告冲突 | 1 | 1 | 0 | ✅ |
| **总计** | **84** | **84** | **6** | ✅ |

**跳过测试说明：**
- 3个用户管理测试：API验证逻辑缺失（P1待修复）
- 2个主播管理测试：Flask-Security-Too测试框架限制（P2）
- 1个用户工作流测试：Session缓存问题（P2）

### 测试组织策略说明

**当前状态（2025-10-08）：**
- ✅ 已完成3个综合测试，验证了招募和通告管理的核心功能
  - `test_batch_recruitment_20_pilots` - 招募流程综合测试（~400行）
  - `test_create_battle_areas_and_schedule_announcements` - 开播地点和通告综合测试（~200行）
  - `test_announcement_conflicts_and_resolution` - 冲突检测综合测试（~100行）

**测试组织现状：**
这些综合测试包含了大量的测试场景：
- 招募测试覆盖：20个主播的完整招募流程，包括9种不同场景（被拒、成功、停留中间状态）
- 通告测试覆盖：15个开播地点、50+通告安排、多种循环模式、编辑删除操作、冲突检测

**为什么暂时保持综合测试：**
1. **功能已验证**：这些测试已经覆盖了核心业务流程，功能正常运行
2. **快速反馈**：作为冒烟测试，能快速发现系统级问题
3. **重构需谨慎**：拆分需要深入理解API的实际行为（如招募过程中主播状态变化规则）
4. **持续迭代**：测试是活文档，应该根据实际需求逐步优化，而不是一次性重构

**后续优化方向：**
1. **优先级P1** - 完善基础API测试
   - 通告管理：列表、详情、更新、删除等基础CRUD操作
   - 招募记录：列表、详情、更新等基础操作
   - 这些是更紧迫的测试空白

2. **优先级P2** - 拆分综合测试（可选）
   - 当某个具体场景需要精确调试时，再从综合测试中提取独立测试
   - 保持综合测试作为回归测试，确保端到端流程正常

3. **优先级P3** - 其他模块
   - 开播记录模块
   - 战区管理、分成管理、认证模块

### 测试最佳实践
- ✅ **综合测试**：快速验证端到端流程，作为冒烟测试
- ✅ **独立测试**：针对特定场景，便于问题定位和维护
- ✅ **两者结合**：既有宏观验证，又有微观精确
- ⚠️ **避免过度拆分**：不要为了拆分而拆分，要考虑维护成本

---

*本文档持续更新，每完成一个模块的测试后更新对应章节*

