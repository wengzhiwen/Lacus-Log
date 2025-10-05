# 基础-仪表盘 REST 化指南

## 结构概览

- 首页 `GET /` 由 `routes/main.py` 的 `home` 视图负责，只渲染 `templates/dashboard/index.html`，页面加载后通过前端脚本逐个调用 REST 接口。
- 所有仪表盘统计运算统一收敛到 `routes/report.py`，`main` 仅作为接口层转发计算结果。
- 页面脚本以 Promise 并发方式请求各自的指标接口，加载成功后再渲染卡片并触发动画。

## API 列表

| 接口 | 说明 | 数据来源函数 |
| --- | --- | --- |
| `GET /api/dashboard/recruit` | 返回当日招募指标（约面、到面、新开播） | `calculate_dashboard_recruit_metrics` |
| `GET /api/dashboard/announcements` | 返回通告计划统计（当日、环比、近 7 日平均） | `calculate_dashboard_announcement_metrics` |
| `GET /api/dashboard/battle-records` | 返回开播记录流水统计（今日、昨日、7 日平均） | `calculate_dashboard_battle_metrics` |
| `GET /api/dashboard/pilots` | 返回主播人数统计（服役、实习、正式） | `calculate_dashboard_pilot_metrics` |
| `GET /api/dashboard/candidates` | 返回候选人相关统计（候补、试播） | `calculate_dashboard_candidate_metrics` |
| `GET /api/dashboard/feature` | 返回仪表盘顶部横幅配置 | `build_dashboard_feature_banner` |

### 响应约定

- 均返回统一结构：
  ```json
  {
    "success": true,
    "data": {
      "generated_at": "2025-10-05 14:30:00",
      "...具体指标...": 123
    },
    "error": null,
    "meta": { "segment": "recruit", "link": "/reports/recruit/daily" }
  }
  ```
- `generated_at` 为 GMT+8 时间；`meta.segment` 用于标识卡片类型，`meta.link`（若存在）给出默认跳转地址。

## 前端渲染要点

- 模板路径：`templates/dashboard/index.html`
  - 预置所有卡片骨架与 `data-field` 占位符。
  - 加载后使用 `Promise.all` 并发请求上述接口，并在全部成功后执行翻牌动画。
  - 链接跳转逻辑集中在 `setupCardNavigation()` 中，依据接口 `meta.link` 或模板默认值构建目标 URL。

## 扩展建议

- 新增卡片时：
  1. 在 `routes/report.py` 中新增对应计算函数。
  2. 在 `routes/main.py` 注册新的 `/api/dashboard/...` 接口，返回统一响应结构。
  3. 在 `templates/dashboard/index.html` 和前端脚本中补充卡片 DOM 与渲染逻辑。
- 若需要缓存或批量刷新，可在 `routes/main.py` 接口层增加缓存策略，并通过 `meta` 暴露缓存时间等信息。
