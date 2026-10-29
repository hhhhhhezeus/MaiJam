# 兼容性与接口记录

核对日期：2026-10-29。

## 已核对的官方资料

- [SDK 2.20.0](https://github.com/Mai-with-u/maibot-plugin-sdk)：当前官方发布版本；本项目在隔离目录安装该版本并运行了组件与配置模型测试。`MaiBotPlugin` 必须实现 `on_load`、`on_unload`、`on_config_update`。
- [事件处理器](https://docs.maibot.chat/plugin/event-handlers)：使用 `EventType.ON_MESSAGE` 和 `intercept_message=False`，不阻塞原消息链。SDK 中装饰器元数据已通过组件注册测试；真实 Host 注入字段仍待实测。
- [命令](https://docs.maibot.chat/plugin/commands)：`@Command` 使用正则命名捕获组；本插件对敏感操作另外校验 `platform:user_id` 白名单，不假设各平台均提供群管理员角色。
- [WebUI 页面](https://docs.maibot.chat/plugin/webui-pages)：schema v2 使用 custom 页面和宿主 `maibot.query/action` 桥接，宿主必须同时具备对应前后端能力。v2 文档称其为开发中协议；实际主程序版本号范围在本环境未验证。
- [SDK SendCapability](https://github.com/Mai-with-u/maibot-plugin-sdk/blob/main/maibot_sdk/capabilities/send.py)：2.20.0 的公开能力有 `text`、`image`、`emoji`、`forward`、`hybrid`、`command`、`custom`，没有通用 `audio` 方法。SDK 兼容层的 `send_voice` 带弃用警告，MaiJam 不使用。
- [NapCat 适配器消息 API](https://github.com/Mai-with-u/MaiBot-Napcat-Adapter/blob/main/docs/message-api.md)：文档列出适配器 API 和获取 AI 语音接口，但这不等同于验证插件通过目标适配器发送本地生成音频的完整路径。MaiJam 的音频投递模块因此明确返回不支持；未调用 TTS 或 AI 语音。

文档中的示例事件有时将 `user_info` 放在消息顶层，而 SDK 示例中的 `MessageDict` 将它放在 `message_info.user_info`。适配层同时读取这两种结构，并在缺少群、用户或平台时忽略事件；没有可信机器人身份时也默认忽略。最终字段以目标 Host 实际事件为准。

## 尚未验证

- 当前工作区没有可运行的 MaiBot 主程序。对官方主程序仓库的下载没有成功；未声称主程序加载、真实 QQ 群的事件字段、或 WebUI schema 在特定安装中通过。
- WebUI 的 v2 自定义 iframe 对 blob 音频的 CSP、完整桥接和页面注册未在配套 Host/Dashboard 中实测；如不可用，请使用离线导出。宿主没有文件上传/下载的通用开放接口时，本插件不构造假链接。
- `host_application` 的版本范围是上架准备目标而非完整版本兼容测试矩阵；首次公开正式版本前需在目标 Host 上确认并收窄或修正。
