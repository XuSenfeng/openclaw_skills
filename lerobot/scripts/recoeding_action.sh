#!/bin/zsh

# Optional positional arguments:
# 1) dataset name (default: so101_try_001)
# 2) single task text (default: pick and place test)
# 3) follower robot port (default: /dev/tty.usbmodem5AA90243381)
# 4) leader teleop port (default: /dev/tty.usbmodem5AA90242591)
DATASET_NAME="${1:-so101_try_001}"
SINGLE_TASK="${2:-pick and place test}"
ROBOT_PORT="${3:-/dev/tty.usbmodem5AA90243381}"
TELEOP_PORT="${4:-/dev/tty.usbmodem5AA90242591}"
DATASET_REPO_ID="./${DATASET_NAME}"
CACHE_ROOT="/Users/jiao/.cache/huggingface/lerobot"
EXPECTED_CACHE_PATH="${CACHE_ROOT}/${DATASET_NAME}"

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

# ============= 执行 lerobot-record 命令 =============
echo "🚀 开始执行 lerobot-record..."
echo "📦 本次数据集名称：$DATASET_NAME"
echo "🔌 使用 follower 端口：$ROBOT_PORT"
echo "🔌 使用 leader 端口：$TELEOP_PORT"
echo "🗂️  预期缓存目录：$EXPECTED_CACHE_PATH"
lerobot-record \
  --robot.type=so101_follower \
	--robot.port="$ROBOT_PORT" \
  --robot.id=my_awesome_follower_arm \
  --teleop.type=so101_leader \
	--teleop.port="$TELEOP_PORT" \
  --teleop.id=my_awesome_leader_arm \
  --dataset.repo_id="$DATASET_REPO_ID" \
  --dataset.single_task="$SINGLE_TASK" \
  --dataset.num_episodes=1 \
  --dataset.episode_time_s=20 \
  --dataset.reset_time_s=5 \
  --dataset.push_to_hub=false \
  --display_data=true

# ============= 执行完成后的清理 =============
RECORD_EXIT_CODE=$?
if [ $RECORD_EXIT_CODE -eq 0 ]; then
	echo "✅ lerobot-record 执行成功！"
	if [ -d "$EXPECTED_CACHE_PATH" ]; then
		echo "📁 录制数据目录：$EXPECTED_CACHE_PATH"
	else
		echo "ℹ️ 命令已成功，若未即时看到目录，请检查：$CACHE_ROOT/so101_try_00*"
	fi
else
	echo "❌ lerobot-record 执行失败，退出码：$RECORD_EXIT_CODE"
fi

conda deactivate
exit $RECORD_EXIT_CODE
