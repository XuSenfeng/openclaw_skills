#!/usr/bin/env python3
"""
LIMO WebSocket Server
运行在小车（ROS 端），桥接 WebSocket 客户端与 ROS /cmd_vel 话题。

依赖安装（在小车上执行）：
    pip3 install websockets

启动方式：
    rosrun limo_remote limo_ws_server.py
  或直接运行：
    python3 limo_ws_server.py

WebSocket 端口：8765
"""

import asyncio
import base64
import json
import logging
import math
import os
import signal
import socket
import threading
import time

import rospy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import Imu
from sensor_msgs.msg import LaserScan

try:
    import actionlib
    from move_base_msgs.msg import MoveBaseAction, MoveBaseGoal
    from actionlib_msgs.msg import GoalStatus
    HAS_MOVE_BASE = True
except ImportError:
    HAS_MOVE_BASE = False

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

try:
    from limo_base.msg import LimoStatus
    HAS_LIMO_STATUS = True
except ImportError:
    HAS_LIMO_STATUS = False

import websockets
from sensor_msgs.msg import Image as RosImage
import threading


# 占位函数，防止空函数体导致 IndentationError
def _usb_cam_callback(msg: RosImage):
    pass

# 支持多摄像头话题缓存
_latest_image_by_topic = {}
_latest_image_locks = {}

def _usb_cam_callback_factory(topic_name):
    def _cb(msg: RosImage):
        lock = _latest_image_locks.setdefault(topic_name, threading.Lock())
        with lock:
            _latest_image_by_topic[topic_name] = msg
    return _cb

def get_latest_image(topic_name):
    lock = _latest_image_locks.setdefault(topic_name, threading.Lock())
    with lock:
        return _latest_image_by_topic.get(topic_name)


# ─────────────────────────────────────────────
# 配置
# ─────────────────────────────────────────────
WS_HOST = "0.0.0.0"   # 监听所有网卡，允许远端连接
WS_PORT = 8765

MAX_LINEAR_SPEED  = 1.0   # m/s
MAX_ANGULAR_SPEED = 2.0   # rad/s

CAMERA_DEVICE = 2
CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 720
CAMERA_WARMUP_FRAMES = 10
CAMERA_DEFAULT_JPEG_QUALITY = 85
CAMERA_BRIGHTNESS_ALPHA = 1.30
CAMERA_BRIGHTNESS_BETA = 30
CAMERA_GAMMA = 1.38
CAMERA_RED_GAIN = 1.18
CAMERA_GREEN_GAIN = 0.82
CAMERA_BLUE_GAIN = 1.06
CAMERA_LAB_CAST_STRENGTH = 1.35
CAMERA_CLAHE_CLIP_LIMIT = 2.8
CAMERA_CLAHE_TILE_SIZE = 8

logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("limo_ws_server")
# 第三方库的 DEBUG 日志太多，只保留 WARNING 以上
logging.getLogger("websockets").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

# ─────────────────────────────────────────────
# 全局共享状态（线程安全用锁）
# ─────────────────────────────────────────────
_lock = threading.Lock()
_robot_state = {
    "odom": {
        "x": 0.0, "y": 0.0, "yaw": 0.0,
        "vx": 0.0, "vy": 0.0, "vyaw": 0.0,
    },
    "imu": {"roll": 0.0, "pitch": 0.0, "yaw": 0.0},
    "status": {
        "vehicle_state": 0,
        "control_mode": 0,
        "battery_voltage": 0.0,
        "error_code": 0,
        "motion_mode": 0,
    },
    "scan": {
        "min_distance": None,
        "front_distance": None,
        "left_distance": None,
        "right_distance": None,
        "points": 0,
    },
    "connected_clients": 0,
    "timestamp": 0.0,
}

_cmd_vel_pub: rospy.Publisher = None
_connected_clients: set = set()
_ros_ready = threading.Event()   # ROS 初始化完成后 set()
_last_camera_debug = {}
_move_base_client = None
_move_base_lock = threading.Lock()


