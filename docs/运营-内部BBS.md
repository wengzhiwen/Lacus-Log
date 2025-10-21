# 运营-内部BBS

内部BBS用于为运营与管理员提供分基地的信息沟通与问题追踪空间，具备分板块、置顶、回复、隐藏等基本能力，并与开播记录及主播业绩模块联动。

## 背景与目标
- 为每个基地提供独立的讨论板块，运营/管理员可在对应基地下发帖交流。
- 采用REST API供前后端复用，帖子详情采用通用弹出层组件，被BBS列表页与主播业绩页共享。
- 与开播记录打通：当创建有备注的开播记录时自动生成联动主贴，方便后续追踪问题。

## 术语与角色
- **板块（Board）**：最小归属单位，默认按照`基地`划分，可扩展其他主题板块。
- **主贴（Post）**：板块内的顶级帖子，记录发布者、内容、关联开播记录等信息。
- **楼层回复（Reply）**：对主贴的直接回复。
- **楼中楼（Comment）**：对某条回复的补充评论，仅允许一层嵌套（回复的回复），不再递归。
- 角色：管理员、运营具备发帖/置顶/隐藏权限；普通运营仅能操作自己发布的内容。

## 数据结构

### 1. 板块（bbs_boards）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | ObjectId | 主键 |
| code | 字符串 | 唯一编码，默认采用基地英文代号 |
| name | 字符串 | 板块名称（展示名） |
| type | 枚举 | `base`（基地类）/`custom`（自定义） |
| base_id | ObjectId | 关联开播地点中的基地元数据，type=base时必填 |
| is_active | 布尔 | 是否可见 |
| order | 数值 | 排序权重，越小越靠前 |
| created_at/updated_at | 时间戳 | UTC |

### 2. 主贴（bbs_posts）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | ObjectId | 主键 |
| board_id | ObjectId | 归属板块 |
| title | 字符串 | 标题 |
| content | 富文本/Markdown | 帖子正文（允许段落与列表，不引入附件） |
| author_id | ObjectId | 发布者用户ID |
| author_snapshot | JSON | 包含昵称、角色、头像等展示信息 |
| status | 枚举 | `published`/`hidden` |
| is_pinned | 布尔 | 是否置顶（板块内独立排序） |
| related_battle_record_id | ObjectId | 关联开播记录，可为空 |
| last_active_at | 时间戳 | 最近更新时间/回复时间，列表排序字段 |
| created_at/updated_at | 时间戳 | UTC |

### 3. 回复（bbs_replies）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | ObjectId | 主键 |
| post_id | ObjectId | 归属主贴 |
| parent_reply_id | ObjectId | 若为楼中楼则指向父回复；顶级回复为空 |
| content | 字符串 | 回复内容 |
| author_id | ObjectId | 回复者 |
| author_snapshot | JSON | 展示信息 |
| status | 枚举 | `published`/`hidden` |
| created_at/updated_at | 时间戳 | UTC |

### 4. 主播关联索引（bbs_post_pilot_refs）
| 字段 | 类型 | 说明 |
| --- | --- | --- |
| post_id | ObjectId | 主贴ID |
| pilot_id | ObjectId | 关联主播ID |
| relevance | 枚举 | `auto`（系统自动）/`manual` |
| updated_at | 时间戳 | 用于“最近更新”排序 |

> 注：当主贴关联的开播记录涉及某主播时，自动写入`auto`关联；运营可在帖子详情中手动补充其他主播关联，用于主播业绩页聚合。

## REST API 设计

- 响应格式统一使用 `create_success_response` 与 `create_error_response`（新增 `utils/bbs_serializers.py`）。
- 所有写操作需 `@jwt_required()` 且校验 CSRF；角色权限使用 `@roles_required('operator')` / `@roles_required('admin')` 等组合实现。

| 接口 | 方法 | 描述 | 额外说明 |
| --- | --- | --- | --- |
| `/api/bbs/boards` | GET | 获取板块列表 | 支持`is_active`筛选 |
| `/api/bbs/posts` | GET | 获取主贴列表 | 筛选：`board_id`、`keyword`、`status`、`pilot_id`；排序：置顶优先，其次`last_active_at`逆序 |
| `/api/bbs/posts` | POST | 新建主贴 | body需包含`board_id/title/content` |
| `/api/bbs/posts/<id>` | GET | 获取主贴详情 | 返回主贴+回复、关联开播记录/主播信息 |
| `/api/bbs/posts/<id>` | PATCH | 编辑主贴 | 限作者或管理员 |
| `/api/bbs/posts/<id>/hide` | POST | 隐藏主贴 | 标记主贴及其全部回复为`hidden` |
| `/api/bbs/posts/<id>/unhide` | POST | 取消隐藏 | 仅管理员可见 |
| `/api/bbs/posts/<id>/pin` | POST | 置顶 | 带`is_pinned`布尔 |
| `/api/bbs/posts/<id>/replies` | POST | 新增回复 | 当`parent_reply_id`存在时即楼中楼 |
| `/api/bbs/replies/<id>` | PATCH | 编辑回复 | 限作者或管理员 |
| `/api/bbs/replies/<id>/hide` | POST | 隐藏回复 | 若父主贴被隐藏则无需额外处理 |
| `/api/bbs/posts/<id>/pilots` | PUT | 更新主播关联 | body为主播ID列表，区分`manual`标记 |
| `/api/bbs/pilots/<pilot_id>/recent` | GET | 获取主播相关主贴 | 返回最近更新的3条 |

错误场景统一返回`create_error_response(code, message)`，常见错误码建议：`BOARD_NOT_FOUND`、`POST_NOT_FOUND`、`PERMISSION_DENIED`、`REPLY_INVALID_PARENT` 等。

