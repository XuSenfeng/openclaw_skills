---
name: ROS-limo-car
description: 用于控制 LIMO 机器人的 skill。可获取机器人状态（里程计/激光雷达/电池）、控制运动（前进/后退/转向）、执行单点或多点导航、拍照。通过 limo_ws_client.py 工具脚本调用，所有输出为 JSON 格式。
---

# ROS-limo-car 技能

## 工具脚本

所有操作通过 `scripts/limo_ws_client.py` 完成，**输出均为 JSON**，便于 AI 直接解析。

脚本需在 **`mqtt-server`** conda 环境中运行。推荐使用 `conda run`（无需手动激活环境）：

```bash
TOOL="conda run -n mqtt-server python3 ~/.openclaw/skills/ROS-limo-car/scripts/limo_ws_client.py"
```

若 `conda run` 不可用，可手动激活环境后执行：

```bash
# 激活 conda 环境
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -z "$CONDA_BASE" ]; then
    CONDA_BASE="$HOME/miniconda3"
    [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ] && CONDA_BASE="$HOME/anaconda3"
fi
source "$CONDA_BASE/etc/profile.d/conda.sh"
conda activate mqtt-server

TOOL="python3 ~/.openclaw/skills/ROS-limo-car/scripts/limo_ws_client.py"
```

---

## 获取小车状态

```bash
$TOOL get_state
```

返回示例：
```json
{
  "success": true,
  "odom": {"x": 0.12, "y": -0.03, "yaw": 5.1, "vx": 0.0, "vyaw": 0.0},
  "scan": {"min_distance": 0.45, "front_distance": 1.2, "left_distance": 0.8, "right_distance": 0.6, "points": 360},
  "status": {"battery_voltage": 12.3, "motion_mode": 0, "motion_mode_name": "差速(diff)", "error_code": 0},
  "connected_clients": 1
}
```

---

## 控制运动

```bash
# 前进 0.5 m/s，持续 2 秒
$TOOL move --linear-x 0.5 --duration 2.0

# 后退 0.3 m/s，持续 1.5 秒
$TOOL move --linear-x -0.3 --duration 1.5

# 左转（角速度 1.0 rad/s），持续 1 秒
$TOOL move --angular-z 1.0 --duration 1.0

# 右转同时前进
$TOOL move --linear-x 0.3 --angular-z -0.5 --duration 2.0

# 横向平移（麦轮模式）
$TOOL move --linear-y 0.3 --duration 1.0
```

参数说明：
| 参数 | 含义 | 正值 | 负值 |
|---|---|---|---|
| `--linear-x` | 前后速度 (m/s) | 前进 | 后退 |
| `--angular-z` | 转向角速度 (rad/s) | 左转 | 右转 |
| `--linear-y` | 横向速度 (m/s，仅麦轮) | 左平移 | 右平移 |
| `--duration` | 持续时间 (秒) | — | — |

---

## 紧急停车

```bash
$TOOL stop
```

---

## 导航

支持通过 WebSocket 调用 move_base 执行单点导航或多点导航。

单点导航：

```bash
# 导航到 map 坐标系下 (1.0, 0.5)，朝向 1.57 rad
$TOOL navigate --x 1.0 --y 0.5 --yaw 1.57

# 指定每个目标点超时时间为 90 秒
$TOOL navigate --x 2.0 --y -0.3 --yaw 0.0 --timeout 90

# 指定导航坐标系
$TOOL navigate --frame map --x 0.0 --y 0.0 --yaw 3.14
```

多点导航：

```bash
$TOOL navigate --waypoints "1.0,0.0,0; 1.0,1.0,1.57; 0.0,0.0,3.14"
```

参数说明：

| 参数 | 含义 |
|---|---|
| `--x` | 单点导航目标 x 坐标 |
| `--y` | 单点导航目标 y 坐标 |
| `--yaw` | 目标朝向，单位 rad，默认 0 |
| `--waypoints` | 多点导航列表，格式为 `"x,y,yaw; x,y,yaw; ..."` |
| `--frame` | 导航目标坐标系，默认 `map` |
| `--timeout` | 每个目标点的超时时间，单位秒，默认 120 |

成功返回示例：

```json
{
  "success": true,
  "message": "导航完成",
  "frame": "map",
  "reached": 3,
  "total": 3
}
```

失败返回示例：

