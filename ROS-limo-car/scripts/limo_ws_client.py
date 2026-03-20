#!/usr/bin/env python3
"""
LIMO 机器人 AI 工具脚本

供 AI Agent 通过命令行调用，所有输出均为 JSON 格式，便于程序解析。

依赖安装：
    pip3 install websockets

子命令：
    get_state    获取机器人当前完整状态（里程计 / 激光雷达 / 电池 / 运动模式等）
    move         控制机器人按指定速度移动一段时间后自动停车
    stop         立即发送零速指令，使机器人停止
    get_image    通过 WebSocket 直接获取小车摄像头图像并保存到本地
    take_photo   远程触发拍照并将图片 scp 到本地

用法示例：
    python3 limo_ws_client.py get_state
    python3 limo_ws_client.py get_state --host 192.168.0.5 --port 8765

    python3 limo_ws_client.py move --linear-x 0.5 --duration 2.0
    python3 limo_ws_client.py move --angular-z 1.0 --duration 1.5
    python3 limo_ws_client.py move --linear-x 0.3 --angular-z 0.5 --duration 3.0

    python3 limo_ws_client.py stop

    python3 limo_ws_client.py get_image
    python3 limo_ws_client.py get_image --output /tmp/limo_cam.jpg --quality 80

    python3 limo_ws_client.py take_photo
    python3 limo_ws_client.py take_photo --output /tmp/limo_photo.jpg

    python3 limo_ws_client.py navigate --x 1.0 --y 0.5 --yaw 1.57
    python3 limo_ws_client.py navigate --waypoints "1.0,0.0,0; 1.0,1.0,1.57; 0.0,0.0,3.14"

所有命令成功时输出：{"success": true, ...}
失败时输出：        {"success": false, "error": "..."}
"""

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
from typing import List, Tuple

import websockets

# ─────────────────────────────────────────────
# 默认配置
# ─────────────────────────────────────────────
DEFAULT_WS_HOST = "192.168.0.5"
DEFAULT_WS_PORT = 8765
DEFAULT_SSH_HOST = "192.168.0.5"
DEFAULT_SSH_USER = "agilex"
DEFAULT_SSH_PASS = "agx"
REMOTE_PHOTO_CMD = "python3 /home/agilex/catkin_ws/take_photo.py"
REMOTE_PHOTO_PATH = "/home/agilex/Desktop/color_photo_fixed.jpg"


def _out(obj: dict):
    """将结果以 JSON 格式输出到 stdout 并退出。"""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# ─────────────────────────────────────────────
# WebSocket 工具函数
# ─────────────────────────────────────────────
async def _connect(host: str, port: int):
    uri = f"ws://{host}:{port}"
    return await websockets.connect(uri, ping_interval=5, ping_timeout=10)


async def _send_cmd_vel(
    ws,
    linear_x: float = 0.0,
    angular_z: float = 0.0,
    linear_y: float = 0.0,
):
    msg = json.dumps(
        {
            "type": "cmd_vel",
            "linear_x": linear_x,
            "angular_z": angular_z,
            "linear_y": linear_y,
        }
    )
    await ws.send(msg)


async def _recv_state(ws, timeout: float = 3.0) -> dict:
    """等待并返回服务端推送的第一条 state 消息数据。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError("未在规定时间内收到状态消息")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        if msg.get("type") == "state":
            return msg["data"]


async def _recv_image_or_error(ws, timeout: float = 8.0) -> dict:
    """等待服务端返回 image，若收到 error 则抛出异常。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError("未在规定时间内收到图像消息")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        mtype = msg.get("type")
        if mtype == "image":
            return msg
        if mtype == "error":
            raise RuntimeError(msg.get("msg", "服务端返回错误"))


async def _recv_nav_result_or_error(ws, timeout: float) -> dict:
    """等待导航结果消息，忽略中间 state 推送。"""
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise TimeoutError("未在规定时间内收到导航结果")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        msg = json.loads(raw)
        mtype = msg.get("type")
        if mtype == "nav_result":
            return msg
        if mtype == "error":
            raise RuntimeError(msg.get("msg", "服务端返回错误"))