async def _run_blocking(func, *args, **kwargs):
    """Run blocking work in a thread, compatible with Python < 3.9."""
    if hasattr(asyncio, "to_thread"):
        return await asyncio.to_thread(func, *args, **kwargs)
    # Python 3.6 没有 get_running_loop，回退到 get_event_loop。
    try:
        loop = asyncio.get_running_loop()
    except AttributeError:
        loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))


# ─────────────────────────────────────────────
# ROS 回调
# ─────────────────────────────────────────────
def _yaw_from_quaternion(q):
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def odom_callback(msg: Odometry):
    yaw = _yaw_from_quaternion(msg.pose.pose.orientation)
    with _lock:
        _robot_state["odom"].update({
            "x":    round(msg.pose.pose.position.x, 4),
            "y":    round(msg.pose.pose.position.y, 4),
            "yaw":  round(math.degrees(yaw), 2),
            "vx":   round(msg.twist.twist.linear.x, 4),
            "vy":   round(msg.twist.twist.linear.y, 4),
            "vyaw": round(msg.twist.twist.angular.z, 4),
        })
        _robot_state["timestamp"] = time.time()


def imu_callback(msg: Imu):
    roll  = math.atan2(2*(msg.orientation.w*msg.orientation.x + msg.orientation.y*msg.orientation.z),
                       1 - 2*(msg.orientation.x**2 + msg.orientation.y**2))
    pitch = math.asin(max(-1.0, min(1.0, 2*(msg.orientation.w*msg.orientation.y
                                            - msg.orientation.z*msg.orientation.x))))
    yaw   = _yaw_from_quaternion(msg.orientation)
    with _lock:
        _robot_state["imu"].update({
            "roll":  round(math.degrees(roll), 2),
            "pitch": round(math.degrees(pitch), 2),
            "yaw":   round(math.degrees(yaw), 2),
        })


def status_callback(msg):
    with _lock:
        _robot_state["status"].update({
            "vehicle_state":  msg.vehicle_state,
            "control_mode":   msg.control_mode,
            "battery_voltage": round(msg.battery_voltage, 2),
            "error_code":     msg.error_code,
            "motion_mode":    msg.motion_mode,
        })


def _sector_min_distance(msg: LaserScan, center_rad: float, half_width_rad: float):
    values = []
    for i, r in enumerate(msg.ranges):
        if not math.isfinite(r) or r < msg.range_min or r > msg.range_max:
            continue
        angle = msg.angle_min + i * msg.angle_increment
        if abs(angle - center_rad) <= half_width_rad:
            values.append(r)
    return round(min(values), 3) if values else None


def _angle_diff(a: float, b: float) -> float:
    """Return smallest signed angle difference (a-b) within [-pi, pi]."""
    return math.atan2(math.sin(a - b), math.cos(a - b))


def _sector_min_distance_wrap(msg: LaserScan, center_rad: float, half_width_rad: float):
    """Sector min distance with angle wrapping, robust at +/-pi boundaries."""
    values = []
    for i, r in enumerate(msg.ranges):
        if not math.isfinite(r) or r < msg.range_min or r > msg.range_max:
            continue
        angle = msg.angle_min + i * msg.angle_increment
        if abs(_angle_diff(angle, center_rad)) <= half_width_rad:
            values.append(r)
    return round(min(values), 3) if values else None


