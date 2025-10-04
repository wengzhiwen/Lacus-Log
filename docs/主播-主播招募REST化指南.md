# 主播招募REST化指南

本指南描述主播招募模块的REST API接口设计、使用方法和实现细节。

## API概览

招募模块现已提供完整的REST API接口，支持以下功能：

### 只读接口
- `GET /api/recruits` - 获取招募列表（支持筛选、分页、搜索）
- `GET /api/recruits/grouped` - 获取分组的招募列表（用于首页展示）
- `GET /api/recruits/<id>` - 获取招募详情
- `GET /api/recruits/<id>/changes` - 获取招募变更记录
- `GET /api/recruits/options` - 获取筛选器选项数据
- `GET /api/recruits/export` - 导出招募数据

### 写入接口
- `POST /api/recruits` - 创建招募
- `PUT /api/recruits/<id>` - 更新招募信息
- `POST /api/recruits/<id>/interview-decision` - 执行面试决策
- `POST /api/recruits/<id>/schedule-training` - 执行预约试播
- `POST /api/recruits/<id>/training-decision` - 执行试播决策
- `POST /api/recruits/<id>/schedule-broadcast` - 执行预约开播
- `POST /api/recruits/<id>/broadcast-decision` - 执行开播决策

## 响应格式

所有API接口统一使用以下响应格式：

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": { ... }
}
```

- 成功：`success=true`，结果放在 `data`；需要分页/统计时写入 `meta`
- 失败：`success=false`，`error={code,message}`，`data=null`

## 权限约定

所有接口统一使用 `@roles_accepted('gicho', 'kancho')` 权限控制，仅允许管理员和运营人员访问。

## CSRF安全

所有写入操作需要CSRF令牌验证：
- 前端从 `meta[name="csrf-token"]` 获取令牌
- 请求头添加 `X-CSRFToken` 字段
- 后端验证令牌有效性

## 数据序列化

招募数据序列化器位于 `utils/recruit_serializers.py`，提供：
- `serialize_recruit()` - 单个招募对象序列化
- `serialize_recruit_list()` - 招募列表序列化
- `serialize_change_log_list()` - 变更记录序列化
- `serialize_recruit_grouped()` - 分组数据序列化

## 前端集成

### JavaScript API客户端

提供 `static/js/recruit-api.js` 客户端库：

```javascript
// 获取招募列表
const response = await RecruitAPI.getRecruits({
    status: '进行中',
    page: 1,
    page_size: 20
});

// 创建招募
const result = await RecruitAPI.createRecruit({
    pilot_id: 'pilot_id',
    recruiter_id: 'recruiter_id',
    appointment_time: '2024-01-01T16:00',
    channel: 'BOSS',
    introduction_fee: 100.00,
    remarks: '备注信息'
});

// 执行面试决策
await RecruitAPI.interviewDecision(recruitId, {
    interview_decision: '预约试播',
    real_name: '真实姓名',
    birth_year: 1990,
    introduction_fee: 100.00,
    remarks: '备注'
});
```

### 错误处理

```javascript
try {
    const result = await RecruitAPI.createRecruit(data);
    ErrorHandler.showSuccess('操作成功');
} catch (error) {
    ErrorHandler.showError(error.message);
}
```

## 状态流转

招募流程的状态流转通过不同的API接口实现：

1. **创建招募** → `PENDING_INTERVIEW` (待面试)
2. **面试决策** → `PENDING_TRAINING_SCHEDULE` (待预约试播) 或 `ENDED` (已结束)
3. **预约试播** → `PENDING_TRAINING` (待试播)
4. **试播决策** → `PENDING_BROADCAST_SCHEDULE` (待预约开播) 或 `ENDED` (已结束)
5. **预约开播** → `PENDING_BROADCAST` (待开播)
6. **开播决策** → `ENDED` (已结束)

## 兼容性

- 保持原有模板路由的兼容性，现有页面仍可正常访问
- 新功能优先使用REST API实现
- 支持历史数据的有效状态映射

## 测试

建议使用以下方式测试API：

1. **单元测试**：使用Flask test client构造请求
2. **集成测试**：模拟真实登录流程，携带CSRF令牌
3. **前端测试**：验证JavaScript客户端功能

## 注意事项

1. 所有时间字段使用ISO格式字符串，前端需要处理时区转换
2. 枚举值使用字符串形式，需要验证有效性
3. 分页参数：`page`（页码，从1开始）、`page_size`（每页数量）
4. 搜索功能支持主播昵称和真实姓名的模糊匹配