def _parse_waypoints(text: str) -> List[Tuple[float, float, float]]:
    """Parse waypoints text: 'x,y,yaw; x,y,yaw; ...'."""
    points = []
    for item in text.split(";"):
        item = item.strip()
        if not item:
            continue
        parts = [p.strip() for p in item.split(",")]
        if len(parts) != 3:
            raise ValueError("Each waypoint must be x,y,yaw")
        x, y, yaw = map(float, parts)
        points.append((x, y, yaw))
    if not points:
        raise ValueError("No valid waypoint found")
    return points


# ─────────────────────────────────────────────
# 子命令实现
# ─────────────────────────────────────────────
async def cmd_get_state(args):
    """连接、接收一次状态快照、断开。"""
    try:
        ws = await _connect(args.host, args.port)
        async with ws:
            state = await _recv_state(ws, timeout=5.0)

        status = state.get("status", {})
        motion_modes = {0: "差速(diff)", 1: "阿克曼(ackermann)", 2: "麦轮(mecanum)"}
        mode_name = motion_modes.get(status.get("motion_mode", -1), "未知")

        _out(
            {
                "success": True,
                "odom": state.get("odom", {}),
                "imu": state.get("imu", {}),
                "scan": state.get("scan", {}),
                "status": {
                    **status,
                    "motion_mode_name": mode_name,
                },
                "connected_clients": state.get("connected_clients"),
            }
        )
    except TimeoutError as e:
        _out({"success": False, "error": str(e)})
    except (ConnectionRefusedError, OSError) as e:
        _out({"success": False, "error": f"WebSocket 连接失败: {e}"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


async def cmd_move(args):
    """发送速度指令持续 duration 秒，结束后发送停车指令，返回运动概要。"""
    try:
        ws = await _connect(args.host, args.port)
        async with ws:
            try:
                state_before = await _recv_state(ws, timeout=3.0)
            except TimeoutError:
                state_before = {}

            end_time = asyncio.get_event_loop().time() + args.duration
            while asyncio.get_event_loop().time() < end_time:
                await _send_cmd_vel(
                    ws,
                    linear_x=args.linear_x,
                    angular_z=args.angular_z,
                    linear_y=args.linear_y,
                )
                await asyncio.sleep(0.05)

            await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
            await asyncio.sleep(0.1)

            try:
                state_after = await _recv_state(ws, timeout=3.0)
            except TimeoutError:
                state_after = {}

        _out(
            {
                "success": True,
                "command": {
                    "linear_x": args.linear_x,
                    "angular_z": args.angular_z,
                    "linear_y": args.linear_y,
                    "duration": args.duration,
                },
                "odom_before": state_before.get("odom", {}),
                "odom_after": state_after.get("odom", {}),
            }
        )
    except (ConnectionRefusedError, OSError) as e:
        _out({"success": False, "error": f"WebSocket 连接失败: {e}"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


async def cmd_stop(args):
    """发送零速指令使机器人立即停止。"""
    try:
        ws = await _connect(args.host, args.port)
        async with ws:
            await _send_cmd_vel(ws, 0.0, 0.0, 0.0)
            await asyncio.sleep(0.1)
        _out({"success": True, "message": "已发送停车指令"})
    except (ConnectionRefusedError, OSError) as e:
        _out({"success": False, "error": f"WebSocket 连接失败: {e}"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


async def cmd_get_image(args):
    """通过 WebSocket 请求一帧图像并写入本地文件。"""
    try:
        ws = await _connect(args.host, args.port)
        async with ws:
            req = {"type": "get_image", "quality": int(args.quality)}
            if hasattr(args, "camera_topic") and args.camera_topic:
                req["camera_topic"] = args.camera_topic
            await ws.send(json.dumps(req))
            msg = await _recv_image_or_error(ws, timeout=12.0)

        img_b64 = msg.get("data")
        if not img_b64:
            raise RuntimeError("图像数据为空")

        img_bytes = base64.b64decode(img_b64)
        output_path = args.output
        parent = os.path.dirname(output_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(img_bytes)

        _out(
            {
                "success": True,
                "message": "已通过 WebSocket 获取图像",
                "local_path": output_path,
                "width": msg.get("width"),
                "height": msg.get("height"),
                "quality": msg.get("quality"),
                "ts": msg.get("ts"),
            }
        )
    except TimeoutError as e:
        _out({"success": False, "error": str(e)})
    except (ConnectionRefusedError, OSError) as e:
        _out({"success": False, "error": f"WebSocket 连接失败: {e}"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


async def cmd_navigate(args):
    """通过 WebSocket 请求 move_base 导航（单点/多点）。"""
    try:
        if args.waypoints:
            goals = _parse_waypoints(args.waypoints)
            nav_req = {
                "type": "navigate",
                "frame": args.frame,
                "timeout": args.timeout,
                "waypoints": [
                    {"x": x, "y": y, "yaw": yaw}
                    for x, y, yaw in goals
                ],
            }
        else:
            if args.x is None or args.y is None:
                raise ValueError("请提供 --x --y，或使用 --waypoints")
            goals = [(args.x, args.y, args.yaw)]
            nav_req = {
                "type": "navigate",
                "frame": args.frame,
                "timeout": args.timeout,
                "x": args.x,
                "y": args.y,
                "yaw": args.yaw,
            }

        wait_timeout = max(10.0, args.timeout * max(1, len(goals)) + 5.0)

        ws = await _connect(args.host, args.port)
        async with ws:
            await ws.send(json.dumps(nav_req))
            nav_result = await _recv_nav_result_or_error(ws, timeout=wait_timeout)

        if nav_result.get("success"):
            _out(
                {
                    "success": True,
                    "message": nav_result.get("message", "导航完成"),
                    "frame": nav_result.get("frame", args.frame),
                    "reached": nav_result.get("reached"),
                    "total": nav_result.get("total"),
                }
            )
        else:
            _out(
                {
                    "success": False,
                    "error": nav_result.get("error", "导航失败"),
                    "reached": nav_result.get("reached"),
                    "total": nav_result.get("total"),
                    "failed_index": nav_result.get("failed_index"),
                    "status": nav_result.get("status"),
                }
            )
    except TimeoutError as e:
        _out({"success": False, "error": str(e)})
    except (ConnectionRefusedError, OSError) as e:
        _out({"success": False, "error": f"WebSocket 连接失败: {e}"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


def cmd_take_photo(args):
    """SSH 触发拍照，然后 scp 图片到本地。"""
    ssh_target = f"{args.ssh_user}@{args.ssh_host}"
    scp_src = f"{ssh_target}:{REMOTE_PHOTO_PATH}"
    local_out = args.output

    try:
        result = subprocess.run(
            [
                "sshpass",
                "-p",
                args.ssh_pass,
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                ssh_target,
                REMOTE_PHOTO_CMD,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            _out({"success": False, "error": f"拍照命令失败: {result.stderr.strip()}"})
            return

        result = subprocess.run(
            [
                "sshpass",
                "-p",
                args.ssh_pass,
                "scp",
                "-o",
                "StrictHostKeyChecking=no",
                scp_src,
                local_out,
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0:
            _out({"success": False, "error": f"图片传输失败: {result.stderr.strip()}"})
            return

        _out(
            {
                "success": True,
                "local_path": local_out,
                "remote_path": REMOTE_PHOTO_PATH,
            }
        )
    except FileNotFoundError:
        _out(
            {
                "success": False,
                "error": "未找到 sshpass，请先安装: brew install hudochenkov/sshpass/sshpass",
            }
        )
    except subprocess.TimeoutExpired:
        _out({"success": False, "error": "SSH/SCP 操作超时"})
    except Exception as e:
        _out({"success": False, "error": str(e)})


# ─────────────────────────────────────────────
# 命令行入口
# ─────────────────────────────────────────────
def main():
    root = argparse.ArgumentParser(
        description="LIMO 机器人 AI 工具 - 所有输出为 JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    root.add_argument(
        "--host", default=DEFAULT_WS_HOST, help=f"WebSocket 服务器 IP（默认 {DEFAULT_WS_HOST}）"
    )
    root.add_argument(
        "--port", default=DEFAULT_WS_PORT, type=int, help=f"WebSocket 端口（默认 {DEFAULT_WS_PORT}）"
    )

    sub = root.add_subparsers(dest="command", required=True)

    sub.add_parser("get_state", help="获取机器人当前状态快照")

    p_move = sub.add_parser("move", help="控制机器人运动指定时间后停车")
    p_move.add_argument(
        "--linear-x", default=0.0, type=float, help="前进/后退速度 m/s（正=前进，负=后退，默认 0）"
    )
    p_move.add_argument(
        "--angular-z", default=0.0, type=float, help="转向角速度 rad/s（正=左转，负=右转，默认 0）"
    )
    p_move.add_argument(
        "--linear-y", default=0.0, type=float, help="横向速度 m/s，仅麦轮模式有效（默认 0）"
    )
    p_move.add_argument("--duration", default=1.0, type=float, help="持续时间 秒（默认 1.0）")

    sub.add_parser("stop", help="立即停止机器人")

    p_image = sub.add_parser("get_image", help="通过 WebSocket 获取一帧摄像头图像")
    p_image.add_argument("--output", default="/tmp/limo_ws_image.jpg", help="本地保存路径（默认 /tmp/limo_ws_image.jpg）")
    p_image.add_argument("--quality", default=85, type=int, help="JPEG 压缩质量 30-95（默认 85）")
    p_image.add_argument("--camera-topic", default="/usb_cam/image_raw", help="摄像头ROS话题名，如 /usb_cam_0/image_raw")

    p_nav = sub.add_parser("navigate", help="通过 move_base 执行单点或多点导航")
    p_nav.add_argument("--frame", default="map", help="导航目标坐标系（默认 map）")
    p_nav.add_argument("--timeout", default=120.0, type=float, help="每个目标点超时秒数（默认 120）")
    p_nav.add_argument("--x", type=float, help="单点导航 x")
    p_nav.add_argument("--y", type=float, help="单点导航 y")
    p_nav.add_argument("--yaw", default=0.0, type=float, help="单点导航 yaw(rad)，默认 0")
    p_nav.add_argument(
        "--waypoints",
        type=str,
        default="",
        help='多点导航，格式: "x,y,yaw; x,y,yaw; ..."',
    )

    p_photo = sub.add_parser("take_photo", help="拍照并传输到本地")
    p_photo.add_argument("--output", default="/tmp/limo_photo.jpg", help="本地保存路径（默认 /tmp/limo_photo.jpg）")
    p_photo.add_argument("--ssh-host", default=DEFAULT_SSH_HOST, help=f"SSH 主机 IP（默认 {DEFAULT_SSH_HOST}）")
    p_photo.add_argument("--ssh-user", default=DEFAULT_SSH_USER, help=f"SSH 用户名（默认 {DEFAULT_SSH_USER}）")
    p_photo.add_argument("--ssh-pass", default=DEFAULT_SSH_PASS, help="SSH 密码（默认 agx）")

    args = root.parse_args()

    if args.command == "get_state":
        asyncio.run(cmd_get_state(args))
    elif args.command == "move":
        asyncio.run(cmd_move(args))
    elif args.command == "stop":
        asyncio.run(cmd_stop(args))
    elif args.command == "get_image":
        asyncio.run(cmd_get_image(args))
    elif args.command == "navigate":
        asyncio.run(cmd_navigate(args))
    elif args.command == "take_photo":
        cmd_take_photo(args)


if __name__ == "__main__":
    main()
