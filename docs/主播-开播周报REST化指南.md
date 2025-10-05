# 主播-开播周报 REST 接口

开播周报已支持 REST 化访问，模板 `templates/reports/weekly.html` 仅负责骨架与交互入口，数据由接口提供。

## 核心接口

- `GET /reports/api/weekly`
  - 查询参数：
    - `week_start`：报表起始自然日（周二，`YYYY-MM-DD`），缺省为“当前日期的上一周周二”。
    - `owner`：直属运营ID，`all` 表示全部。
    - `mode`：开播方式（`all`/`online`/`offline`）。
  - 返回结构示例：
    ```json
    {
      "success": true,
      "data": {
        "week_start": "2025-09-23",
        "summary": {
          "pilot_count": 42,
          "revenue_sum": 512340.0,
          "basepay_sum": 86000.0,
          "pilot_share_sum": 271000.0,
          "company_share_sum": 241340.0,
          "profit_7d": 155340.0,
          "conversion_rate": 596
        },
        "details": [
          {
            "pilot_id": "...",
            "pilot_display": "火花",
            "gender_age": "23-♂",
            "owner": "小舟",
            "rank": "正式机师",
            "records_count": 8,
            "avg_duration": 4.5,
            "total_revenue": 61234.5,
            "total_pilot_share": 31800.0,
            "total_company_share": 29434.5,
            "total_base_salary": 4000.0,
            "total_profit": 25434.5
          }
        ],
        "pagination": {
          "week_start": "2025-09-23",
          "prev_week_start": "2025-09-16",
          "next_week_start": "2025-09-30"
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

- 页面筛选器仍保持原有体验，变更后通过地址栏刷新页面并重新请求 API。
- 所有直属运营选项来自 `GET /api/users/operators`。
- CSV 下载保留 `/reports/weekly/export.csv`，会带上当前选定的 `week_start`、`owner` 与 `mode`。

## 使用提示

- `profit_7d` 为不计返点的 7 天毛利，可能为空或 0，前端需自行格式化。
- 若传入的 `week_start` 不是周二，接口将自动对齐到最近的周二起点。
- 列表按照“周累计毛利”排序，便于定位表现较差的主播。
