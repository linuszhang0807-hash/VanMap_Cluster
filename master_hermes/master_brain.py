import json
import os
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
# 2. 🌟 Master Agent 主控逻辑核心
# ==========================================
class HermesMaster:
    def __init__(self):
        # 锁定发件箱物理路径
        self.order_box_path = r"E:\AI_Project1_Web\VanMap_Cluster\master_hermes\order_box"

    def plan_and_dispatch(self, user_intent: str):
        print(f"\n📡 [Master Hermes]: 接收到人类最高指令 -> '{user_intent}'")
        print("🧠 [Master Hermes]: 正在进行思维链推理（CoT）...")
        
        # 纯业务逻辑判断：如果指令包含中餐/韩餐/地图，自动拆解并指派给代码部门
        if "中餐" in user_intent or "韩餐" in user_intent or "地图" in user_intent:
            print("💡 [Master Hermes 决策]: 判断此任务需要【代码部门】先搭建大温地图底层框架。")
            
            # 严格打包工单
            task_data = MapTaskContract(
                command="CREATE_MAP_FRAMEWORK",
                project_name="Vancouver Food & Fun Map",
                center_location={"lat": 49.2827, "lng": -123.1207} # 锁死温哥华Downtown中心点
            )
            
            self._write_to_order_box(task_data)
        else:
            print("❌ [Master Hermes 错误]: 无法识别的商业指令，拒绝派发。")

    def _write_to_order_box(self, task: MapTaskContract):
        file_name = "task.json"
        full_path = os.path.join(self.order_box_path, file_name)
        
        # 转换为干净的 JSON 写入文件
        with open(full_path, 'w', encoding='utf-8') as f:
            json.dump(task.model_dump(), f, indent=2, ensure_ascii=False)
            
        print(f"📦 [Master Hermes]: 工单已成功送达发件箱！物理路径: {full_path}")
        print("⏳ [Master Hermes]: 状态机已切换为：等待代码子 Agent 读取并部署...")

if __name__ == "__main__":
    master = HermesMaster()
    # 模拟你未来给它的聊天输入
    user_command = "帮我规划和更新一下大温城市的中餐和韩餐地图框架"
    master.plan_and_dispatch(user_command)