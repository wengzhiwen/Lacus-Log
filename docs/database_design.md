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

## 说明
- 启动时自动创建缺失的角色（gicho/kancho）与默认议长
- 使用Flask-Security-Too的MongoEngineUserDatastore
- 支持会话跟踪和登录统计
- 预计后续将为审计日志、登录日志、业务数据增加索引
