# MaiJam · 群聊协作乐队

MaiJam 把群聊互动转换成可复现的音乐控制事件，按小节生成原创鼓组、低音、和弦与旋律。音乐合成在本地完成，不调用 LLM、TTS、Embedding 或第三方生成 API，不需要 GPU 和 API Key。

**当前版本：0.1.2，开发预览。** 离线核心与真实 SDK 2.20.0 的模拟宿主集成测试已运行；实际 MaiBot Host、QQ 适配器和宿主 WebUI 页面尚未联调。Manifest 中 Host 范围是待实机验证的目标范围，不代表整个区间均已验证。

## 立即离线试听

```bash
python examples/offline_demo.py --output demo
```

示例模拟 5 位成员在约 60 秒内发言，输出 `demo.wav`、`demo.mid`、`demo_events.json`。JSON 保存的是数字化控制事件和音符，不包含聊天原文。可用 `--style lofi|synthwave|chiptune|house` 和 `--seed 123` 切换；同样的输入和种子产生同样的音符事件。

离线引擎只使用 Python 标准库（Python 3.10+）。WAV 为单声道、16 位 PCM、22050 Hz；MIDI 为标准格式 0。合成是原创程序波形而非采样。

## 安装

1. 使用提供 SDK 2.20.0 的 MaiBot Host，把整个 `MaiJam` 目录复制到 MaiBot 的 `plugins/MaiJam/`。不要覆盖主程序源码。
2. 在插件设置中填写 `admins` 和 `bot_ids`，例如 `admins = ["qq:123456789"]`、`bot_ids = ["qq:3663187956"]`。两者默认空：管理命令不会放行；无法识别自身机器人时消息观察也会安全地停止。
3. 在插件管理中启用 MaiJam 或按 Host 的方式重载插件。在目标群由管理员发送 `/jam start`。每个群默认关闭，插件加载本身不会开始群聊音乐。
4. 群友发送 `/jam join`，随后用 `/jam instrument drums` 等选择角色。管理员可 `/jam record 30` 记录之后 30 秒的音乐控制状态；完成后自动合成 WAV 与 MIDI。

### Windows

将本目录复制到 MaiBot 安装目录的 `plugins\MaiJam`，通过 MaiBot WebUI 设置并重载。离线演示可在该目录运行 `py examples\offline_demo.py`。

### Linux

将本目录复制到 MaiBot 的 `plugins/MaiJam`。用 `python3 examples/offline_demo.py` 离线生成；确保 Host 分配的插件数据目录可写。

### Docker

将本目录放到映射到容器 `plugins/` 的持久卷，例如你自己的 compose 配置中 `./plugins:/MaiMBot/plugins`。同时持久化 Host 的 `data/`，以免成员配置和导出随容器重建丢失。具体容器路径以你的部署配置为准；无需新增端口或 GPU。

运行时配置由 SDK 生成；`config.example.toml` 仅供参考。不要把自己的 `config.toml` 提交到 Git。

## 命令

| 命令 | 作用 | 权限 |
| --- | --- | --- |
| `/jam start` / `/jam stop` | 启动或停止本群；停止会取消尚未完成的录制 | 白名单管理员 |
| `/jam status` | 查看风格、BPM、小节和当前能量 | 群成员 |
| `/jam join` / `/jam leave` | 加入或离开乐队 | 群成员 |
| `/jam instrument drums` | 改为 `drums`、`bass`、`lead`、`chords`、`arp` 或 `fx` | 已加入成员 |
| `/jam members` | 查看成员及休眠状态 | 群成员 |
| `/jam style lofi` | 切换 `lofi`、`synthwave`、`chiptune`、`house` | 白名单管理员 |
| `/jam record 30` | 收集接下来 30 秒的聚合状态并后台合成 | 白名单管理员 |
| `/jam export wav` / `/jam export midi` | 报告已完成文件的宿主路径 | 白名单管理员 |
| `/jam help` | 显示命令 | 群成员 |

录制时长 5–60 秒，可通过配置降低上限。因为音乐按完整小节输出，文件时长可能比所请求时间短至不足一个小节。录制期间切换风格会中止本次生成，避免一首曲目出现不一致的 BPM。没有已验证的通用 SDK 音频发送接口；命令不会声称音频已发送，也不会把本地路径伪装成其他群友可访问的下载链接。部署者可在插件数据目录取得文件，或通过兼容的宿主 WebUI 试听。

## WebUI 工作台

WebUI 操作等同于 Dashboard 的 owner 操作，不受 `admins` 白名单限制；能够登录 Dashboard 的用户可控制工作台并读取生成的音频。工作台快照一次返回所有已登记群的乐队信息，包括成员用户 ID、风格与混音状态；能登录 Dashboard 的人可以查看这些跨群信息。请只向可信人员开放 Dashboard。

