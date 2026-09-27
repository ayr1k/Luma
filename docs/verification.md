# 验证记录 · 2026-09-26

## 桌面阶段追加

- 桌面依赖 pywebview 6.2.1 已安装，pip check 通过。
- Python 回归：16 passed / 1 skipped。
- 桌面 Bridge → 实际 HTTP 服务：鉴权、目录选择后的项目注册、文件列表、文件内容、拒绝越界路径与任意 URL、服务关闭全部通过。
- Edge headless 界面测试（模拟数据）：项目切换、文件预览、纯文本显示 HTML、变更页切换通过；无 JavaScript 异常。
- 原生 WinForms / EdgeChromium 容器启动：初始化超时；系统存在 WebView2 Runtime，尚未定位具体原因，不能声称原生桌面运行通过。
- 新增无控制台和带控制台启动入口；原生初始化失败有 30 秒超时和错误提示。

## 第一阶段记录

- 独立 Python 3.12 环境完成 editable package 安装。
- pytest：14 passed，1 skipped。跳过项为 Windows 未授权创建符号链接；沙箱路径越界测试通过。
- 旧 Streamlit UI 使用 AppTest 启动，确认无异常并加载 Core 状态。
- 模拟 HTTP 端到端：completed；本地文件内容、获批命令、变更追踪全部验证通过。
- 真实 LAN `http://192.168.1.77:4000/v1`：认证后模型列表包含 `local-agent-coder`。
- 真实 LAN 端到端：completed；模型创建并读取 demo.txt，客户端审批执行 `echo local-tool-ok`，退出码 0，文件进入 agent_changes。
- 实际 Uvicorn 回环端口启动、无令牌 401、带令牌获取项目和 schema 全部通过。检查后停止测试进程。
- 工程内 `.venv-client` 已安装依赖；pip check 通过。原 `.venv` 保留。`.env` 仅追加缺失的独立本机 API 随机令牌，未改动模型凭据。
- 未执行真实用户项目上的模型任务。原 projects.json、sessions 文件未迁移或重写；原 agent.py/web.py 已备份。
- 主机 PostgreSQL / Virtual Key 签发配置未部署，当前凭据类型未确认。

测试覆盖审批重放/错误 ID/拒绝/恢复、审批后继续工具队列、命令崩溃后不重放、步数上限、参数错误、旧存储兼容、文件回滚与手工变更保护、接口认证、Origin/Host 拒绝、schema 校验、UI 启动。
