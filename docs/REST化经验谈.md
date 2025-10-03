# REST化经验谈

> 总结本次将模板渲染改为通过 REST API 交互的落地经验，聚焦真实踩坑与可复用规范。示例来自“主播管理/用户管理”。

## 1. 接口与通用约定
- 统一响应结构：success / data / error / meta。
  - 成功：{"success": true, "data": {...}, "error": null, "meta": {...}}
  - 失败：{"success": false, "data": null, "error": {"code": "...", "message": "..."}, "meta": {}}
- 写操作权限固定用法：@roles_accepted('gicho','kancho')。遗漏导入会触发运行期 NameError。
- CSRF：仅写操作需要，统一从请求头 X-CSRFToken 校验。

## 2. 模型/序列化一致性
- 字段名必须与模型一致。
  - 经验：PilotChangeLog 实际是 pilot_id / change_time，不是 pilot / created_at。
- 只读属性不可写（如 Pilot.age 由 birth_year 计算）。更新逻辑只写“持久化字段”。
- 统一“空值”处理：封装 safe_strip(value)，将 None 与空白字符串安全归一。

## 3. 业务校验与错误回传
- 模型 clean() 的业务错误用 ValueError 表达；接口层显式 except ValueError as e 返回 VALIDATION_ERROR 与清晰 message。
- 保存顺序：校验 -> 赋值 -> save() -> 写变更日志。缺少 save() 会出现“日志有、数据没变”。

## 4. 变更记录与审计
- 严格按模型写入：PilotChangeLog(pilot_id=..., user_id=..., field_name, old_value, new_value, ...)。
- 仅写存在于模型的字段；需要扩展先改模型。
- 序列化时将 Enum 统一转 .value，前端按统一字典渲染。

## 5. 前端交互与错误展示
- 固定错误区 + toast：表单上方常驻错误区展示后端 error.message，同时用短 toast 提醒。
- 枚举/下拉“去耦”：如直属运营下拉改为 /api/users/operators 独立接口，页面加载时与枚举并行拉取。

## 6. 导出下载的可靠实现
- 后端响应头：
  - Content-Disposition: attachment; filename="pilot_export.csv"
  - Content-Type: text/csv; charset=utf-8
  - 在内容前加 BOM："\ufeff" + csv_content 以兼容 Excel 中文。
- 前端优先使用 window.location.href = '/api/.../export?...' 触发下载；只有在需要自定义鉴权头/跨域时才降级到 fetch -> blob 方案。

## 7. 筛选/枚举/导出一致性
- 多选参数统一使用 getlist 语义：?owner_id=a&owner_id=b。
- 后端过滤前做枚举合法性检查（非法值忽略）以避免 500。
- 导出列头与详情页字段一致；时间统一本地化格式化。

## 8. 改造 Checklist（强烈建议）
1) 明确页面数据点，分离“布局（保留）/数据（API化）”。
2) 先列表/详情（只读），再创建/更新/状态变更（写入）。
3) 统一响应结构与错误码；前端接入固定错误区。
4) 审核模型字段：只读/可空/枚举；同步更新序列化与变更日志映射。
5) 统一空值策略：前端可能传 null，后端用 safe_strip() 配合处理。
6) 导出链路单独走通：响应头、BOM、文件名、触发方式。
7) 日志：接口入口/出口 INFO，异常 ERROR+exc_info=True，必要 DEBUG。

## 9. 可复用片段
```python
# 安全去空格
def safe_strip(value):
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return None

# 业务错误回传
try:
    pilot.save()
except ValueError as e:
    return jsonify(create_error_response('VALIDATION_ERROR', str(e))), 400
```

```javascript
// 固定错误区
function showErrorAlert(message) {
  const box = document.getElementById('errorAlert');
  document.getElementById('errorMessage').textContent = message || '保存失败';
  box.style.display = 'flex';
}

// 导出（优先浏览器下载）
function exportPilots() {
  const params = new URLSearchParams(/* 当前筛选 */);
  window.location.href = `/api/pilots/export?${params.toString()}`;
}
```

---
以上规范可作为后续模块 REST 化基线：最小必要改动、UI 不变、错误清晰、日志可追踪。