def scan_callback(msg: LaserScan):
    valid_ranges = [
        r for r in msg.ranges
        if math.isfinite(r) and msg.range_min <= r <= msg.range_max
    ]

    # Front direction can differ by LiDAR mounting; try both 0 deg and 180 deg.
    front_0 = _sector_min_distance_wrap(msg, 0.0, math.radians(15.0))
    front_180 = _sector_min_distance_wrap(msg, math.pi, math.radians(15.0))
    if front_0 is None and front_180 is None:
        front = None
        front_basis_deg = None
    elif front_0 is None:
        front = front_180
        front_basis_deg = 180
    elif front_180 is None:
        front = front_0
        front_basis_deg = 0
    else:
        # Prefer the closer obstacle to keep the value conservative for teleop.
        front = front_0 if front_0 <= front_180 else front_180
        front_basis_deg = 0 if front_0 <= front_180 else 180

    left = _sector_min_distance_wrap(msg, math.radians(90.0), math.radians(15.0))
    right = _sector_min_distance_wrap(msg, math.radians(-90.0), math.radians(15.0))

    with _lock:
        _robot_state["scan"].update({
            "min_distance": round(min(valid_ranges), 3) if valid_ranges else None,
            "front_distance": front,
            "left_distance": left,
            "right_distance": right,
            "front_basis_deg": front_basis_deg,
            "points": len(msg.ranges),
        })
        _robot_state["timestamp"] = time.time()


# ─────────────────────────────────────────────
# 速度指令处理
# ─────────────────────────────────────────────
def _clamp(val, min_val, max_val):
    return max(min_val, min(max_val, val))


_last_nonzero_log = 0.0   # 限制非零指令日志频率

def publish_cmd_vel(linear_x: float, angular_z: float, linear_y: float = 0.0):
    """发布速度指令到 /cmd_vel，自动限速。"""
    global _last_nonzero_log

    if not _ros_ready.is_set():
        log.warning("⚠️  ROS 尚未就绪，等待中（最多 10s）…")
        if not _ros_ready.wait(timeout=10.0):
            log.error("❌ ROS 初始化超时！请确认 roscore 和 limo_start.launch 已在小车上运行。")
            return

    twist = Twist()
    twist.linear.x  = _clamp(linear_x,  -MAX_LINEAR_SPEED,  MAX_LINEAR_SPEED)
    twist.linear.y  = _clamp(linear_y,  -MAX_LINEAR_SPEED,  MAX_LINEAR_SPEED)
    twist.angular.z = _clamp(angular_z, -MAX_ANGULAR_SPEED, MAX_ANGULAR_SPEED)
    _cmd_vel_pub.publish(twist)

    # 仅在有非零速度时打印日志，且每 0.5s 最多一条，避免刷屏
    now = time.time()
    if (linear_x != 0 or angular_z != 0 or linear_y != 0) and (now - _last_nonzero_log > 0.5):
        log.info(f"▶ cmd_vel  lx={twist.linear.x:+.2f}  ly={twist.linear.y:+.2f}  az={twist.angular.z:+.2f}")
        _last_nonzero_log = now


def emergency_stop():
    publish_cmd_vel(0.0, 0.0, 0.0)
    log.warning("⛔ 紧急停止已触发！")


def _yaw_to_quaternion(yaw: float):
    half = yaw * 0.5
    return 0.0, 0.0, math.sin(half), math.cos(half)


def _build_move_base_goal(x: float, y: float, yaw: float, frame_id: str):
    goal = MoveBaseGoal()
    goal.target_pose.header.frame_id = frame_id
    goal.target_pose.header.stamp = rospy.Time.now()
    goal.target_pose.pose.position.x = x
    goal.target_pose.pose.position.y = y
    qx, qy, qz, qw = _yaw_to_quaternion(yaw)
    goal.target_pose.pose.orientation.x = qx
    goal.target_pose.pose.orientation.y = qy
    goal.target_pose.pose.orientation.z = qz
    goal.target_pose.pose.orientation.w = qw
    return goal


def _goal_status_to_text(status: int) -> str:
    if not HAS_MOVE_BASE:
        return "UNKNOWN"
    mapping = {
        GoalStatus.PENDING: "PENDING",
        GoalStatus.ACTIVE: "ACTIVE",
        GoalStatus.PREEMPTED: "PREEMPTED",
        GoalStatus.SUCCEEDED: "SUCCEEDED",
        GoalStatus.ABORTED: "ABORTED",
        GoalStatus.REJECTED: "REJECTED",
        GoalStatus.PREEMPTING: "PREEMPTING",
        GoalStatus.RECALLING: "RECALLING",
        GoalStatus.RECALLED: "RECALLED",
        GoalStatus.LOST: "LOST",
    }
    return mapping.get(status, "UNKNOWN")