```json
{
  "success": false,
  "error": "导航失败",
  "reached": 1,
  "total": 3,
  "failed_index": 2,
  "status": 4
}
```

说明：

- 单点导航需提供 `--x` 和 `--y`，`--yaw` 可省略
- 多点导航时，`--waypoints` 中每个点都必须是 `x,y,yaw` 三元组
- 实际等待超时会根据目标点数量自动放大，无需手动计算总超时
- 使用前需确保车端导航相关 ROS 节点和 move_base 已正常启动

---



## 获取摄像头图片

```bash
$TOOL get_image
# 或指定本地保存路径和压缩质量
$TOOL get_image --output /tmp/limo_cam.jpg --quality 80
# 选择不同摄像头话题（如有多路摄像头）
$TOOL get_image --camera-topic /usb_cam_1/image_raw --output /tmp/cam1.jpg
```

说明：
- 该命令通过 WebSocket 请求服务器，服务器会返回最近一帧指定 ROS 话题（如 `/usb_cam/image_raw`、`/usb_cam_0/image_raw`、`/usb_cam_1/image_raw` 等）的图片（JPEG 格式，base64 编码），并保存到本地。
- 支持 `--output` 指定保存路径，`--quality` 指定 JPEG 压缩质量（30-95，默认85）。
- 支持 `--camera-topic` 选择摄像头 ROS 话题，默认 `/usb_cam/image_raw`。
- 若长时间未收到图片，请检查小车端对应话题是否正常发布。

返回示例：
```json
{
  "success": true,
  "message": "已通过 WebSocket 获取图像",
  "local_path": "/tmp/limo_cam.jpg",
  "width": 1280,
  "height": 720,
  "quality": 85,
  "ts": 1710750000.123
}
```

---

## 拍照（通过SSH远程触发）

```bash
$TOOL take_photo
# 或指定本地保存路径
$TOOL take_photo --output /tmp/limo_photo.jpg
```

返回：
```json
{"success": true, "local_path": "/tmp/limo_photo.jpg", "remote_path": "/home/agilex/Desktop/color_photo_fixed.jpg"}
```

拍照成功后，使用以下方式查看图片：

```bash
# 在终端预览（需 imgcat，适用于 iTerm2）
imgcat /tmp/limo_photo.jpg

# 用系统默认应用打开
open /tmp/limo_photo.jpg

# 若使用了自定义路径，替换为对应路径
open <local_path>
```

AI 处理图片时，可直接将 `local_path` 作为图片文件路径传入图像分析工具。

> 依赖 `sshpass`，macOS 安装：`brew install hudochenkov/sshpass/sshpass`

---

## 连接配置

默认连接参数（无需手动指定）：
- WebSocket：`ws://10.218.99.91:8765`
- SSH：`agilex@10.218.99.91`（密码 `agx`）

如需更改：
```bash
$TOOL --host <IP> --port <PORT> get_state
$TOOL --host <IP> take_photo --ssh-host <SSH_IP>
```

### 环境启动

在连接到小车的终端上，需先启动 ROS 节点和 WebSocket 服务：

建图：

```bash
roslaunch limo_bringup limo_start.launch
roslaunch limo_bringup limo_teletop_keyboard.launch
# 建图
roslaunch limo_bringup limo_cartographer.launch
# 记录地图
rosrun map_server map_saver -f ~/maps/limo_map
```

导航：

```bash
roslaunch limo_bringup limo_start.launch
rosrun map_server map_server ~/maps/limo_map.yaml
# 需要在有屏幕的地方
roslaunch limo_bringup limo_navigation_diff.launch
```

控制服务器:

```bash
python3 limo_ws_server.py
```

说明：

- 建图阶段先启动底盘，再启动键盘遥控，随后运行 cartographer 进行环境建图
- 保存地图后，导航阶段需要先加载对应的地图 yaml 文件
- `limo_navigation_diff.launch` 需要图形界面环境，因此需要在有屏幕的地方启动
- 实际启动服务之前需要查看是否已经启动了相关的 ROS 节点，特别是 move_base 和 WebSocket 服务节点

---

## 注意事项

- 使用前确保 ROS 节点已在小车上启动（WebSocket 服务运行在 8765 端口）
- 激光雷达 `scan.front_distance` 单位为米，可用于避障判断
- `status.error_code != 0` 时表示小车存在故障
- 摄像头：video0/video1 为深度相机，video2 为 RGB 相机