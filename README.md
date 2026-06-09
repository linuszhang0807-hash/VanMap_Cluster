# VanMap 大温城市情报中心

大温地区餐厅、酒吧、娱乐、景点、徒步与活动的地图化情报平台。

## 项目结构

```
VanMap_Cluster/
├── data/                    # 唯一权威数据源 ✅
│   ├── master_data.json
│   ├── events_data.json
│   ├── SCHEMA.md
│   └── SOURCES.md
├── docs/                    # CHANGELOG, FEATURES
├── scripts/sync_data.*      # data/ → 前端同步
├── slave_scraper/           # 采集工厂
├── slave_coder/src/         # Leaflet 前端
└── master_hermes/           # 调度 + Discord Bot
```

## 快速启动

### 1. 安装依赖

```bash
cd slave_scraper
pip install -r requirements.txt
cp ../.env.example ../.env   # 可选：填入 YOUTUBE_API_KEY
```

### 2. 采集数据

```bash
cd slave_scraper
python vancouver_scraper.py --sync
python events_scraper.py --sync
```

默认 `VANMAP_SCRAPE_MODE=osm`（OpenStreetMap Overpass）。强制 Mock：`python vancouver_scraper.py --mock`

### 3. 同步到前端（Scraper --sync 已自动执行时可跳过）

```powershell
.\scripts\sync_data.ps1
```

### 4. 启动网页

```bash
cd slave_coder/src
python -m http.server 8080
```

- 首页：http://localhost:8080/index_home.html
- 地图：http://localhost:8080/index.html?type=活动

## 云端部署

GitHub Pages 工作流：`.github/workflows/deploy.yml`  
每周活动刷新：`.github/workflows/refresh-events.yml`

## Discord 调度（Phase 4）

```bash
cd master_hermes
set DISCORD_BOT_TOKEN=your_token
python discord_bot.py
```

命令：`!vanmap 更新大温活动数据` 或 `!refresh_events`

## 版本

当前版本见 [VERSION](VERSION)，变更见 [docs/CHANGELOG.md](docs/CHANGELOG.md)。
