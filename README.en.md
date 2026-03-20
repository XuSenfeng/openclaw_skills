# OpenClaw Skill Repository

This repository contains a collection of skills for controlling robot hardware, including control scripts for the LIMO mobile robot and the LeRobot arm.

## Project Structure

```
.
├── ROS-limo-car/          # LIMO robot control skills
│   ├── SKILL.md          # Skill documentation
│   └── scripts/          # Scripts directory
│       ├── limo_ws_client.py  # WebSocket client
│       └── limo_ws_server.py  # WebSocket server
└── lerobot/              # Arm control skills
    ├── SKILL.md          # Skill documentation
    ├── assets/           # Asset files
    └── scripts/          # Scripts directory
        ├── calibrate_action.sh   # Calibration script
        ├── play_action.sh        # Action playback script
        ├── recoeding_action.sh   # Action recording script
        └── teleoperate_action.sh # Teleoperation script
```

## Features

### ROS-limo-car (LIMO Robot)

- **State Retrieval**: Odometry, LiDAR, battery information
- **Motion Control**: Forward, backward, turning, lateral translation (in mecanum wheel mode)
- **Navigation**: Single-point and multi-point navigation with support for custom coordinate systems
- **Camera**: Image acquisition and photo capture functionality

### lerobot (Arm)

- **Action Recording**: Record action datasets for the robotic arm
- **Action Playback**: Replay recorded action sequences
- **Teleoperation**: Real-time Leader-Follower control mode
- **Calibration**: Calibrate arm ports

## System Requirements

- ROS (Robot Operating System)
- Python 3.8+
- Conda environment

## Quick Start

### LIMO Robot

```bash
# Activate conda environment
conda activate limo

# Get robot state
python limo_ws_client.py --host 192.168.x.x --get-state

# Move forward at 0.5 m/s for 2 seconds
python limo_ws_client.py --host 192.168.x.x --move 0.5 0

# Navigate to specified position
python limo_ws_client.py --host 192.168.x.x --navigate 1.0 0.5 1.57
```

### Arm

```bash
# Activate lerobot environment
conda activate lerobot

# Calibrate the arm
./scripts/calibrate_action.sh

# Record actions
./scripts/recoeding_action.sh --dataset-name so101_try_001

# Play back actions
./scripts/play_action.sh

# Teleoperate
./scripts/teleoperate_action.sh
```

## Detailed Documentation

- [ROS-limo-car Skill Documentation](./ROS-limo-car/SKILL.md)
- [lerobot Skill Documentation](./lerobot/SKILL.md)

## Notes

1. Ensure network connectivity is stable before use.
2. Correct port configuration is required for arm control.
3. Navigation functionality requires a display environment.
4. It is recommended to perform device calibration before first use.