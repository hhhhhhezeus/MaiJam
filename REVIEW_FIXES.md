# 审核修复与验证记录

日期：2026-10-30；对应申请 #1163。

## 修复

- plugin_type 改为 media。
- 根据审核提供的文档方案，在 README 明确 WebUI 等价于 Dashboard owner 操作、不受 admins 限制；未宣称 API 已增加群管理员身份校验。

## 验证

在 maibot-plugin-sdk 2.20.0 下，于仓库上一级运行 `PYTHONPATH=.:MaiJam python -m unittest discover -s MaiJam/tests -v`，14 项通过。

覆盖音乐引擎、WAV/MIDI、会话隔离与持久化、管理权限、事件过滤、录制与取消、配置更新和 WebUI API 函数。WebUI 测试调用 Python API，不能等同于真实 Dashboard 页面联调。

## 兼容性边界与尚未完成项

- 本次环境：macOS、Python 3.13；没有真实 MaiBot / QQ / NapCat / Dashboard 安装。
- Host 上限从 `1.9.99` 收窄到 `1.3.99`，不再声明未来的 1.4–1.9 系列。**这仍是待验证的目标范围，不是实测兼容结论**，原有最低版本同样未在此次联调中验证。
- 审核所要求的真实 Host 版本验证尚未完成；不能以本记录替代。正式确认兼容范围前，应在目标 Host 验证加载、命令及对应界面，再更新 manifest 和测试记录。
- 本轮修复将随 `v0.1.1` 发布；旧 `v0.1.0` 保留历史内容。请使用 `v0.1.1` 验证，发行 tag 与对应 manifest 版本一致。