def _parse_navigation_request(msg: dict):
    frame_id = str(msg.get("frame", "map"))
    timeout = float(msg.get("timeout", 120.0))
    if timeout <= 0:
        raise ValueError("timeout 必须大于 0")

    waypoints = msg.get("waypoints")
    if waypoints is not None:
        if not isinstance(waypoints, list) or not waypoints:
            raise ValueError("waypoints 必须是非空数组")
        goals = []
        for item in waypoints:
            if not isinstance(item, dict):
                raise ValueError("waypoints 中每一项都必须是对象")
            x = float(item["x"])
            y = float(item["y"])
            yaw = float(item.get("yaw", 0.0))
            goals.append((x, y, yaw))
    else:
        if "x" not in msg or "y" not in msg:
            raise ValueError("单点导航需要提供 x 和 y")
        goals = [(float(msg["x"]), float(msg["y"]), float(msg.get("yaw", 0.0)))]

    return goals, frame_id, timeout


def _run_navigation(goals, frame_id: str, timeout_s: float):
    if not HAS_MOVE_BASE:
        return {
            "success": False,
            "error": "缺少 move_base 相关依赖（move_base_msgs/actionlib）",
        }

    if not _ros_ready.is_set() and not _ros_ready.wait(timeout=10.0):
        return {
            "success": False,
            "error": "ROS 尚未就绪，无法执行导航",
        }

    if _move_base_client is None:
        return {
            "success": False,
            "error": "move_base 客户端未初始化",
        }

    with _move_base_lock:
        if not _move_base_client.wait_for_server(rospy.Duration(20.0)):
            return {
                "success": False,
                "error": "move_base action server 不可用，请先启动导航 launch",
            }

        reached = 0
        total = len(goals)
        for idx, (x, y, yaw) in enumerate(goals, start=1):
            if rospy.is_shutdown():
                return {
                    "success": False,
                    "error": "ROS 已关闭，导航中断",
                    "reached": reached,
                    "total": total,
                }

            goal = _build_move_base_goal(x, y, yaw, frame_id)
            _move_base_client.send_goal(goal)

            finished = _move_base_client.wait_for_result(rospy.Duration(timeout_s))
            if not finished:
                _move_base_client.cancel_goal()
                return {
                    "success": False,
                    "error": f"第 {idx}/{total} 个目标超时（>{timeout_s:.1f}s）",
                    "reached": reached,
                    "total": total,
                    "failed_index": idx,
                }

            status = _move_base_client.get_state()
            if status != GoalStatus.SUCCEEDED:
                return {
                    "success": False,
                    "error": f"第 {idx}/{total} 个目标失败: {_goal_status_to_text(status)}",
                    "reached": reached,
                    "total": total,
                    "failed_index": idx,
                    "status": _goal_status_to_text(status),
                }

            reached += 1

        return {
            "success": True,
            "message": "导航完成",
            "reached": reached,
            "total": total,
            "frame": frame_id,
        }


def _decode_fourcc(value: float) -> str:
    """Decode OpenCV numeric fourcc value to a 4-char string."""
    i = int(value)
    return "".join(chr((i >> (8 * k)) & 0xFF) for k in range(4))


def _frame_green_cast_score(frame):
    """Lower score means less green cast and a more plausible decode."""
    if frame is None or len(frame.shape) != 3 or frame.shape[2] != 3:
        return float("inf")
    b_mean, g_mean, r_mean = [float(x) for x in cv2.mean(frame)[:3]]
    return abs(g_mean - (r_mean + b_mean) / 2.0)


def _try_decode_candidates(frame, candidates):
    best_name = None
    best_frame = None
    best_score = float("inf")

    for name, code in candidates:
        try:
            decoded = cv2.cvtColor(frame, code)
        except Exception:
            continue
        score = _frame_green_cast_score(decoded)
        if score < best_score:
            best_name = name
            best_frame = decoded
            best_score = score

    return best_name, best_frame, best_score


