# Luma 0.7.3

任务进度与操作卡片、对话搜索和归档、桌面联动，以及更宽松的插件数量上限。详见 [升级说明](docs/release-0.7.3.md)。

## Luma 0.6.1

统一扩展中心入口样式，新增五个预置 Skill 和默认 / 自定义安装。详见 [升级说明](docs/release-0.6.1.md)。

## Luma 0.6.0

新增插件与 Skills：扩展中心、本地包安装、独立 Skill 文件夹、显式选择，以及逐次审批的独立进程工具。详见 [升级说明](docs/release-0.6.0.md) 和 [扩展开发指南](docs/extensions.md)。

## 0.5.7

修复工具成功后自然结束答复被继续催促的问题。详见 [升级说明](docs/release-0.5.7.md)。

# Luma 0.5.6

可恢复的任务暂停、无工具回复限制调整、思考内容展示与兼容参数。详见 [升级说明](docs/release-0.5.6.md)。

# Luma 0.5.5

新增系统托盘后台运行及任务完成通知。详见 [升级说明](docs/release-0.5.5.md)。

# Luma 0.5.4

新增内置帮助、更新日志，以及带语法高亮和行号的只读文件预览。详见 [升级说明](docs/release-0.5.4.md)。

# Luma 0.5.3

新增消息时间、生成耗时、复制及编辑提问后重新生成。详见 [升级说明](docs/release-0.5.3.md)。

# Luma 0.5.2

修复浅色主题，新增图片与文件附件。详见 [0.5.2 升级说明](docs/release-0.5.2.md)。

# Luma 0.5.1

Local Agent 更名为 Luma：新版桌面 UI、Chat / Plan / Work、DDGS 联网搜索、参数设置与软件设置。

详见 [0.5.1 使用与升级说明](docs/release-0.5.1.md)。现有数据目录不变，兼容旧版本配置和项目。

# Luma 0.5.0

Local Agent 更名为 Luma：新版桌面 UI、Chat / Plan / Work、DDGS 联网搜索、参数设置与软件设置。

详见 [0.5.0 使用与升级说明](docs/release-0.5.0.md)。现有数据目录不变，兼容旧版本配置和项目。

## 0.4.0：主界面模型选择

自动获取当前主机和客户端密钥可用的模型，支持搜索、刷新和记住选择。详见 [升级说明](docs/release-0.4.0.md)。

# Local Agent Client

## 0.3.0 任务运行更新

新增任务进度、停止后续执行、审批后台续跑、多开保护和 Windows 会话保存冲突修复。用户已确认上版在正常桌面能打开窗口；本版沿用同一窗口方案。升级与验收范围见 [0.3.0 发布说明](docs/release-0.3.0.md)。

## 0.2.0 安装预览版

已新增独立程序与安装包、首次连接配置、Windows 加密密钥存储和仅本次使用模式。见 [安装与验证说明](docs/release-0.2.0.md)。原生桌面启动仍待正常用户环境验收，当前包为预览版。


## 新增：桌面客户端

本机已安装桌面依赖。先关闭旧 Streamlit 窗口对应的终端服务，以及 `serve` API 服务（Ctrl+C），避免同时操作同一个会话目录。

在工程目录双击 **Start Local Agent.vbs**，或运行：

```powershell
cd C:\Users\lempi\local-agent
.\.venv-client\Scripts\python.exe -m local_agent desktop
```

桌面入口自动启动独立回环 API 和 WebView2 窗口，无需打开浏览器或单独运行 `serve`。若启动失败，使用 **Start Local Agent.cmd** 查看提示。桌面模式使用临时回环端口，因此不需要打开 8765 网页。

功能：原生选择本地项目文件夹、项目切换、会话聊天、命令批准/拒绝、文件预览、Agent/Git diff、保留/安全回滚、工具记录、模型连接与简短推理测试。执行期间界面禁用其他操作，关闭窗口会被阻止，直到任务完成或等待审批。尚不支持流式输出和取消运行。

网页只调用受限 native bridge；模型和本机密钥不会传给页面。模型回复和文件内容用纯文本渲染。独立桌面之间有进程锁；旧 CLI/Streamlit 仍需手动关闭。窗口缓存位于 `.webview`，项目与会话沿用现有位置。

新机器安装：`python -m pip install -e '.[desktop,web,test]'`，需要 Windows 和 Microsoft Edge WebView2 Runtime。本阶段提供源码及双击启动入口，已生成 0.2.0 安装预览包，验收范围见最新发布说明。

