

# OpenClaw 技能仓库

本仓库包含用于控制机器人硬件的技能集合，包括 LIMO 移动机器人和 LeRobot 机械臂的控制脚本。

## 项目结构

```
.
├── ROS-limo-car/          # LIMO 机器人控制技能
│   ├── SKILL.md          # 技能说明文档
│   └── scripts/          # 脚本目录
│       ├── limo_ws_client.py  # WebSocket 客户端
│       └── limo_ws_server.py  # WebSocket 服务器
└── lerobot/              # 机械臂控制技能
    ├── SKILL.md          # 技能说明文档
    ├── assets/           # 资源文件
    └── scripts/          # 脚本目录
        ├── calibrate_action.sh   # 校准脚本
        ├── play_action.sh        # 动作播放脚本
        ├── recoeding_action.sh   # 动作录制脚本
        └── teleoperate_action.sh # 跟随控制脚本
```

## 功能特性

### ROS-limo-car（LIMO 机器人）

- **状态获取**：里程计、激光雷达、电池信息
- **运动控制**：前进、后退、转向、横向平移（麦轮模式）
- **导航功能**：单点/多点导航，支持自定义坐标系
- **摄像头**：获取图像、拍照功能

### lerobot（机械臂）

- **动作录制**：录制机械臂动作数据集
- **动作播放**：回放录制的动作序列
- **跟随控制**：Leader-Follower 模式的实时控制
- **校准功能**：校准机械臂端口

## 环境要求

- ROS (Robot Operating System)
- Python 3.8+
- Conda 环境

## 快速开始

### LIMO 机器人

```bash
# 激活 conda 环境
conda activate limo

# 获取小车状态
python limo_ws_client.py --host 192.168.x.x --get-state

# 前进 0.5 m/s，持续 2 秒
python limo_ws_client.py --host 192.168.x.x --move 0.5 0

# 导航到指定位置
python limo_ws_client.py --host 192.168.x.x --navigate 1.0 0.5 1.57
```

### 机械臂

```bash
# 激活 lerobot 环境
conda activate lerobot

# 校准机械臂
./scripts/calibrate_action.sh

# 动作录制
./scripts/recoeding_action.sh --dataset-name so101_try_001

# 动作播放
./scripts/play_action.sh

# 跟随控制
./scripts/teleoperate_action.sh
```

## 详细文档

- [ROS-limo-car 技能说明](./ROS-limo-car/SKILL.md)
- [lerobot 技能说明](./lerobot/SKILL.md)

## 注意事项

1. 使用前请确保网络连接正常
2. 机械臂控制需要正确的端口配置
3. 导航功能需要在有屏幕的环境下运行
4. 建议首次使用前进行设备校准