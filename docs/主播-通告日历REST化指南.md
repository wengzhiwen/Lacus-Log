# 主播-通告日历REST接口现状

通告日历模块在 `routes/calendar_api.py` 中提供三组只读 JSON 接口，用于月/周/日视图的数据填充。此前文档猜测的 `/api/announcements/calendar/...` 路径与现状不符，现统一说明如下。

## 可用接口

| 功能 | 方法 | 路径 | 说明 |
| --- | --- | --- | --- |
| 月视图数据 | GET | `/calendar/api/month-data` | 参数：`year`、`month`（默认当前月）。内部调用 `aggregate_monthly_data` 聚合每天的通告数量等信息。|
| 周视图数据 | GET | `/calendar/api/week-data` | 参数：`date`（任意位于目标周的日期，默认今日）。调用 `aggregate_weekly_data` 返回 7 天的通告与可用资源统计。|
| 日视图数据 | GET | `/calendar/api/day-data` | 参数：`date`（默认今日）。调用 `aggregate_daily_data`，返回各坐席在当日的时间轴数据。|

- 以上接口均要求用户已登录并具备 `gicho` / `kancho` 角色。
- 响应由 `utils/calendar_aggregator.py` 生成，结构已在对应模块中固定下来（包含聚合结果与时间范围）。

## 仍采用模板的部分

- `/calendar/`（周视图默认页）、`/calendar/month`、`/calendar/week`、`/calendar/day` 仍渲染 HTML 模板（位于 `routes/calendar.py`），仅在前端加载时调用上述 JSON 接口。
- 通告的创建、编辑、冲突处理等操作依旧在 `routes/announcement.py` 中完成，与日历 API 无直接关联。

## 使用与维护建议

1. **前端调用**：在日历视图中通过 `fetch('/calendar/api/week-data?date=...')` 获取数据，并基于返回结构渲染；如需新增字段，请同步更新 `aggregate_*` 函数与前端解析逻辑。
2. **错误处理**：接口失败时返回 `{"error": "获取数据失败"}` 且状态码 500，前端应做好兜底提示。
3. **扩展字段**：若要为返回值增加更多统计（例如占用率、冲突列表），建议在 `aggregate_*` 函数中扩展，保持 JSON 结构向后兼容。
4. **权限控制**：目前所有接口均允许运营与管理员访问；如需开放给其他角色，请在蓝图装饰器上调整。

> 结论：通告日历已经具备月/周/日三类只读 REST 接口，其路径与前文档描述不同。请以本文为准调用，并在扩展时保持结构一致性。