def _raw_yuv_to_bgr(frame, fourcc: str):
    """Convert raw camera frame to BGR and auto-correct likely channel mismatches."""
    global _last_camera_debug

    fourcc = (fourcc or "").strip()
    debug = {
        "input_shape": list(frame.shape) if hasattr(frame, "shape") else None,
        "reported_fourcc": fourcc,
    }

    if len(frame.shape) == 3 and frame.shape[2] == 2:
        candidates = []
        if fourcc in ("YUYV", "YUY2", "YUNV"):
            candidates.extend([
                ("YUYV", cv2.COLOR_YUV2BGR_YUY2),
                ("YVYU", cv2.COLOR_YUV2BGR_YVYU),
                ("UYVY", cv2.COLOR_YUV2BGR_UYVY),
            ])
        elif fourcc == "YVYU":
            candidates.extend([
                ("YVYU", cv2.COLOR_YUV2BGR_YVYU),
                ("YUYV", cv2.COLOR_YUV2BGR_YUY2),
                ("UYVY", cv2.COLOR_YUV2BGR_UYVY),
            ])
        elif fourcc == "UYVY":
            candidates.extend([
                ("UYVY", cv2.COLOR_YUV2BGR_UYVY),
                ("YUYV", cv2.COLOR_YUV2BGR_YUY2),
                ("YVYU", cv2.COLOR_YUV2BGR_YVYU),
            ])
        else:
            candidates.extend([
                ("YUYV", cv2.COLOR_YUV2BGR_YUY2),
                ("YVYU", cv2.COLOR_YUV2BGR_YVYU),
                ("UYVY", cv2.COLOR_YUV2BGR_UYVY),
            ])

        chosen_name, chosen_frame, chosen_score = _try_decode_candidates(frame, candidates)
        debug.update({
            "decode_mode": chosen_name,
            "green_cast_score": round(chosen_score, 3) if math.isfinite(chosen_score) else None,
        })
        _last_camera_debug = debug
        if chosen_frame is not None:
            return chosen_frame

    if len(frame.shape) == 2:
        bayer_candidates = [
            ("BAYER_BG", cv2.COLOR_BAYER_BG2BGR),
            ("BAYER_GB", cv2.COLOR_BAYER_GB2BGR),
            ("BAYER_RG", cv2.COLOR_BAYER_RG2BGR),
            ("BAYER_GR", cv2.COLOR_BAYER_GR2BGR),
        ]
        chosen_name, chosen_frame, chosen_score = _try_decode_candidates(frame, bayer_candidates)
        debug.update({
            "decode_mode": chosen_name,
            "green_cast_score": round(chosen_score, 3) if math.isfinite(chosen_score) else None,
        })
        _last_camera_debug = debug
        if chosen_frame is not None:
            return chosen_frame

    debug["decode_mode"] = "passthrough"
    _last_camera_debug = debug
    return frame


def _gray_world_white_balance(frame):
    """Simple gray-world white balance to mitigate green cast."""
    b, g, r = cv2.split(frame)
    mb = float(b.mean())
    mg = float(g.mean())
    mr = float(r.mean())
    m = (mb + mg + mr) / 3.0 if (mb + mg + mr) > 0 else 1.0

    kb = m / max(mb, 1e-6)
    kg = m / max(mg, 1e-6)
    kr = m / max(mr, 1e-6)

    b = cv2.convertScaleAbs(b, alpha=kb)
    g = cv2.convertScaleAbs(g, alpha=kg)
    r = cv2.convertScaleAbs(r, alpha=kr)
    return cv2.merge([b, g, r])


