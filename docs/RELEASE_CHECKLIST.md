# 发布准备

当前为 0.1.0 开发预览；本地测试不等同真实宿主验收。

1. 在真实 MaiBot Host、匹配的 Dashboard 和 QQ/NapCat 环境验证 SDK 2.20.0 加载、消息字段、自己的机器人身份过滤、原有回复链、管理员权限和群隔离。
2. 在真实 Host 的 schema v2 中验证 `webui.json`、所有按钮、音频分片读取、iframe CSP 和浏览器音频播放。若 Host 或 Dashboard 暂不支持该协议，移除页面声明或提供其支持的界面，不要宣称已验证。
3. 验证 WAV、MIDI 和 60 秒录制，观察 CPU 峰值、停止及卸载的后台任务清理。核对其他平台的群与用户字段。
4. 根据实际 Host/SDK 兼容测试修正 `_manifest.json` 的版本范围；调整作者、仓库和文档地址与实际 GitHub 仓库一致。
5. 执行 `python -m unittest discover -s tests -v`（按 README 设置 `PYTHONPATH`），保留结果；检查源码中不含用户配置、样本群消息或凭据。
6. 推送独立公开仓库，发布与 manifest 相同三段版本号的 Release；按 [插件中心说明](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md) 提交 Add Plugin Issue。收录后更新版本应创建新版本与新标签，不重写已收录标签。

用户数据、导出文件和 SDK 不应打进公共发布源代码包。这个清单不表示已完成 GitHub 发布或市场收录。
