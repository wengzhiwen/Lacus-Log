# 主播-开播月报 REST 接口

开播月报已完成 REST 化改造，模板 `templates/reports/monthly.html` 仅渲染页面骨架，数据通过下述接口获取。

## 核心接口

- `GET /reports/api/monthly`
  - 查询参数：
    - `month`：报表月份（`YYYY-MM`），缺省为当前月。
    - `owner`：直属运营ID，`all` 表示全部。
    - `mode`：开播方式（`all`/`online`/`offline`）。
  - 返回结构示例：
    ```json
    {
      "success": true,
      "data": {
        "month": "2025-09",
        "summary": {
          "pilot_count": 86,
          "revenue_sum": 6123456.78,
          "basepay_sum": 980000.0,
          "rebate_sum": 123456.0,
          "pilot_share_sum": 3210000.0,
          "company_share_sum": 2793456.78,
          "operating_profit": 1693456.78,
          "conversion_rate": 625
        },
        "details": [
          {
            "pilot_id": "...",
            "pilot_display": "星河",
            "gender_age": "25-♀",
            "owner": "小舟",
            "rank": "正式机师",
            "records_count": 24,
            "avg_duration": 4.3,
            "total_revenue": 156234.0,
            "total_pilot_share": 81200.0,
            "total_company_share": 75034.0,
            "rebate_rate": 0.07,
            "rebate_amount": 5400.0,
            "total_base_salary": 7200.0,
            "total_profit": 72434.0
          }
        ],
        "pagination": {
          "month": "2025-09",
          "prev_month": "2025-08",
          "next_month": "2025-10"
        }
      },
      "meta": {
        "filters": {
          "owner": "all",
          "mode": "all"
        }
      }
    }
    ```

## 页面协作

- 直属运营筛选项统一来自 `GET /api/users/operators`。
- 页面通过地址栏参数控制月份与筛选条件，刷新后重新请求 API，用户体验保持与旧版一致。
- CSV 导出接口仍为 `/reports/monthly/export.csv`，与当前参数保持一致。

## 实施要点

- `rebate_rate` 以 0~1 的小数返回，需要在前端转成百分比显示。
- `operating_profit` 已包含返点抵扣，和页面原先口径一致。
- 接口具备缓存装饰器，重复请求同一月份时避免重复计算。
