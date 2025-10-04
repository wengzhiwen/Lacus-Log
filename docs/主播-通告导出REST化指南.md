# 主播-通告导出REST接口现状

通告导出功能目前仅提供传统的表单页面 `/announcements/export`，提交后在服务器端渲染 HTML 表格并返回给用户，**未实现任何 REST 接口**。以下为现状说明与后续改造提示。

## 现有实现

- 入口：GET `/announcements/export` 渲染选择表单（主播 + 年月）。
- 提交：POST `/announcements/export` 校验表单参数，调用 `generate_export_table()` 生成表格数据，再同步渲染 `export_table.html`。
- 打印：前端直接调用浏览器打印或另存为 PDF，不涉及 API。

## 未实现的 REST 能力

指南中提到的 `/api/announcements/export/options`、`/preview`、`/tasks` 等接口均尚未落地；当前代码也不支持异步导出或 CSV/PDF 下载。

## 维护建议

1. **继续使用现有表单流程**：如需微调导出效果，请直接修改模板与 `generate_export_table()` 的数据结构。
2. **若要 REST 化**：
   - 需拆分数据组装逻辑，输出 JSON 给前端自行渲染；
   - 或提供导出的文件下载接口（CSV/PDF），并复用统一的 `success/data/error` 响应结构。
3. **记录需求**：在真正实现 REST 导出前，请勿引用或依赖本指南中未落地的端点，避免产生混淆。

> 结论：当前仓库没有任何与通告导出相关的 REST API，仍以表单渲染为主。后续改造时再行更新本文件。

## 未来 REST 化建议

- **统一导出入口**：如需提供 API 导出，建议沿用 `GET /api/announcements?format=csv` 这种内容协商方式，而非新增 `/api/announcements/export` 路径。
- **预览与打印**：若需要预览数据，可复用列表接口并在 `meta` 内附带表格结构，使页面和导出保持同一数据源。