验证：16 个 Python 测试通过、1 个符号链接权限测试跳过；浏览器引擎交互测试通过。**原生 WebView2 容器在当前受限执行环境中初始化超时，尚未确认真实桌面启动成功**。启动器会在超时后显示错误，不会静默卡在空白窗口。浏览器交互测试使用模拟项目数据，不代表原生容器验收。

桌面 API 用法依据 [pywebview 官方文档](https://pywebview.flowrl.com/api/)。以下为保留的服务层说明。

用户电脑运行 Agent Core 和本机 API，负责项目文件、Git、会话、变更追踪及命令审批。主机 `192.168.1.77` 的 LiteLLM/Ollama 只提供 OpenAI-compatible 推理 API。模型收到的消息和工具结果可能包含客户端代码内容；文件执行位置始终是客户端。

## 工程结构

```text
agent.py                 兼容命令行入口
web.py                   原 Streamlit UI，使用共用 Core
local_agent/
  core.py                Agent 状态机、工具队列、一次性审批、变更追踪/回滚
  tools.py               原文件/Git/搜索工具和已批准命令执行器
  model.py               LAN 推理通信与连接测试
  config.py              客户端配置；导入 Core 不要求模型密钥
  storage.py             projects/sessions 原子 JSON 持久化
  schemas.py             API 请求/响应模型
  service.py             FastAPI 本机服务
  files.py               文件预览、Agent diff、Git diff
  tool_schema.py         模型工具 schema
  prompt.py              共用系统提示
host/                    主机 LiteLLM 配置、客户端密钥签发脚本
scripts/demo.py          模拟 HTTP / 真实 LAN 两种端到端演示
tests/                   Core、服务和旧 UI 回归测试
backups/pre-productization/  重构前 agent.py、web.py 备份
```

## 安装与启动（Windows PowerShell）

使用可运行的 Python 3.11+。已有 `.venv` 可以继续使用；若不可用，创建新的环境：

```powershell
cd C:\Users\lempi\local-agent
python -m venv .venv-client
.\.venv-client\Scripts\python.exe -m pip install -e '.[web,test]'
```

保留现有 `.env`；新客户端参考 `.env.example` 创建自己的 `.env`。配置：

| 配置 | 含义 |
|---|---|
| `LITELLM_BASE_URL` | `http://192.168.1.77:4000/v1` |
| `LITELLM_API_KEY` | 主机单独签发给这台客户端的 Virtual Key |
| `AGENT_MODEL` | `local-agent-coder` |
| `AGENT_LOCAL_TOKEN` | 本机 API 专用随机令牌，与 Virtual Key 完全独立 |
| `AGENT_DATA_DIR` | 默认工程目录；兼容现有 projects.json / sessions |
| `AGENT_PORT` | 默认 `8765` |

新安装生成本机令牌：`python -c "import secrets; print(secrets.token_urlsafe(32))"`，填入 `.env`。不要把主机 Master Key 放到客户端。

```powershell
# 检查模型列表；加 --inference 会执行一条简短推理
.\.venv-client\Scripts\python.exe -m local_agent check --inference

# 本机服务，仅监听 127.0.0.1:8765
.\.venv-client\Scripts\python.exe -m local_agent serve

# 保留的独立入口（二选一，不要与服务同时使用同一数据目录）
.\.venv-client\Scripts\python.exe agent.py C:\path\to\project
.\.venv-client\Scripts\python.exe -m streamlit run web.py --server.address 127.0.0.1
```

也可运行 `scripts/start-client.ps1 -Python .\.venv-client\Scripts\python.exe`。桌面模式见本文开头；安装包见 0.2.0 发布说明。

## API 合约

除 `/health` 外，所有路由都需要 `Authorization: Bearer <AGENT_LOCAL_TOKEN>`。本机服务不接受浏览器 Origin，不开放 CORS；后续桌面壳应通过 native bridge 调用。不要将本机 API 绑定到 `0.0.0.0`。

完整机器可读 schema 由鉴权后的 `GET /openapi.json` 提供，静态副本见 `docs/openapi.json`。

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/health` | 本机服务状态 |
| POST | `/v1/connection/test` | `{"inference":false}`，验证网关/密钥/模型；true 增加真实推理 |
| GET/POST | `/v1/projects` | 项目列表 / `{"path":"C:/project"}` 注册已有本地目录 |
| DELETE | `/v1/projects/{id}` | 从列表移除，保留磁盘文件和会话 |
| GET | `/v1/projects/{id}/session` | 获取会话、状态、待审批命令 |
| POST | `/v1/projects/{id}/session/reset` | 清空该项目当前会话及变更追踪，保留工作文件 |
| POST | `/v1/projects/{id}/messages` | `{"content":"任务描述"}`，运行至完成、失败或待审批 |
| POST | `/v1/projects/{id}/approvals` | `{"approval_id":"…","allow":true}`，消费审批并继续 |
| GET | `/v1/projects/{id}/changes` | Agent diff 和 Git 变更 |
| POST | `/v1/projects/{id}/changes/keep` | 接受变更、清空追踪 |
| POST | `/v1/projects/{id}/changes/revert` | 哈希匹配才回滚，返回 reverted/skipped |

状态包括 `idle/running/waiting_approval/completed/failed/interrupted`。审批 ID 绑定原始命令、项目和工具调用，只使用一次；旧审批重放返回 409。批量工具调用在审批后继续队列，不丢失后续调用。命令执行前持久化审批消费；执行期间崩溃会进入 interrupted，必须检查文件并新建会话，不会自动重跑命令。

0.7.3 支持同项目多会话：旧主会话沿用 workspace SHA-256 文件名，新会话使用 conversation-ID 文件；各自保留历史、审批与变更记录。任务异步执行和轮询，支持停止；一次只运行一个任务，不使用多 worker。同项目文件共享，其他任务待审批时不可开始新的执行。进程锁防止多个客户端同时写同一数据目录。

## 沙箱与审批边界

文件工具解析真实路径后必须位于 workspace 内；搜索和预览也检查符号链接目标。`run_command` 无法经普通工具分发绕过审批。终端命令使用现有 `shell=True` 行为，工作目录是 workspace，但它不是操作系统级沙箱，获批命令仍可访问用户权限内的其他位置。审批者需查看完整命令与目录。

Agent changes 追踪 write_file/apply_patch，保存原始字节以准确回滚换行。文件在 Agent 修改后又被手工修改时，回滚跳过它。命令导致的文件修改仍通过 Git diff 查看，不伪装成可安全自动回滚的 Agent 文件编辑。

本机令牌与模型 Key 不在 API schema、会话日志或输出中返回。局域网 HTTP 不加密链路，部署仅限可信 LAN；文件沙箱不防御并发替换链接等恶意本机进程。本阶段不配置公网或 Tailscale。

## 主机配置与每客户端 Virtual Key

保留现有主机服务，参考 `host/litellm.config.example.yaml` 调整。主机需要 PostgreSQL、`DATABASE_URL`、`LITELLM_MASTER_KEY`；模型 tag 替换成实际安装的支持 tools 的 Ollama 模型。以主机本地 Ollama 为上游：

```powershell
litellm --config host/litellm.config.example.yaml --host 192.168.1.77 --port 4000
python host/create_client_key.py client-alice
```

签发脚本只在主机运行，从环境变量读取 Master Key，返回限定 `local-agent-coder`、30 天有效、每分钟 30 次的独立客户端 Key。分别发给对应用户，写入各自 `.env`；在 LiteLLM 管理端撤销/轮换。Ollama 与数据库无需对客户端开放；主机防火墙仅允许可信 LAN 来源访问 4000。

本次只验证现有凭据可连接/推理，没有更改正在运行的主机配置、创建数据库或签发真实客户端 Key，现有凭据是否是 Virtual Key 尚未确认。

依据：[LiteLLM Virtual Keys](https://docs.litellm.ai/docs/proxy/virtual_keys)、[Ollama provider](https://docs.litellm.ai/docs/providers/ollama)。

## 演示与测试

```powershell
python scripts/demo.py
python scripts/demo.py --live --base-url http://192.168.1.77:4000/v1
python -m pytest -q
```

演示会新建隔离项目，通过 FastAPI → Core → OpenAI HTTP → 模型 → 客户端文件工具完成闭环。默认模式使用确定性的模拟 HTTP 网关；`--live` 使用真实主机。演示只自动批准固定命令 `echo local-tool-ok`，其他命令拒绝。结果和会话保留在 `demo-runs`，不会改现有用户项目。

验证记录见 `docs/verification.md`。



### 0.7.3 项目任务 API
`POST /v1/projects/{id}/conversations` 使用可选 name 新建同项目会话，返回独立 id；已有 project 路由中的 id 同样可以指向新会话。列表返回 group_id、project_name、kind、session_id、status、updated_at。归档/删除针对单个会话，default_skills/default_plugins 修改对该项目组生效。旧主会话 ID 和磁盘文件保持兼容。
