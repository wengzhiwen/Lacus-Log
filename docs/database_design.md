# 数据库结构设计

> 术语统一记录（2025-09-26）
> - 历史用语→统一用语：机师→主播；征召→招募；训练→试播；X坐标→基地；Y坐标→场地；Z坐标→坐席；预约训练→预约试播；训练征召→试播招募；训练决策→试播决策。
> - 本次复核（2025-09-26）：已完成逐段术语检查，正文采用统一用语；数据库/接口字段仍保留历史命名，仅以字段标注说明。
数据库：`lacus`

## 集合与索引

### roles
- 字段：
  - `name` 唯一，角色名称（gicho=管理员, kancho=运营）
  - `description` 角色描述
  - `permissions` 权限列表（Flask-Security-Too扩展）
- 索引：
  - `name` 唯一索引

### users
- 字段：
  - `username` 唯一，登录标识
  - `password` 密文（pbkdf2_sha512哈希）
  - `nickname` 用户昵称
  - `email` 邮箱，非必填
  - `active` 布尔，账户激活状态
  - `created_at` 创建时间
  - `fs_uniquifier` 唯一标识符（Flask-Security-Too要求）
  - `last_login_at` 最后登录时间
  - `current_login_at` 当前登录时间
  - `last_login_ip` 最后登录IP
  - `current_login_ip` 当前登录IP
  - `login_count` 登录次数统计
  - `roles` 角色关联列表（关联到roles集合）
- 索引：
  - `username` 唯一索引
  - `fs_uniquifier` 唯一索引

### pilots
- 字段：
  - `nickname` 昵称，唯一，最大20字符
  - `real_name` 真实姓名，最大20字符
  - `gender` 性别枚举（0=男，1=女，2=不明确）
  - `birth_year` 出生年份
  - `owner` 直属运营（关联到users集合）
  - `platform` 开播地点（快手/抖音/其他/未知）
  - `work_mode` 开播方式（线下/线上/未知）
  - `rank` 主播分类（候选人/试播主播/实习主播/正式主播）
  - `status` 状态（未招募/不招募/已招募/已签约/已阵亡）
  - `created_at` 创建时间
  - `updated_at` 最后修改时间
- 索引：
  - `nickname` 唯一索引
  - `owner` 索引
  - `rank` 索引
  - `status` 索引
  - `platform` 索引
  - `created_at` 降序索引

### pilot_change_logs
- 字段：
  - `pilot_id` 关联主播ID（关联到pilots集合）
  - `user_id` 操作用户ID（关联到users集合）
  - `field_name` 变更字段名
  - `old_value` 变更前值
  - `new_value` 变更后值
  - `change_time` 变更时间
  - `ip_address` 操作IP地址
- 索引：
  - `pilot_id + change_time` 复合索引（降序）
  - `user_id` 索引
  - `change_time` 索引

### battle_areas
- 字段：
  - `x_coord` 基地，字符串，必填，最大50字符
  - `y_coord` 场地，字符串，必填，最大50字符
  - `z_coord` 坐席，字符串，必填，最大50字符
  - `availability` 可用性枚举（可用/禁用），默认可用
  - `created_at` 创建时间
  - `updated_at` 最后修改时间
- 索引：
  - `x_coord + y_coord + z_coord` 复合唯一索引
  - `x_coord` 索引
  - `y_coord` 索引
  - `availability` 索引
  - `x_coord + y_coord` 复合索引
  - `x_coord + y_coord + z_coord` 复合降序索引（`-x_coord/-y_coord/-z_coord`）

### announcements
- 字段：
  - `pilot` 关联主播（关联到pilots集合）
  - `battle_area` 关联开播地点（关联到battle_areas集合）
  - `x_coord` 基地快照，字符串，必填
  - `y_coord` 场地快照，字符串，必填
  - `z_coord` 坐席快照，字符串，必填
  - `start_time` 开始时间，UTC时间戳
  - `duration_hours` 计划时长，浮点数（1.0-16.0小时，0.5步进）
  - `recurrence_type` 重复类型枚举（无重复/每日/每周/自定义）
  - `recurrence_pattern` 重复模式，JSON格式字符串
  - `recurrence_end` 重复结束时间，UTC时间戳
  - `parent_announcement` 父通告ID（关联到自身，用于重复事件组）
  - `created_at` 创建时间
  - `updated_at` 最后修改时间
  - `created_by` 创建用户（关联到users集合）
