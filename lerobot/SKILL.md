---
name: lerobot
description: 控制机械臂
---
# lerobot技能

所有技能基于seeed studio的lerobot机械臂, 需要先安装好相关的驱动和环境, 具体安装步骤可以参考https://wiki.seeedstudio.com/cn/lerobot_so100m/ , 安装完成以后才可以进行一下的动作录制和播放, 以及跟随控制等功能

## 查询端口

用户给机械臂上电, 电脑连接type-c线, 机械臂会自动连接电脑, 但是需要查询一下连接的端口号, 才能进行后续的动作录制和播放, 直接运行以下命令即可查询到连接的端口号, 例如`/dev/tty.usbmodemXXXX`:
```bash
lerobot-find-port
```
输入命令, 拔出type-c线, 回车即可查询到连接的端口号, 例如`/dev/tty.usbmodemXXXX` 实际的输出示例如下
```bash
(lerobot) jiao@jiaodeMacBook-Air scripts % lerobot-find-port
Finding all available ports for the MotorsBus.
Ports before disconnecting: ['/dev/tty.Bluetooth-Incoming-Port', '/dev/tty.XMLYMiniboom', '/dev/tty.iQOOTWS5', '/dev/ttys000', '/dev/ttys002', '/dev/ttys006', '/dev/ttys005', '/dev/ttys008', '/dev/ttys009', '/dev/ttys010', '/dev/ttys011', '/dev/ttys015', '/dev/ttys017', '/dev/tty.usbmodem5AA90242591', '/dev/tty.usbmodem5AA90243381', '/dev/tty.usbmodem1301', '/dev/ttys003']
Remove the USB cable from your MotorsBus and press Enter when done.

The port of this MotorsBus is '/dev/tty.usbmodem5AA90242591'
Reconnect the USB cable.
```
分为leader和follower两个机械臂, 需要查询两个机械臂的端口号, 以便于后续的动作录制和播放


## 重要提示：端口号获取

**在进行任何需要指定端口的操作（如动作录制、播放、跟随等）前，请务必先通过 `lerobot-find-port` 查询并确认机械臂的端口号！**

如未先查询端口，后续命令可能会失败或找不到设备。

查询方法见上文“查询端口”章节。

---

## 动作播放

失败的话重复运行命令几次，直到成功为止。这里的 ./so101_try_002 是一个数据集路径，里面包含了机械臂的动作数据，运行这个命令会让机械臂按照数据集中的动作进行点头。不同的机械臂的动作对应的数据集在文件 assets/action.json 里面, 查询这个文件后再执行命令。

控制机械臂点头, 直接运行以下命令即可：
```bash
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./play_action.sh ./so101_try_002

# 指定 follower 端口（请用 lerobot-find-port 查询实际端口号）
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./play_action.sh ./so101_try_002 /dev/tty.usbmodemXXXX
```

参考的脚本示例如下
1. 激活conda环境
2. 运行机械臂控制脚本
3. 退出conda环境

## 动作录制


在实现数据录制以后, 更新了`assets/action.json`文件, 以便于后续的动作播放, 例如:
```json
{
    "点头": "./so101_try_002",
    "新的动作": "./so101_try_009"
}
```

```bash
# 默认数据集名 so101_try_001
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./recoeding_action.sh

# 指定数据集名
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./recoeding_action.sh so101_try_009

# 指定数据集名 + 任务描述
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./recoeding_action.sh so101_try_009 "pick and place test"

# 指定数据集名 + 任务描述 + follower端口 + leader端口
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./recoeding_action.sh so101_try_009 "pick and place test" /dev/tty.usbmodemFOLLOWER /dev/tty.usbmodemLEADER
```
文件记录在`/Users/$USER/.cache/huggingface/lerobot/数据名字`, 名字需要是不一致的, 不可以重复, 否则会报错

## 跟随控制

```bash
# 使用默认端口
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./teleoperate_action.sh

# 指定 follower 端口和 leader 端口
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./teleoperate_action.sh /dev/tty.usbmodemFOLLOWER /dev/tty.usbmodemLEADER
```



## 校准

获取机械臂的可以运动的角度, 记录在配置文件中
```bash
# 使用默认端口（会依次校准 follower 和 leader）
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./calibrate_action.sh

# 指定 follower 端口和 leader 端口
cd /Users/$USER/.openclaw/skills/lerobot/scripts && ./calibrate_action.sh /dev/tty.usbmodemFOLLOWER /dev/tty.usbmodemLEADER
```

如果校准失败, 先确认两个机械臂都已上电并连接稳定, 然后重新执行校准命令。

## lerobot环境激活

lerobot的脚本依赖于Conda环境，确保在运行任何控制或录制命令之前正确激活环境。以下是一个示例脚本片段，展示了如何强制加载Conda配置并激活lerobot环境：
```bash
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
echo "🔍 切换到 lerobot 目录：/Users/$USER/JHY/python/lerobot"
cd /Users/$USER/JHY/python/lerobot || {
    echo "❌ 错误：无法切换到目录 /Users/$USER/JHY/python/lerobot，请检查路径是否正确！"
    exit 1
}

echo "🔧 激活 lerobot Conda 环境..."
conda activate lerobot || {
    echo "❌ 错误：无法激活 lerobot 环境！请执行 conda env list 检查环境是否存在。"
    exit 1
}
```

## 资料

安装以及环境初始化文档 https://wiki.seeedstudio.com/cn/lerobot_so100m/
