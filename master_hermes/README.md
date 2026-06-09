# 主控调度中心 (Master Hermes)

本模块是 VanMap Cluster 的**主控 Agent**，负责接收人类高层指令、进行思维链推理（CoT）、拆解任务并派发工单。它不直接采集数据，也不修改前端代码。

## 在集群中的位置

```
人类指令
    ↓
master_hermes/          ← 本模块（Hermes Master）
    ↓ order_box/task.json
slave_coder/            ← 代码子 Agent 读取工单并执行
slave_scraper/          ← 数据采集工厂（独立运行）
```

| 模块 | 职责 |
|---|---|
| **Master Hermes** | 指令理解、任务拆解、工单派发 |
| **Slave Scraper** | 采集、清洗、输出 JSON |
| **Slave Coder** | Leaflet 地图 + 侧边栏展示 |

## 核心职责

- **接收指令**：解析自然语言商业意图（如「大温中餐/韩餐地图框架」）
- **CoT 推理**：判断任务应派发给哪个子部门
- **工单打包**：按 `MapTaskContract` 严格格式化输出
- **状态切换**：写入发件箱后等待子 Agent 读取并部署

### 禁止事项

- 不直接修改 `slave_scraper/` 或 `slave_coder/` 代码
- 不采集数据、不渲染 UI
- 唯一输出路径为 `order_box/task.json`

## 目录结构

```
master_hermes/
├── master_brain.py       # HermesMaster 主控逻辑
├── order_box/
│   └── task.json         # 工单发件箱（子 Agent 读取）
└── README.md
```

## 快速运行

```bash
cd master_hermes
python master_brain.py
```

Windows PowerShell：

```powershell
cd e:\AI_Project1_Web\VanMap_Cluster\master_hermes
python master_brain.py
```

默认会模拟一条人类指令并写入工单：

```
帮我规划和更新一下大温城市的中餐和韩餐地图框架
```

## 工单 Schema（MapTaskContract）

工单由 Pydantic 模型 `MapTaskContract` 约束，字段如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `command` | `string` | 给子 Agent 的执行指令 |
| `project_name` | `string` | 项目名称 |
| `center_location` | `object` | 地图中心坐标，含 `lat` / `lng` |
| `status` | `string` | 工单状态，默认 `INIT` |

示例输出（`order_box/task.json`）：

```json
{
  "command": "CREATE_MAP_FRAMEWORK",
  "project_name": "Vancouver Food & Fun Map",
  "center_location": {
    "lat": 49.2827,
    "lng": -123.1207
  },
  "status": "INIT"
}
```

## 指令映射规则（当前版本）

| 触发关键词 | 派发部门 | command | 中心点 |
|---|---|---|---|
| 中餐 / 韩餐 / 地图 | 代码部门 | `CREATE_MAP_FRAMEWORK` | 温哥华 Downtown `49.2827, -123.1207` |
| 其他 | — | 拒绝派发 | — |

中心点锁定为温哥华市中心，确保地图框架始终以 Downtown 为默认视野。

## 架构要点

### `HermesMaster` 类

```python
class HermesMaster:
    def plan_and_dispatch(self, user_intent: str)  # 接收指令 → 推理 → 派发
    def _write_to_order_box(self, task: MapTaskContract)  # 写入 task.json
```

### 状态机流程

```
INIT（写入工单）
    ↓
等待 slave_coder 读取 task.json 并执行 CREATE_MAP_FRAMEWORK
    ↓
（未来扩展）DONE / FAILED 等状态回写
```

## 与子 Agent 的协作

1. **Master** 将工单写入 `order_box/task.json`
2. **Slave Coder**（或专用调度脚本）轮询/读取该文件
3. 子 Agent 根据 `command` 字段执行对应操作（如搭建地图底层框架）
4. 执行完成后可回写 `status` 字段（待实现）

当前 `slave_coder` 尚未接入工单读取逻辑；工单机制为架构预留，便于后续多 Agent 自动化协作。

## 依赖

- Python 3.10+
- [Pydantic](https://docs.pydantic.dev/) v2（`BaseModel`, `Field`）

安装示例：

```bash
pip install pydantic
```

## 开发备忘

- 修改 `order_box_path` 时注意 Windows 绝对路径与跨机部署
- 扩展指令映射时同步更新 `MapTaskContract` 及本文档
- 新增 `command` 类型需与 `slave_coder` 执行端约定一致
- 集群整体说明见 [VanMap_Cluster/README.md](../README.md)