`webui.json` 使用官方文档的 schema v2 自定义页面，所有查询和操作通过本插件声明的静态 `@API`。页面显示群、风格、BPM、调性、小节、活跃度、成员、各声部音量及静音，并提供开始、停止、风格切换、30 秒录制和录音试听。试听通过 API 分片读取生成的 WAV，加载后需要用户点击播放器。

此协议需要配套的 MaiBot Host 与 Dashboard；不是所有现有安装都具备 v2 `custom_pages`。当前环境未运行这些组件，页面注册、桥接、CSP 下的 blob 音频和真实按钮交互**尚未完成宿主实测**。API 处理函数已在真实 SDK 的模拟上下文中验证。宿主不支持页面时，离线生成和群命令仍可使用；不存在对外开放的独立 Web 服务。

## 设置

| 配置 | 默认 | 说明 |
| --- | --- | --- |
| `admins` | `[]` | `平台:用户ID` 的管理白名单；默认拒绝群管理命令 |
| `bot_ids` | `[]` | `平台:机器人ID`；没有可信 self ID 或此配置时不处理消息 |
| `window_seconds` | 30 | 消息聚合窗口，秒 |
| `user_cap` | 5 | 每用户每窗口最多贡献次数 |
| `max_queue` | 512 | 每群内存事件队列上限 |
| `energy_scale` | 18 | 能量密度达到上限的消息计数尺度 |
| `smoothing` | 0.35 | 每次小节量化的能量平滑系数 |
| `fill_scale` / `accent_scale` | 3 / 8 | 笑声填充和标点重音的归一化尺度 |
| `active_users_scale` | 5 | 编曲层数的活跃人数尺度 |
| `max_members` / `sleep_seconds` | 32 / 900 | 每群成员上限和休眠时间 |
| `cooldown_seconds` | 30 | 每群两次录制的冷却时间 |
| `max_record_seconds` | 60 | 单次录制上限，不能超过 60 |
| `max_parallel_recordings` | 2 | 全局同时录制上限，最多 4 |
| `retention_days` | 7 | 导出保留天数；启动、导出后和每小时清理，每群最多保留 24 个文件 |

配置热更新应用于新事件和录制。群的成员、角色、风格、混音设置和数值控制状态存于 `ctx.paths.data_dir`；重启后会恢复配置，但会话保持停止，需要管理员重新启动。用户的聊天原文不会保存。成员 ID 和最后活跃时间会持久化以恢复乐队；请按自己的数据管理策略管理插件数据目录。

## 算法与边界

文字长度、笑声、感叹号、表情和活跃人数由本地规则识别；消息先在有界窗口内聚合，同一用户的贡献有上限。能量使用指数平滑，统计在小节边界转换成音符。用户角色影响对应声部的力度，多人的相同角色合并并有上限；不会因人数增加而新建无限音轨。成员不活跃时进入休眠，空窗的能量逐渐下降。

四种风格使用不同 BPM、鼓组、音色和编排。四小节和弦循环结合固定调式，主旋律由种子生成的动机重复、变形，并在乐句末归音；ADSR、分轨音量和峰值限制在本地完成。若将同一事件序列与种子重复输入，得到相同音符；实时群聊的实际到达时间可能不同。纯 Python 渲染在后台线程执行；使用时应留意 CPU 负载。

目前没有自动发送 QQ 语音、独立公网分享、音频流直播和自然语言乐器识别。素材文件的保留只受配置策略约束；请按自己的部署清理与备份。主程序和各平台消息结构可能变化，真实群消息形状、机器人自身过滤、录音播报与 WebUI 行为需要在目标部署中验证。

## 开发与测试

```bash
python -m pip install maibot-plugin-sdk==2.20.0
# 从 MaiJam 目录的上一级，使包 MaiJam 可被导入：
PYTHONPATH=".:./MaiJam" python -m unittest discover -s MaiJam/tests -v
```

Windows PowerShell 示例：在 `MaiJam` 目录的上一级执行 `$env:PYTHONPATH=".;.\MaiJam"; python -m unittest discover -s MaiJam\tests -v`。测试细节及未覆盖项见 [TEST_RESULTS.md](TEST_RESULTS.md)；SDK API 与来源见 [兼容性记录](docs/COMPATIBILITY.md)。

## 可扩展方向

经过真实适配器验证后增加 QQ 音频投递；更多和弦与音色、分段导出、音乐主题和 WebUI 波形；持久化的匿名化统计和更精细的成员贡献映射。

MIT License.

## 本次审核修复

修改内容、可复现测试和未完成的真实 Host 验证见 [审核修复记录](REVIEW_FIXES.md)。

审核修复发行版本：`v0.1.2`。请从 Releases 下载此版本；`v0.1.0` 不包含本轮修复。
