# 数据库结构设计

数据库：`lacus`

## 集合与索引

### roles
- 字段：
  - `name` 唯一，角色名称（gicho=议长, kancho=舰长）
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
  - `owner` 所属舰长/议长（关联到users集合）
  - `platform` 战区枚举（快手/抖音/其他/未知）
  - `work_mode` 参战形式枚举（线下/线上/未知）
  - `rank` 阶级枚举（候补机师/训练机师/实习机师/正式机师）
  - `status` 状态枚举（未征召/不征召/已征召/已签约/已阵亡）
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
  - `pilot_id` 关联机师ID（关联到pilots集合）
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
  - `x_coord` X坐标，字符串，必填，最大50字符
  - `y_coord` Y坐标，字符串，必填，最大50字符
  - `z_coord` Z坐标，字符串，必填，最大50字符
  - `availability` 可用性枚举（可用/禁用），默认可用
  - `created_at` 创建时间
  - `updated_at` 最后修改时间
- 索引：
  - `x_coord + y_coord + z_coord` 复合唯一索引
  - `x_coord` 索引
  - `y_coord` 索引
  - `availability` 索引
  - `x_coord + y_coord` 复合索引
  - `x_coord + y_coord + z_coord` 复合降序索引

### announcements
- 字段：
  - `pilot` 关联机师（关联到pilots集合）
  - `battle_area` 关联战斗区域（关联到battle_areas集合）
  - `x_coord` X坐标快照，字符串，必填
  - `y_coord` Y坐标快照，字符串，必填
  - `z_coord` Z坐标快照，字符串，必填
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

### recruits
- 字段：
  - `pilot` 关联机师（关联到pilots集合）
  - `recruiter` 征召负责人（关联到users集合，必须是舰长或议长）
  - `appointment_time` 预约时间，UTC时间戳
  - `channel` 征召渠道枚举（BOSS/51/介绍/其他）
  - `introduction_fee` 介绍费，精确到分（DecimalField，精度2）
  - `remarks` 备注，最大200字符
  - `status` 征召状态枚举（待面试/待预约训练/待训练/待预约开播/待开播/已结束）
  - 新六步制流程字段：
    - `interview_decision` 面试决策枚举（预约训练/不征召）
    - `interview_decision_maker` 面试决策人（关联到users集合）
    - `interview_decision_time` 面试决策时间，UTC时间戳
    - `scheduled_training_time` 预约训练时间，UTC时间戳
    - `scheduled_training_decision_maker` 预约训练决策人（关联到users集合）
    - `scheduled_training_decision_time` 预约训练决策时间，UTC时间戳
    - `training_decision` 训练决策枚举（预约开播/不征召）
    - `training_decision_maker` 训练决策人（关联到users集合）
    - `training_decision_time` 训练决策时间，UTC时间戳
    - `scheduled_broadcast_time` 预约开播时间，UTC时间戳
    - `scheduled_broadcast_decision_maker` 预约开播决策人（关联到users集合）
    - `scheduled_broadcast_decision_time` 预约开播决策时间，UTC时间戳
    - `broadcast_decision` 开播决策枚举（正式机师/实习机师/不征召）
    - `broadcast_decision_maker` 开播决策人（关联到users集合）
    - `broadcast_decision_time` 开播决策时间，UTC时间戳
  - 废弃字段（历史兼容）：
    - `training_decision_old` 训练征召决策枚举（废弃）
    - `training_decision_maker_old` 训练征召决策人（废弃）
    - `training_decision_time_old` 训练征召决策时间（废弃）
    - `training_time` 训练时间（废弃）
    - `final_decision` 结束征召决策枚举（废弃）
    - `final_decision_maker` 结束征召决策人（废弃）
    - `final_decision_time` 结束征召决策时间（废弃）
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
  - `-interview_decision_time` 降序索引（用于征召日报统计）
  - `-broadcast_decision_time` 降序索引（用于征召日报统计）
  - `-training_decision_time` 降序索引（用于训练决策时间查询）
  - `-scheduled_training_decision_time` 降序索引（用于预约训练决策时间查询）
  - `-scheduled_broadcast_decision_time` 降序索引（用于预约开播决策时间查询）
  - `training_decision_old` 索引（历史兼容）
  - `final_decision` 索引（历史兼容）
  - `-training_time` 降序索引（历史兼容）
  - `-training_decision_time_old` 降序索引（历史兼容，用于征召日报统计）
  - `-final_decision_time` 降序索引（历史兼容，用于征召日报统计）

### recruit_change_logs
- 字段：
  - `recruit_id` 关联征召ID（关联到recruits集合）
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
- 启动时自动创建缺失的角色（gicho/kancho）与默认议长
- 使用Flask-Security-Too的MongoEngineUserDatastore
- 支持会话跟踪和登录统计
- 机师管理系统包含完整的CRUD操作和变更记录
- 作战计划管理系统支持重复事件、冲突检查、变更记录等功能
- 机师征召管理系统支持六步制征召流程：待面试→待预约训练→待训练→待预约开播→待开播→已结束
- 征召系统包含完整的决策记录、决策人追踪、变更记录和历史数据兼容性
- 预计后续将为审计日志、登录日志、业务数据增加索引