def _lab_color_cast_correction(frame, strength: float = CAMERA_LAB_CAST_STRENGTH):
    """Correct green/magenta cast in LAB space while preserving luminance."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB).astype("float32")
    l_chan, a_chan, b_chan = cv2.split(lab)

    avg_a = float(a_chan.mean())
    avg_b = float(b_chan.mean())
    l_scale = l_chan / 255.0

    a_chan -= (avg_a - 128.0) * l_scale * strength
    b_chan -= (avg_b - 128.0) * l_scale * strength

    a_chan = cv2.min(cv2.max(a_chan, 0), 255)
    b_chan = cv2.min(cv2.max(b_chan, 0), 255)
    corrected = cv2.merge([l_chan, a_chan, b_chan]).astype("uint8")
    return cv2.cvtColor(corrected, cv2.COLOR_LAB2BGR)


def _apply_channel_gains(frame):
    """Apply a small warm bias to counter residual green cast from the sensor."""
    b_chan, g_chan, r_chan = cv2.split(frame)
    b_chan = cv2.convertScaleAbs(b_chan, alpha=CAMERA_BLUE_GAIN)
    g_chan = cv2.convertScaleAbs(g_chan, alpha=CAMERA_GREEN_GAIN)
    r_chan = cv2.convertScaleAbs(r_chan, alpha=CAMERA_RED_GAIN)
    return cv2.merge([b_chan, g_chan, r_chan])


def _apply_gamma(frame, gamma: float = CAMERA_GAMMA):
    """Lift midtones to reduce the dark look without overexposing highlights."""
    if gamma <= 0:
        return frame
    import numpy as np
    inv_gamma = 1.0 / gamma
    table = [
        min(255, max(0, int(((i / 255.0) ** inv_gamma) * 255.0 + 0.5)))
        for i in range(256)
    ]
    lut = np.array(table, dtype=np.uint8)
    return cv2.LUT(frame, lut)


def _apply_clahe_brightness(frame):
    """Enhance local brightness/contrast on the luminance channel."""
    lab = cv2.cvtColor(frame, cv2.COLOR_BGR2LAB)
    l_chan, a_chan, b_chan = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=CAMERA_CLAHE_CLIP_LIMIT,
        tileGridSize=(CAMERA_CLAHE_TILE_SIZE, CAMERA_CLAHE_TILE_SIZE),
    )
    l_chan = clahe.apply(l_chan)
    return cv2.cvtColor(cv2.merge([l_chan, a_chan, b_chan]), cv2.COLOR_LAB2BGR)


def capture_usb_cam_jpeg_base64(quality: int = CAMERA_DEFAULT_JPEG_QUALITY, camera_topic: str = "/usb_cam/image_raw"):
    """从最近一帧 camera_topic 获取图片并转为JPEG base64"""
    if not HAS_CV2:
        raise RuntimeError("OpenCV 未安装，请先在小车安装 python3-opencv 或 pip3 install opencv-python")
    msg = get_latest_image(camera_topic)
    if msg is None:
        raise RuntimeError(f"未收到 {camera_topic} 图像，请检查摄像头驱动和话题发布")
    import numpy as np
    if msg.encoding not in ("bgr8", "rgb8"):
        raise RuntimeError(f"暂不支持的图像编码: {msg.encoding}, 仅支持bgr8/rgb8")
    img_np = np.frombuffer(msg.data, dtype=np.uint8).reshape((msg.height, msg.width, 3))
    if msg.encoding == "rgb8":
        img_np = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
    frame = img_np
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("JPEG 编码失败")
    b64 = base64.b64encode(encoded.tobytes()).decode("ascii")
    h, w = frame.shape[:2]
    return b64, w, h


# ─────────────────────────────────────────────
# WebSocket 处理器
# ─────────────────────────────────────────────
async def push_state_loop(websocket):
    """每 100ms 向客户端推送一次机器人状态。"""
    try:
        while True:
            with _lock:
                payload = {
                    "type": "state",
                    "data": dict(_robot_state),
                }
            payload["data"]["connected_clients"] = len(_connected_clients)
            await websocket.send(json.dumps(payload))
            await asyncio.sleep(0.1)
    except (websockets.exceptions.ConnectionClosed, asyncio.CancelledError):
        pass


async def handle_message(websocket, raw: str):
    """
    解析并处理客户端消息。

    支持的消息类型（JSON）：
        {"type": "cmd_vel",  "linear_x": 0.5, "angular_z": 0.3}
        {"type": "cmd_vel",  "linear_x": 0.0, "angular_z": 0.0, "linear_y": 0.0}
        {"type": "stop"}
        {"type": "ping"}
        {"type": "get_image", "quality": 85}
    """
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        await websocket.send(json.dumps({"type": "error", "msg": "JSON 解析失败"}))
        return

    msg_type = msg.get("type", "")

    if msg_type == "cmd_vel":
        lx  = float(msg.get("linear_x",  0.0))
        az  = float(msg.get("angular_z", 0.0))
        ly  = float(msg.get("linear_y",  0.0))
        log.debug(f"收到 cmd_vel: lx={lx:+.3f}  az={az:+.3f}  ly={ly:+.3f}")
        publish_cmd_vel(lx, az, ly)

    elif msg_type == "stop":
        log.info("收到 stop 指令")
        emergency_stop()
        await websocket.send(json.dumps({"type": "ack", "msg": "已停止"}))

    elif msg_type == "ping":
        await websocket.send(json.dumps({"type": "pong", "ts": time.time()}))

    elif msg_type == "get_image":
        quality = int(msg.get("quality", CAMERA_DEFAULT_JPEG_QUALITY))
        quality = max(30, min(95, quality))
        camera_topic = msg.get("camera_topic", "/usb_cam/image_raw")
        try:
            data_b64, width, height = await _run_blocking(capture_usb_cam_jpeg_base64, quality, camera_topic)
            await websocket.send(json.dumps({
                "type": "image",
                "format": "jpeg",
                "encoding": "base64",
                "quality": quality,
                "width": width,
                "height": height,
                "ts": time.time(),
                "camera_debug": _last_camera_debug,
                "data": data_b64,
            }))
        except Exception as e:
            log.error(f"获取图像失败: {e}")
            await websocket.send(json.dumps({"type": "error", "msg": f"获取图像失败: {e}"}))

    elif msg_type == "navigate":
        try:
            goals, frame_id, timeout_s = _parse_navigation_request(msg)
        except Exception as e:
            await websocket.send(json.dumps({"type": "error", "msg": f"导航参数错误: {e}"}))
            return

        log.info(
            "收到导航请求: goals=%d frame=%s timeout=%.1fs",
            len(goals),
            frame_id,
            timeout_s,
        )
        try:
            result = await _run_blocking(_run_navigation, goals, frame_id, timeout_s)
            await websocket.send(json.dumps({"type": "nav_result", **result}))
        except Exception as e:
            log.exception("导航执行异常")
            await websocket.send(json.dumps({"type": "error", "msg": f"导航执行异常: {e}"}))

    else:
        log.warning(f"未知消息类型: {msg_type}  raw={raw[:80]}")
        await websocket.send(json.dumps({"type": "error", "msg": f"未知消息类型: {msg_type}"}))


async def client_handler(websocket, path=None):
    client_addr = websocket.remote_address
    log.info(f"客户端连接: {client_addr}")
    _connected_clients.add(websocket)

    push_task = asyncio.ensure_future(push_state_loop(websocket))

    try:
        async for raw in websocket:
            await handle_message(websocket, raw)
    except websockets.exceptions.ConnectionClosed:
        pass
    finally:
        push_task.cancel()
        _connected_clients.discard(websocket)
        emergency_stop()   # 客户端断开时自动停车
        log.info(f"客户端断开: {client_addr}")


# ─────────────────────────────────────────────
# ROS 节点初始化（在子线程中 spin）
# ─────────────────────────────────────────────
def _check_rosmaster() -> bool:
    """用 TCP socket 测试 rosmaster 端口是否可达，避免 rospy.init_node 挂起。"""
    master_uri = os.environ.get("ROS_MASTER_URI", "http://localhost:11311")
    try:
        # 解析 URI：http://host:port
        host = master_uri.split("//")[-1].split(":")[0]
        port = int(master_uri.split(":")[-1].rstrip("/"))
    except Exception:
        host, port = "localhost", 11311

    log.info(f"检查 ROS Master: {master_uri}  ({host}:{port})")
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
        log.info("✅ ROS Master 端口可达")
        return True
    except OSError as e:
        log.error(f"❌ 无法连接 ROS Master ({host}:{port}): {e}")
        log.error("   请在小车上先执行:  roslaunch limo_bringup limo_start.launch")
        return False


def ros_init():

    global _cmd_vel_pub, _move_base_client
    # 支持多摄像头话题
    camera_topics = ["/usb_cam/image_raw", "/usb_cam_0/image_raw", "/usb_cam_1/image_raw", "/usb_cam_2/image_raw"]
    for topic in camera_topics:
        rospy.Subscriber(topic, RosImage, _usb_cam_callback_factory(topic), queue_size=1)

    # 先检查 rosmaster 端口，防止 init_node 无限挂起
    if not _check_rosmaster():
        log.error("ROS Master 不可达，ROS 初始化放弃。")
        return

    try:
        # disable_signals=True：信号处理只能在主线程注册，子线程必须禁用
        rospy.init_node("limo_ws_server", anonymous=False, disable_signals=True)
    except Exception as e:
        log.error(f"❌ rospy.init_node 失败: {type(e).__name__}: {e}")
        return

    _cmd_vel_pub = rospy.Publisher("/cmd_vel", Twist, queue_size=10)
    if HAS_MOVE_BASE:
        _move_base_client = actionlib.SimpleActionClient("move_base", MoveBaseAction)
    else:
        log.warning("move_base 依赖未安装，导航功能不可用。")

    rospy.Subscriber("/odom",   Odometry, odom_callback,   queue_size=5)
    rospy.Subscriber("/imu",    Imu,      imu_callback,    queue_size=5)
    rospy.Subscriber("/scan",   LaserScan, scan_callback,  queue_size=2)

    if HAS_LIMO_STATUS:
        rospy.Subscriber("/limo_status", LimoStatus, status_callback, queue_size=5)
    else:
        log.warning("limo_base.msg.LimoStatus 未找到，跳过状态订阅。")

    _ros_ready.set()   # 通知主线程 ROS 已就绪
    log.info("✅ ROS 节点已就绪，Publisher/Subscriber 全部创建完成")

    # 启动后 3 秒做一次话题诊断
    def _check_topics():
        time.sleep(3.0)
        published = [t for t, _ in rospy.get_published_topics()]
        for topic in ["/odom", "/imu", "/scan", "/limo_status", "/cmd_vel"]:
            s = "✅" if topic in published else "❌ 未发布"
            log.info(f"  话题检查  {topic}: {s}")
        if "/odom" not in published:
            log.warning("⚠️  /odom 话题不存在，请确认 limo_start.launch 已启动！")

    threading.Thread(target=_check_topics, daemon=True).start()

    rospy.spin()


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────
def main():
    ros_thread = threading.Thread(target=ros_init, daemon=True)
    ros_thread.start()

    log.info("等待 ROS 节点初始化…")
    if not _ros_ready.wait(timeout=15.0):
        log.error("❌ 等待 ROS 超时（15s），请检查 roscore 是否运行。WebSocket 仍会启动，但发布功能不可用。")
    else:
        log.info("✅ ROS 就绪，启动 WebSocket 服务器")

    log.info(f"WebSocket 服务器启动于 ws://{WS_HOST}:{WS_PORT}")
    log.info("等待远端客户端连接……")

    loop = asyncio.get_event_loop()
    start_server = websockets.serve(client_handler, WS_HOST, WS_PORT)
    loop.run_until_complete(start_server)

    def _shutdown(signum, frame):
        log.info("收到退出信号，正在关闭…")
        emergency_stop()
        rospy.signal_shutdown("用户终止")
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGINT,  _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        emergency_stop()
        log.info("服务器已关闭。")


if __name__ == "__main__":
    main()
