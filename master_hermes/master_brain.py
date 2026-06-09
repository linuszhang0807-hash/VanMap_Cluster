import json
import os
from pathlib import Path

from pydantic import BaseModel, Field

# ==========================================
# 1. 架构级定义：严格限制 Master 派发工单的格式
# ==========================================
class MapTaskContract(BaseModel):
    command: str = Field(..., description="给子Agent的指令")
    project_name: str = Field(..., description="项目名称")
    center_location: dict = Field(..., description="包含 lat 和 lng 的温哥华坐标")
    status: str = Field(default="INIT", description="工单状态")


# ==========================================
# 2. Master Agent 主控逻辑核心
# ==========================================
class HermesMaster:
    def __init__(self) -> None:
        self.order_box_path = str(Path(__file__).resolve().parent / "order_box")

    def plan_and_dispatch(self, user_intent: str) -> None:
        print(f"\n[Master Hermes]: 接收到人类最高指令 -> '{user_intent}'")
        print("[Master Hermes]: 正在进行思维链推理（CoT）...")

        intent = user_intent.lower()
        command = self._resolve_command(user_intent, intent)
        if not command:
            print("[Master Hermes 错误]: 无法识别的商业指令，拒绝派发。")
            return

        print(f"[Master Hermes 决策]: 派发 command={command}")

        task_data = MapTaskContract(
            command=command,
            project_name="Vancouver Food & Fun Map",
            center_location={"lat": 49.2827, "lng": -123.1207},
        )
        self._write_to_order_box(task_data)

    def _resolve_command(self, user_intent: str, intent: str) -> str | None:
        if any(k in user_intent for k in ("活动", "event")) or "events" in intent:
            return "RUN_EVENTS_SCRAPER"
        if any(k in user_intent for k in ("同步", "sync", "部署")):
            return "SYNC_DATA"
        if any(k in user_intent for k in ("全量", "全部", "刷新", "更新")) and any(
            k in user_intent for k in ("数据", "地图", "网站")
        ):
            return "FULL_REFRESH"
        if any(k in user_intent for k in ("采集", "爬虫", "scraper", "餐厅", "酒吧")):
            return "RUN_PLACE_SCRAPER"
        if any(k in user_intent for k in ("中餐", "韩餐", "地图", "框架")):
            return "CREATE_MAP_FRAMEWORK"
        return None

    def _write_to_order_box(self, task: MapTaskContract) -> None:
        os.makedirs(self.order_box_path, exist_ok=True)
        full_path = os.path.join(self.order_box_path, "task.json")
        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(task.model_dump(), f, indent=2, ensure_ascii=False)
        print(f"[Master Hermes]: 工单已成功送达发件箱！物理路径: {full_path}")
        print("[Master Hermes]: 状态机已切换为 INIT — 等待 task_runner 执行...")


if __name__ == "__main__":
    master = HermesMaster()
    user_command = "帮我更新一下大温活动数据"
    master.plan_and_dispatch(user_command)
