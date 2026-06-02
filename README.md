# VanMap 大温美食情报中心

## 项目结构
- `slave_scraper/`: 数据采集工厂。运行 `python vancouver_scraper.py` 生成 JSON。
- `slave_coder/`: 前端展示平台。读取 `src/shared_data/` 下的 JSON 进行渲染。

## 快速启动
1. 爬取数据: `cd slave_scraper && python vancouver_scraper.py`
2. 同步数据: 将生成的 JSON 覆盖到 `slave_coder/src/shared_data/`
3. 启动网页: 在 `slave_coder/` 目录下运行 `python -m http.server 8080`