# 主播-招募日报 REST 接口

招募日报模块已完成 REST 化，页面与详情均通过 `/api/recruit-reports/daily` 获取数据。服务器端仍复用既有统计函数，保持与邮件报表一致的统计口径。

## 接口概览

- **方法**：`GET`
- **路径**：`/api/recruit-reports/daily`
- **权限**：`roles_accepted('gicho', 'kancho')`
- **响应结构**：统一的 `success/data/error/meta`
- **使用角色**：管理员、运营

同一个端点同时承载“汇总视图”和“详情视图”，通过 `view` 参数加以区分：

| 视图 | 参数 `view` | 说明 |
| --- | --- | --- |
| 汇总视图 | `summary`（默认） | 返回报表日 / 近7日 / 近14日的统计及百分比，用于日报主表格。|
| 详情视图 | `detail` | 返回指定维度的招募记录列表，用于详情页卡片。|

## 通用查询参数

| 参数 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `date` | `YYYY-MM-DD` | 当前本地日期 | 报表日期（GMT+8）。|
| `recruiter` | `字符串` | `all` | 招募负责人筛选，传运营/管理员的用户ID，`all` 表示全部。|
| `view` | `summary` / `detail` | `summary` | 控制返回汇总还是详情。|

当 `view=detail` 时需额外提供：

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `range` | `report_day` / `last_7_days` / `last_14_days` | 是 | 对应报表范围。|
| `metric` | `appointments` / `interviews` / `trials` / `new_recruits` | 是 | 对应指标：约面、到面、试播、新开播。|

## 汇总视图响应

示例：

```json
{
  "success": true,
  "data": {
    "date": "2025-01-05",
    "summary": {
      "report_day": {"appointments": 3, "interviews": 2, "trials": 1, "new_recruits": 1},
      "last_7_days": {"appointments": 15, "interviews": 8, "trials": 5, "new_recruits": 3},
      "last_14_days": {"appointments": 28, "interviews": 16, "trials": 9, "new_recruits": 6}
    },
    "percentages": {
      "report_day": {"appointments": 20.0, "interviews": 25.0, "trials": 20.0, "new_recruits": 33.3},
      "last_7_days": {"appointments": 53.6, "interviews": 50.0, "trials": 55.6, "new_recruits": 50.0}
    },
    "pagination": {
      "date": "2025-01-05",
      "prev_date": "2025-01-04",
      "next_date": "2025-01-06"
    }
  },
  "meta": {
    "filters": {"recruiter": "all"}
  }
}
```

字段说明：

- `summary`：三段统计区间的计数，字段名与页面表头一一对应。
- `percentages`：报表日占近7日、近7日占近14日的占比，仅对前两行返回。
- `pagination`：上一日/下一日日期字符串，页面用于拼接导航链接。

## 详情视图响应

示例：

```json
{
  "success": true,
  "data": {
    "date": "2025-01-05",
    "range": "last_7_days",
    "range_label": "近7日",
    "metric": "appointments",
    "metric_label": "约面",
    "count": 4,
    "recruits": [
      {
        "id": "6791347f2f3f7b5c8c9f7a10",
        "pilot": {"id": "678fde...", "nickname": "小鱼", "real_name": "张三"},
        "recruiter": {"id": "678abc...", "nickname": "运营A", "username": "kancho-a"},
        "channel": "BOSS",
        "effective_status": "待预约试播",
        "highlight": {"label": "创建", "time": "2025-01-03T10:20:00", "display": "01月03日 10:20"},
        "created_at": "2025-01-03T10:20:00",
        "remarks": "回访需跟进"
      }
    ],
    "pagination": {
      "date": "2025-01-05",
      "prev_date": "2025-01-04",
      "next_date": "2025-01-06"
    }
  },
  "meta": {
    "filters": {"recruiter": "all"},
    "labels": {"range": "近7日", "metric": "约面"}
  }
}
```

字段说明：

- `range_label` / `metric_label`：便于前端直接展示中文名称。
- `count`：符合条件的记录总数，为前端标题提供数字。
- `recruits`：序列化后的招募记录列表，字段含义：
  - `pilot`：主播基本信息（昵称、真实姓名）。
  - `recruiter`：招募负责人。
  - `channel`：招募渠道（遵循 `RecruitChannel` 枚举值）。
  - `effective_status`：当前有效状态，已兼容旧状态值。
  - `highlight`：根据指标映射出的关键时间，`time` 为 GMT+8 ISO 字符串，`display` 为页面直接展示的文本。
  - `remarks`：备注字段，若无内容返回空字符串。

## 前端适配要点

- `templates/recruit_reports/daily.html`：页面加载后调用 `view=summary` 接口渲染主表格，日期与筛选器仍通过刷新跳转保持 URL 状态。
- `templates/recruit_reports/detail.html`：详情页加载后调用 `view=detail` 接口渲染卡片列表，并复用 `recruit.detail_recruit` 路由跳转至招募详情。
- `users_api.get_operators` 继续用于下拉数据来源，保持现有权限控制。

## 其他说明

- 邮件报告 (`routes/report_mail.py`) 已直接复用 `calculate_recruit_daily_stats`，不受本次改造影响。
- 目前接口仅提供 JSON 视图，CSV 导出仍未实现。如需导出，可在同一端点上扩展 `format=csv` 分支，沿用现有统计和筛选参数。