- 索引：
  - `pilot + start_time` 复合索引
  - `battle_area + start_time` 复合索引
  - `start_time` 索引
  - `parent_announcement` 索引
  - `created_by` 索引
  - `start_time` 降序索引
  - `start_time + duration_hours` 复合索引（提升冲突检查效率）
  - `pilot + start_time + duration_hours` 复合索引
  - `battle_area + start_time + duration_hours` 复合索引

### announcement_change_logs
- 字段：
  - `announcement_id` 关联通告ID（关联到announcements集合）
  - `user_id` 操作用户ID（关联到users集合）
  - `field_name` 变更字段名
  - `old_value` 变更前值
  - `new_value` 变更后值
  - `change_time` 变更时间
  - `ip_address` 操作IP地址
- 索引：
  - `announcement_id + change_time` 复合索引（降序）
  - `user_id` 索引
  - `change_time` 索引

### battle_records
- 字段：
  - `pilot` 关联主播（必填）
  - `related_announcement` 可选的关联通告
  - `start_time` 开始时间（UTC）
  - `end_time` 结束时间（UTC）
  - `revenue_amount` 流水金额（Decimal，默认0）
  - `base_salary` 底薪金额（Decimal，默认0）
  - `x_coord` / `y_coord` / `z_coord` 开播地点快照（线下必填）
  - `work_mode` 开播方式（线上/线下）
  - `owner_snapshot` 直属运营快照（ReferenceField User）
  - `registered_by` 登记人（ReferenceField User）
  - `notes` 备注
  - `created_at` / `updated_at`
- 索引：
  - `start_time` 索引（时间范围查询）
  - `start_time + pilot` 复合索引
  - `start_time + owner_snapshot` 复合索引
  - `pilot + -start_time` 复合索引（主播业绩查询）
  - `-start_time + -revenue_amount` 复合索引（列表排序）
  - `owner_snapshot` 索引
  - `registered_by` 索引
  - `related_announcement` 索引
  - `start_time + pilot + revenue_amount` 复合索引（按月聚合）

### battle_record_change_logs
- 字段：
  - `battle_record_id` 关联开播记录ID
  - `user_id` 操作用户ID
  - `field_name` 变更字段
  - `old_value` / `new_value`
  - `change_time`
  - `ip_address`
- 索引：
  - `battle_record_id + change_time` 复合索引（降序）
  - `user_id` 索引
  - `change_time` 索引

### pilot_commissions
- 字段：
  - `pilot_id` 关联主播
  - `adjustment_date` 调整生效日期（UTC）
  - `commission_rate` 分成比例（0-50）
  - `remark` 备注
  - `is_active` 是否有效（软删除标记）
  - `created_at` / `updated_at`
- 索引：
  - `pilot_id + adjustment_date` 复合索引
  - `pilot_id + is_active` 复合索引（查询当前有效记录）
  - `adjustment_date` 索引
  - `is_active` 索引
  - `-created_at` 索引

### pilot_commission_change_logs
- 字段：
  - `commission_id` 关联分成调整记录
  - `user_id` 操作用户ID
  - `field_name` 变更字段
  - `old_value` / `new_value`
  - `change_time`
  - `ip_address`
- 索引：
  - `commission_id + change_time` 复合索引（降序）
  - `user_id` 索引
  - `change_time` 索引

### recruits
- 字段：
  - `pilot` 关联主播（历史称“机师”，字段名保留为 pilot，关联到 pilots 集合）
  - `recruiter` 招募负责人（关联到users集合，必须是运营或管理员）
  - `appointment_time` 预约时间，UTC时间戳
  - `channel` 招募渠道枚举（BOSS/51/介绍/其他）
  - `introduction_fee` 介绍费，精确到分（DecimalField，精度2）
  - `remarks` 备注，最大200字符
  - `status` 招募状态枚举（待面试/待预约试播/待试播/待预约开播/待开播/已结束）
  - 新六步制流程字段：
    - `interview_decision` 面试决策枚举（预约试播/不招募）
    - `interview_decision_maker` 面试决策人（关联到users集合）
    - `interview_decision_time` 面试决策时间，UTC时间戳
    - `scheduled_training_time` 预约试播时间，UTC时间戳
    - `scheduled_training_decision_maker` 预约试播决策人（关联到users集合）
    - `scheduled_training_decision_time` 预约试播决策时间，UTC时间戳
    - `training_decision` 试播决策枚举（预约开播/不招募）
    - `training_decision_maker` 试播决策人（关联到users集合）
    - `training_decision_time` 试播决策时间，UTC时间戳
    - `scheduled_broadcast_time` 预约开播时间，UTC时间戳
    - `scheduled_broadcast_decision_maker` 预约开播决策人（关联到users集合）
    - `scheduled_broadcast_decision_time` 预约开播决策时间，UTC时间戳
    - `broadcast_decision` 开播决策枚举（正式主播/实习主播/不招募）
    - `broadcast_decision_maker` 开播决策人（关联到users集合）
    - `broadcast_decision_time` 开播决策时间，UTC时间戳
  - 废弃字段（历史兼容）：
    - `training_decision_old` 试播招募决策枚举（废弃，原称“训练征召决策”）
    - `training_decision_maker_old` 试播招募决策人（废弃）
    - `training_decision_time_old` 试播招募决策时间（废弃）
    - `training_time` 试播时间（废弃）
    - `final_decision` 结束招募决策枚举（废弃）
    - `final_decision_maker` 结束招募决策人（废弃）
    - `final_decision_time` 结束招募决策时间（废弃）
  - `created_at` 创建时间
  - `updated_at` 最后修改时间