## 业务规则

### 1. 板块管理
- 默认为每个基地生成一个板块；当新增/禁用基地时，同步更新板块的`is_active`状态。
- 支持配置类板块（type=`custom`），由管理员在后台维护。

### 2. 发帖与编辑
- 运营/管理员可发帖；展示作者昵称（缺省回退用户名）与发布时间。
- 作者可在帖子详情弹窗中编辑标题、正文；编辑会刷新`last_active_at`。
- 隐藏帖子仅标记状态，不删除数据；隐藏了就不可恢复了没有恢复功能。
- 置顶只对所在板块生效，排序规则：置顶按`updated_at`逆序，其余按`last_active_at`逆序。

### 3. 回复层级
- 主贴下的顶级回复为楼层；楼层允许被再次回复形成楼中楼。
- `parent_reply_id`非空时必须指向同一主贴且是顶级回复，若传入楼中楼ID则报错`REPLY_INVALID_PARENT`。
- 楼层或楼中楼被隐藏后，其子楼中楼同步隐藏。

### 4. 隐藏逻辑
- 主贴隐藏：将主贴及所有关联回复标记为`hidden`，同时从列表、主播业绩聚合中排除。
- 所有隐藏操作记录操作人、时间，写入DEBUG日志。

## 与开播记录的联动

1. 触发时机：开播记录编辑保存后，若满足以下全部条件，则自动创建关联主贴：
   - 当前状态为“已下播”
   - 流水金额不为0
   - 备注非空
   - 尚无与该开播记录关联的主贴
2. 主贴内容模板：
   ```
   【开播记录】<主播昵称> 于 <日期 时段> 在 <基地-场地-坐席> 完成开播。
   流水：¥<金额>，底薪：¥<金额>。
   备注：<remark>
   ```
   - 主贴标题：`[开播记录] <主播昵称> <日期>`。
   - 主贴作者：系统账号 `system`，显示昵称“系统自动投稿”。
   - 关联字段：保存`related_battle_record_id`，并自动关联相关主播。
3. 主贴内提供“查看开播记录”按钮，点击跳转`/battle-records/<id>`（新窗口）。
4. 若同一开播记录已生成帖子，则不重复创建；后续备注或流水变化不会删除已生成帖子。

## UI 交互与复用

### BBS 列表页
- 左侧板块列表：展示可用板块及帖子数；切换板块时刷新帖子列表。
- 帖子卡片：显示标题、作者、发布时间、最后回复时间、回复总数、是否置顶；隐藏状态仅对作者和管理员显示灰色标签。
- 支持关键词搜索（标题/正文模糊匹配）与“仅看我的帖子”筛选。
- 点击帖子卡片任意位置即可打开通用的帖子详情弹出层。

### 帖子详情弹出层
- 顶部显示标题、作者、时间。
- 主体分为主贴内容、回复列表、回复输入框；楼中楼按缩进展示。关联区域统一提供“查看开播记录”“主播业绩”按钮，均以新窗口打开。
- 行为按钮：编辑、隐藏/取消隐藏、置顶（管理员）；作者看到的按钮仅限自己可操作范围。
- 提交回复后刷新当前弹窗数据，并触发列表中目标帖的`last_active_at`更新。
- 弹窗组件封装在`templates/bbs/post_detail_modal.html` + `static/js/bbs_post_detail.js`，在BBS列表页与主播业绩页复用。

### 主播业绩页联动
- 在主播信息卡片下方新增“相关讨论”模块，展示最近更新的3个主贴：
  - 数据来源：`GET /api/bbs/pilots/<pilot_id>/recent`。
  - 每条显示标题、所在板块、最后更新人和更新时间。
  - 支持一键打开对应帖子弹窗及“前往内部BBS”入口。

### 无独立帖子详情页
- 所有入口共用弹窗；
- 若用户从URL直接访问 `/bbs/posts/<id>`，前端路由重定向到列表页并自动打开对应弹窗。

## 日志与审计
- 新增 `log/bbs.log`，按自然日切分，记录模块整体操作。
- DEBUG 日志：发帖、编辑、隐藏、取消隐藏、置顶、自动创建帖子等操作的关键信息（操作者、目标ID、板块、结果）。
- INFO 日志仅在自动创建主贴和批量隐藏的少量重要事件触发。

## 权限与安全
- 访问帖子列表需登录；写操作需JWT认证 + CSRF（参考其他API）。
- 管理员：可编辑/隐藏任意帖子和回复、管理置顶。
- 运营：可创建/编辑/隐藏自己发布的帖子和回复，查看所有公开内容。
- 普通用户（若未来开放）：暂不设计
- 隐藏内容不可见，意味着隐藏不可恢复。

## 前后台开发约定
- 后端蓝图建议 `routes/bbs_api.py`，传统视图 `routes/bbs.py` 负责列表页渲染。
- 序列化与响应封装：新增 `utils/bbs_serializers.py`，提供帖子/回复的序列化函数，并在需要时补充分页`meta.pagination`数据。
- 模板/静态资源新增在 `templates/bbs/` 与 `static/js/bbs/`，注意遵循项目既有命名与打包方式。
- 单测：覆盖API的权限与关键流程；针对自动生成帖子写集成测试，验证备注为空时不创建。

## 后续扩展留口
- 预留“表情包”的扩展可能，虽然现在都是纯文本内容，但要准备好将来显示图文混排内容
- 板块分类与跨板块搜索：API层预留`scope`参数，便于后续扩展。

## 入口
- 主菜单： 首页的下方，BBS入口
- 主播业绩页：主播信息卡片下方

## 其他
- BBS主帖列表要处理分页，20条一页，采用滑动加载（滑到底部时加载下一页）。其他部分一律不处理分页
