# VanMap 展示平台 (Coder Module)

本模块负责大温地区情报数据的视觉化呈现与用户交互，采用 **Ins Creamy White** 奶白风格，基于 Leaflet 地图 + 侧边栏列表的双栏布局。

## 页面结构

| 文件 | 说明 |
|---|---|
| `src/index_home.html` | 几何切片首页，按类目导航至地图页 |
| `src/index.html` | 主地图应用（筛选、搜索、弹窗、照片合集） |

## 核心职责

- **多类目统一渲染**：餐厅、酒吧、娱乐、徒步、景点、活动共用一套 Popup / 侧边栏卡片模板
- **高级筛选**：类目筛选 + 餐厅子类目（中餐/韩餐/日料）+ 地区交集筛选（AND 逻辑）
- **智能搜索**：地图顶部搜索栏，支持 `flyTo` 定位并打开弹窗
- **评分排序**：默认按 `aggregate_score` 降序
- **悬停预览**：侧边栏卡片 Hover 显示详情浮层
- **照片合集 Lightbox**：弹窗内照片条点击打开模态框，支持分类 Tab、网格缩略图、大图轮播
- **官网跳转**：弹窗 Header 区域点击跳转 `official_website`（有值时显示手形光标与 ↗ 图标）

## 快速部署

1. **进入前端目录**（数据路径为相对路径 `./shared_data/`，必须从 `src/` 启动服务）：

   ```bash
   cd src
   python -m http.server 8080
   ```

2. **访问**：
   - 首页：`http://localhost:8080/index_home.html`
   - 地图页：`http://localhost:8080/index.html`
   - 带类目参数：`http://localhost:8080/index.html?type=活动`

## 数据源

前端通过 `Promise.all` 并行加载以下两个文件：

| 文件 | 内容 |
|---|---|
| `src/shared_data/restaurants.json` | 餐厅数据（中餐/韩餐子类） |
| `src/shared_data/master_data.json` | 酒吧、娱乐、景点、徒步等主数据 |

另有 `src/shared_data/events_data.json`（活动专题数据，由 `events_scraper.py` 生成），**当前尚未接入 `index.html` 加载逻辑**。若「活动」筛选无数据，需将活动条目合并进 `master_data.json`，或在 `index.html` 中增加对 `events_data.json` 的 fetch。

### ⚠️ 数据同步注意事项

项目中存在多份数据副本，**浏览器实际读取的是 `src/shared_data/` 下的文件**：

```
src/master_data.json          ← 开发/备份副本
src/shared_data/master_data.json  ← HTTP 服务实际提供 ✅
shared_data/master_data.json      ← 仓库根目录副本
```

Scraper 更新数据后，务必同步到 `src/shared_data/`，否则前端不会反映最新内容。

## 数据 Schema（关键字段）

### 通用字段（所有类目）

```json
{
  "name": "The Keefer Bar",
  "category": "酒吧",
  "address": "...",
  "lat": 49.28, "lng": -123.10,
  "url": "https://www.google.com/maps/...",
  "official_website": "https://thekeeferbar.com/",
  "description": "...",
  "image_url": null,
  "photos": [
    { "category": "吧台环境", "url": "https://..." },
    { "category": "招牌特调", "url": "https://..." }
  ],
  "keywords": ["..."],
  "videos": [{ "platform": "YouTube", "url": "...", "summary": "..." }],
  "reviews": [{ "platform": "Google Review", "text": "...", "source_url": "..." }],
  "rating_system": {
    "aggregate_score": 4.6,
    "google_rating": 4.6,
    "xiaohongshu": 4.5,
    "review_count": 780
  }
}
```

### 活动类目扩展字段

```json
{
  "category": "活动",
  "event_date": "2026年6月19日–6月28日",
  "venue": "David Lam Park",
  "event_type": "音乐节 / 爵士乐",
  "admission": "部分场次免费，付费票 $35–$120"
}
```

规范化后写入 `_activity` 对象，用于弹窗 Header 日期行、侧边栏 quickStat 与详情板块。

## 前端架构要点

### 数据规范化

| 函数 | 用途 |
|---|---|
| `normalizeRestaurantEntry()` | 将 `restaurants.json` 条目转为与主数据相同的对象结构 |
| `normalizeMasterEntry()` | 统一 `social_metrics` / `rating_system` / `photos` 等 schema 变体 |

两类数据合并为 `allData`，下游 `buildPopup`、`buildCard`、`buildSocialLinks` 等函数完全复用。

### 弹窗 (Popup)

- **Header**：有 `official_website` 时可点击，`window.open()` 新标签打开
- **照片条**：Bento 网格（最多预览 3 张），点击打开 Lightbox
- **评价模块**：Google Review + 小红书，含源链接
- **社交链接**：TikTok / YouTube（侧边栏与弹窗均不显示「官方网站」「Google Maps」按钮）

### 照片合集 (Lightbox)

- 触发：弹窗内照片条 `onclick → __lb.open(idx)`
- Tab 筛选：「全部」+ 各 `photos[].category`
- 网格缩略图 → 点击全屏预览，支持 ← → 键与按钮翻页
- 关闭：Esc / 点击遮罩 / 右上角 ✕

### 照片 URL 与降级策略

`getPhotos(r)` 处理逻辑：

1. 有条目 `photos[]` → 逐条检测 URL 可靠性
2. 无 `photos[]` → 按类目生成内联 SVG 占位图（无需外网）
3. 图片加载失败 → `onerror` 回退至 `fallbackUrl`

**已知问题**：Scraper 生成的 `lh5.googleusercontent.com/p/AF1Qip…` 类 URL 为占位 ID，实测返回 HTTP 400，无法直接热链。前端会自动降级为 SVG 占位图（显示分类名称）。要显示真实照片，Scraper 需提供可访问 URL 或将图片下载至本地路径（如 `./assets/photos/xxx.jpg`）。

## 类目与配色

| 类目 | 主色 | Emoji |
|---|---|---|
| 中餐 | `#c96b52` | 🥢 |
| 韩餐 | `#5b87b0` | 🥩 |
| 酒吧 | `#7c52a8` | 🍺 |
| 娱乐 | `#2d7d9a` | 🎭 |
| 徒步 | `#2d6a4f` | 🥾 |
| 景点 | `#a07c10` | 📸 |
| 活动 | `#be185d` | 🎪 |

## 筛选与排序逻辑

- **类目**：`state.type` 匹配 `r.type`（餐厅为 `"餐厅"`，其余与 `category` 一致）
- **子类目**（仅餐厅）：`state.subtype` 匹配 `r.category`（中餐/韩餐/日料）
- **地区**：`state.district` 匹配 `r.district`
- **排序**：`aggregate_score` 降序

## 开发备忘

- 修改 `index.html` 后需硬刷新（`Ctrl+Shift+R`）避免浏览器缓存
- 弹窗内 `<a>` 标签可能被 Leaflet 事件拦截，Header 官网跳转使用 `div + onclick + window.open()`
- `window.__lbData[]` 在每次 `buildPopup` 时按索引存储照片数据，供 Lightbox 引用