- 索引：
  - `pilot` 索引
  - `recruiter` 索引
  - `status` 索引
  - `-appointment_time` 降序索引
  - `-created_at` 降序索引
  - `interview_decision` 索引
  - `training_decision` 索引
  - `broadcast_decision` 索引
  - `-scheduled_training_time` 降序索引
  - `-scheduled_broadcast_time` 降序索引
  - `-interview_decision_time` 降序索引（用于招募日报统计）
  - `-broadcast_decision_time` 降序索引（用于招募日报统计）
  - `-training_decision_time` 降序索引（用于试播决策时间查询）
  - `-scheduled_training_decision_time` 降序索引（用于预约试播决策时间查询）
  - `-scheduled_broadcast_decision_time` 降序索引（用于预约开播决策时间查询）
  - `training_decision_old` 索引（历史兼容）
  - `final_decision` 索引（历史兼容）
  - `-training_time` 降序索引（历史兼容）
  - `-training_decision_time_old` 降序索引（历史兼容，用于招募日报统计）
  - `-final_decision_time` 降序索引（历史兼容，用于招募日报统计）

### recruit_change_logs
- 字段：
  - `recruit_id` 关联招募ID（关联到recruits集合）
  - `user_id` 操作用户ID（关联到users集合）
  - `field_name` 变更字段名
  - `old_value` 变更前值
  - `new_value` 变更后值
  - `change_time` 变更时间
  - `ip_address` 操作IP地址
- 索引：
  - `recruit_id + change_time` 复合索引（降序）
  - `user_id` 索引
  - `change_time` 索引

### base_salary_applications
- 字段：
  - `pilot_id` 关联主播（关联到pilots集合，必填）
  - `battle_record_id` 关联开播记录（关联到battle_records集合，必填）
  - `settlement_type` 结算方式快照（字符串：daily_base/monthly_base/none，必填）
  - `base_salary_amount` 底薪金额（Decimal，精度2，必填）
  - `applicant_id` 申请人（关联到users集合，必填）
  - `status` 申请状态枚举（pending/approved/rejected，默认pending）
  - `created_at` 创建时间（UTC）
  - `updated_at` 最后修改时间（UTC）
- 索引：
  - `pilot_id + -created_at` 复合索引（查询特定主播的历史申请）
  - `battle_record_id` 索引（关键：支持与battle_records的$lookup关联）
  - `applicant_id` 索引
  - `status` 索引
  - `-created_at` 降序索引（最新优先）
  - `pilot_id + status` 复合索引（主播按状态查询）
  - `battle_record_id + status` 复合索引（优化按申请状态的关联查询）
  - `-updated_at` 降序索引（界面排序用）
- 重要设计说明：
  - 使用 `settlement_type` 快照记录申请时的结算方式，与主播当时的设置状态对应
  - 与battle_records通过 `battle_record_id` 建立关联；查询时需使用MongoDB的 `$lookup` 聚合管道
  - **MongoEngine限制**：MongoEngine的 `aggregate()` 方法对ReferenceField的 `$lookup` 处理有限制，建议使用原生MongoDB aggregation API（`db.base_salary_applications.aggregate()`）
  - 聚合查询示例（按开播日期筛选）：
    ```python
    pipeline = [{
        '$lookup': {
            'from': 'battle_records',
            'localField': 'battle_record_id',
            'foreignField': '_id',
            'as': 'battle_record'
        }
    }, {
        '$unwind': {
            'path': '$battle_record',
            'preserveNullAndEmptyArrays': False
        }
    }, {
        '$match': {
            'battle_record.start_time': {
                '$gte': start_of_day_utc,
                '$lte': end_of_day_utc
            }
        }
    }]
    db.base_salary_applications.aggregate(pipeline)
    ```

