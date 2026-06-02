import json
import os

task_path = os.path.join(os.path.dirname(__file__), "shared_data", "task.json")

with open(task_path, "r", encoding="utf-8") as f:
    task = json.load(f)

project_name = task["project_name"]
center = task["center_location"]
lat = center["lat"]
lng = center["lng"]

print(f"项目名称: {project_name}")
print(f"地图中心坐标: 纬度 {lat}, 经度 {lng}")
