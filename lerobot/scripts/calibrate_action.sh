#!/bin/zsh

# Optional positional arguments:
# 1) follower robot port (default: /dev/tty.usbmodem5AA90243381)
# 2) leader robot port (default: /dev/tty.usbmodem5AA90242591)
FOLLOWER_PORT="${1:-/dev/tty.usbmodem5AA90243381}"
LEADER_PORT="${2:-/dev/tty.usbmodem5AA90242591}"

# ============= 关键修复：强制加载 Conda 配置（解决非交互式运行问题） =============
CONDA_BASE=$(conda info --base 2>/dev/null)
if [ -z "$CONDA_BASE" ]; then
    CONDA_BASE="$HOME/miniconda3"
    if [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        CONDA_BASE="$HOME/anaconda3"
    fi

    if [ ! -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
        echo "❌ 错误：未找到 Conda 安装路径，请先安装并初始化 Conda！"
        echo "尝试的路径：$CONDA_BASE"
        exit 1
    fi
fi

# 加载 Conda 核心配置
if [ -f "$CONDA_BASE/etc/profile.d/conda.sh" ]; then
    source "$CONDA_BASE/etc/profile.d/conda.sh"
else
    echo "❌ 错误：Conda 配置文件不存在，请重新执行 conda init zsh！"
    exit 1
fi

# ============= 切换到 lerobot 目录并激活环境 =============
echo "🔍 切换到 lerobot 目录：/Users/jiao/JHY/python/lerobot"
cd /Users/jiao/JHY/python/lerobot || {
    echo "❌ 错误：无法切换到目录 /Users/jiao/JHY/python/lerobot，请检查路径是否正确！"
    exit 1
}

echo "🔧 激活 lerobot Conda 环境..."
conda activate lerobot || {
    echo "❌ 错误：无法激活 lerobot 环境！请执行 conda env list 检查环境是否存在。"
    exit 1
}

# ============= 校准 follower =============
echo "🛠️ 开始校准 follower 机械臂..."
echo "🔌 follower 端口：$FOLLOWER_PORT"
lerobot-calibrate \
  --robot.type=so101_follower \
  --robot.port="$FOLLOWER_PORT" \
  --robot.id=my_awesome_follower_arm

FOLLOWER_EXIT_CODE=$?
if [ $FOLLOWER_EXIT_CODE -ne 0 ]; then
    echo "❌ follower 校准失败，退出码：$FOLLOWER_EXIT_CODE"
    conda deactivate
    exit $FOLLOWER_EXIT_CODE
fi

echo "✅ follower 校准完成"

# ============= 校准 leader =============
echo "🛠️ 开始校准 leader 机械臂..."
echo "🔌 leader 端口：$LEADER_PORT"
lerobot-calibrate \
  --robot.type=so101_leader \
  --robot.port="$LEADER_PORT" \
  --robot.id=my_awesome_leader_arm

LEADER_EXIT_CODE=$?
if [ $LEADER_EXIT_CODE -eq 0 ]; then
    echo "✅ leader 校准完成"
    echo "✅ 所有机械臂校准成功！"
else
    echo "❌ leader 校准失败，退出码：$LEADER_EXIT_CODE"
fi

conda deactivate
exit $LEADER_EXIT_CODE