### base_salary_application_change_logs
- 字段：
  - `application_id` 关联底薪申请ID（关联到base_salary_applications集合，必填）
  - `user_id` 操作用户ID（关联到users集合，必填）
  - `field_name` 变更字段名
  - `old_value` 变更前值
  - `new_value` 变更后值
  - `remark` 操作备注（最大200字符）
  - `change_time` 变更时间（UTC）
  - `ip_address` 操作IP地址
- 索引：
  - `application_id + -change_time` 复合索引（降序，查询申请的变更历史）
  - `user_id` 索引
  - `-change_time` 降序索引

### job_plans（新增：任务计划令牌）
- 用途：调度“计划令牌”，保证同一分钟的同名任务只执行一次（多进程/多实例下防重）。
- 字段：
  - `job_code` 任务代码（字符串，必填）
  - `fire_minute` 触发分钟（UTC，格式：YYYYMMDDHHMM，字符串，必填）
  - `planned_at` 计划写入时间（UTC，DateTime）
  - `expire_at` 过期参考时间（UTC，DateTime）
- 索引：
  - 复合唯一索引：`job_code + fire_minute`（用于 upsert 与原子 find_one_and_delete 消费）
  - TTL 索引：`expire_at`（`expireAfterSeconds = 7*24*3600`，计划历史自动清理）
- 读写路径：
  - 启动时：基于 Cron 计算“下一次触发时间（UTC分钟）”，执行 upsert 写入计划
  - 触发时：以“当前分钟（UTC）”执行 `find_one_and_delete` 原子消费；成功才运行任务；任务完成后写入下一次计划
- 启动清理：
  - 应用启动时在 `app.py` 中清空历史 JobPlan 记录（`JobPlan.objects.delete()`），避免重启导致的令牌残留与冲突。
- 环境开关：
  - 需设置 `ENABLE_SCHEDULER=true` 才会启动内置调度器并写入/消费计划令牌；开发环境仅在“重载主进程”启动以避免重复注册。

## 说明
- 启动时自动创建缺失的角色（gicho/kancho）与默认管理员
- 使用Flask-Security-Too的MongoEngineUserDatastore
- 支持会话跟踪和登录统计
- 主播管理系统包含完整的CRUD操作和变更记录（字段名沿用历史命名）
- 通告管理系统支持重复事件、冲突检查、变更记录等功能
- 招募管理系统支持六步制招募流程：待面试→待预约试播→待试播→待预约开播→待开播→已结束
- 招募系统包含完整的决策记录、决策人追踪、变更记录和历史数据兼容性
- 预计后续将为审计日志、登录日志、业务数据增加索引

### 聚合查询与关联查询的最佳实践

#### MongoEngine的 `aggregate()` 限制
MongoEngine的 `aggregate()` 方法对ReferenceField的处理有限制。使用MongoEngine时：
```python
# ❌ 可能不工作
applications_data = BaseSalaryApplication.objects.aggregate(pipeline)
```

应改用原生MongoDB API：
```python
# ✓ 正确做法
from mongoengine import get_db
db = get_db()
applications_data = list(db.base_salary_applications.aggregate(pipeline))
```

#### 时间范围查询的注意事项
- 所有时间字段在数据库中存储为UTC
- 界面显示和输入采用GMT+8（中国标准时间）
- 进行日期范围查询时，必须先将本地时间转换为UTC：
  ```python
  from utils.timezone_helper import local_to_utc
  
  query_date = datetime.strptime('2025-10-17', '%Y-%m-%d')
  start_of_day_utc = local_to_utc(query_date.replace(hour=0, minute=0, second=0))
  end_of_day_utc = local_to_utc(query_date.replace(hour=23, minute=59, second=59))
  ```

#### 底薪申请查询的最佳实践
- 优先使用底薪申请的索引（特别是 `battle_record_id`）来优化关联性能
- 进行日期范围查询时，聚合管道应放在Python代码中执行，不依赖ORM
- 聚合结果返回ObjectId，需重新查询关联的对象以获取完整数据
- 查询使用 `db.base_salary_applications` 而不是 `BaseSalaryApplication.objects.aggregate()`
