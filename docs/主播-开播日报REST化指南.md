# 主播-开播日报 REST 接口

开播日报已经完成 REST 化改造，页面骨架仍由 `templates/reports/daily.html` 渲染，数据全部来自 JSON 接口。

## 核心接口

- `GET /reports/api/daily`
  - 查询参数：
    - `date`：报表日期（`YYYY-MM-DD`，缺省为当前本地日）。
    - `owner`：直属运营ID，`all` 表示汇总全部。
    - `mode`：开播方式（`all`/`online`/`offline`）。
  - 返回结构：
    ```json
    {
      "success": true,
      "data": {
        "date": "2025-09-30",
        "summary": {
          "pilot_count": 18,
          "effective_pilot_count": 12,
          "revenue_sum": 152300.5,
          "basepay_sum": 32000.0,
          "pilot_share_sum": 81200.0,
          "company_share_sum": 71100.5,
          "conversion_rate": 476
        },
        "details": [
          {
            "pilot_id": "...",
            "pilot_display": "星辰（林某）",
            "gender_age": "24-♀",
            "owner": "小舟",
            "rank": "正式机师",
            "battle_area": "线上@L1-01-02",
            "duration": 5.5,
            "revenue": 12345.67,
            "commission_rate": 55.0,
            "pilot_share": 6790.12,
            "company_share": 5555.55,
            "rebate_rate": 0.05,
            "rebate_amount": 617.28,
            "base_salary": 600.0,
            "daily_profit": 5572.83,
            "three_day_avg_revenue": 9800.12,
            "monthly_stats": {
              "month_days_count": 12,
              "month_avg_duration": 4.2,
              "month_total_revenue": 82340.55,
              "month_total_base_salary": 7800.0
            },
            "monthly_commission_stats": {
              "month_total_pilot_share": 36210.11,
              "month_total_company_share": 29870.44,
              "month_total_profit": 24070.44
            },
            "month_rebate_amount": 2100.0
          }
        ],
        "pagination": {
          "date": "2025-09-30",
          "prev_date": "2025-09-29",
          "next_date": "2025-10-01"
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

- 模板只负责结构、路由跳转与 CSV 下载按钮；数据加载由内嵌脚本调用 `GET /reports/api/daily` 完成。
- 直属运营选项统一调用 `GET /api/users/operators`，保持与其他模块一致的人员列表。
- CSV 导出继续沿用 `/reports/daily/export.csv`，会根据当前筛选参数生成内容。

## 注意事项

- 接口返回的金额、时长均为浮点数，前端需自行格式化显示。
- `rebate_rate` 仍使用 0~1 小数表示，需要在前端转为百分比。
- 当 `three_day_avg_revenue` 为 `null` 时表示近三天不足以计算平均值。
- 接口带有缓存装饰器，频繁刷新同一日期会命中缓存，避免额外查询压力。
