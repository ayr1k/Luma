Luma

**连接你的模型，处理你的项目。**

Luma 是面向 Windows 的桌面 AI Agent，将对话、项目文件、工具执行、插件和 Skills 放在同一个工作界面中。你可以用它进行日常交流、分析项目、制定计划，以及在明确的权限边界下修改本地文件和执行命令。

Luma 采用客户端与推理服务分离的架构：**客户端负责本地操作，模型服务负责推理。** 当前主要面向可信局域网部署，适合个人工作站以及共享模型主机的使用场景。

[下载安装](https://github.com/ayr1k/Luma/releases) · [更新说明](docs/release-0.7.4.md) · [扩展开发指南](docs/extensions.md) · [LTS 政策](docs/lts.md) · [反馈问题](https://github.com/ayr1k/Luma/issues)

## 主要功能

- **独立桌面应用**：使用内嵌 WebView 界面，无需打开独立浏览器；支持浅色与深色主题、系统托盘和后台任务完成通知。
- **Chat / Plan / Work**：根据任务选择自由对话、只读分析或实际执行，避免把所有需求都当作文件修改任务。
- **项目与多对话管理**：支持独立聊天、同项目多会话、搜索、状态筛选、归档和删除。
- **模型连接与配置**：根据服务地址和客户端密钥获取可用模型，在主界面切换模型，配置模型参数并测试连接。
- **流式对话与附件**：逐步显示模型输出，支持发送图片和文件；具体处理能力取决于模型、网关及文件类型。
- **本地项目工具**：读取、写入、搜索文件，应用补丁，查看 Git diff，并在审批后执行终端命令。
- **文件与变更预览**：只读文件预览支持语法高亮、行号和换行；支持查看 Agent 文件变更，并在条件满足时回滚。
- **插件与 Skills**：通过本地 ZIP 或开发目录安装扩展，使用 `/` 选择 Skills、使用 `$` 选择工具插件。
- **联网搜索**：可启用基于 DDGS 的搜索，效果受网络环境和上游搜索服务可用性影响。
- **上下文管理**：Latest 0.7.4 提供 Token 用量估算、可编辑确认的对话摘要、历史分支和本机草稿恢复。

功能随版本和渠道有所不同，请以对应版本的更新说明为准。

## 下载与安装

1. 前往 [GitHub Releases](https://github.com/ayr1k/Luma/releases)，选择需要的正式版本。
2. 下载 `Luma-Setup-<最新版版本号>.exe`。普通用户无需下载 GitHub 自动生成的 Source code 压缩包。
3. 运行安装程序，选择 **Latest** 或 **LTS**。
4. 选择默认安装，或通过自定义安装调整预置 Skills 和插件。
5. 启动 Luma，在“连接设置”中填写模型服务地址和对应的客户端密钥。
6. 获取模型列表并选择模型，使用“测试模型连接”检查连接情况。

**运行环境：** Windows 桌面环境及 Microsoft Edge WebView2 Runtime。安装包包含客户端运行所需的 Python 环境，普通用户无需另行安装 Python。

**模型需要另外配置：** Luma 安装包不包含模型、Ollama 或 LiteLLM，也不提供公共推理服务、共享密钥或免费额度。

发布页提供 SHA-256 校验文件时，可在 PowerShell 中计算安装包的哈希并与之比较：

```powershell
Get-FileHash .\Luma-Setup-0.7.4.exe -Algorithm SHA256
```

当前安装包未进行代码签名。SHA-256 用于核对文件完整性，不能替代发布者身份签名。

## Latest 与 LTS

每次发布只提供一个统一安装包，在安装过程中选择渠道。

| 渠道 | 定位 | 版本基线 |
| --- | --- | --- |
| Latest | 持续引入功能和交互改进 | 本源码对应 0.7.4；已发布版本见 Releases |
| LTS | 优先维护稳定性和既有插件兼容性 | 0.7.2 LTS |

LTS（Long-Term Support，长期支持版）用于提供变化较少的使用和扩展适配基线。维护重点是重要缺陷、安全问题和必要的兼容修复，不主动引入重大新功能或破坏性接口变化。

- 大版本按首位划分：`0.x.x`、`1.x.x`、`2.x.x`，每个大版本选择一个 LTS 锚点。
- 在选定稳定候选版本后的下一次版本迭代发布时，该候选正式转入 LTS。
- 当前 LTS 的支持和下载窗口保留至下一代 LTS 正式发布。
- 第一个锚点为 **0.7.2 LTS**，在 0.7.3 发布时转入 LTS。
- 后续锚点根据实际稳定性选择，尚未公布的版本和日期不作为发布承诺。

两条渠道目前共用安装位置和用户数据目录。升级或切换前，请从托盘彻底退出 Luma，并备份重要项目与用户数据。对任意历史版本的降级兼容不作保证。

完整说明见 [LTS 政策与路线图](docs/lts.md)。

## 开始使用

### 1. 连接模型服务

推荐的局域网部署结构：

```text
用户电脑                              模型主机
┌─────────────────────────┐          ┌──────────────────────┐
│ Luma 桌面界面           │          │ LiteLLM 网关         │
│ 本机 API 与 Agent Core  │ ──LAN──▶ │ Ollama / 模型服务    │
│ 项目文件、Git、工具执行 │          │ 模型推理             │
└─────────────────────────┘          └──────────────────────┘
```

连接地址通常形如 `http://<模型主机局域网地址>:4000/v1`。每台客户端应使用单独签发的 LiteLLM Virtual Key，**不要把主机 Master Key 分发给客户端**。

模型需要支持所用网关的 OpenAI-compatible 接口。Work 模式依赖模型正确生成工具调用；视觉输入、推理参数和思考内容返回也需要模型与网关共同支持。

模型列表中出现某个模型，并不代表它已经通过所有能力测试。

### 2. 选择工作模式

| 模式 | 适用场景 | 项目操作边界 |
| --- | --- | --- |
| Chat | 问答、写作、讨论、附件交流 | 不读取或修改项目文件；可读取所选 Skill 的附属资料 |
| Plan | 理解代码、分析问题、制定实施计划 | 使用允许的只读项目工具，不修改项目 |
| Work | 修改代码、整理项目、执行实际任务 | 可使用文件编辑工具；终端命令和代码插件调用需要审批 |

添加本地项目后，Luma 在该项目的工作目录内执行文件工具。独立聊天可用于不依赖项目的讨论。

### 3. 查看并确认结果

执行期间可以查看任务状态、工具记录和待审批操作。完成后，使用文件预览、Agent 变更及 Git diff 检查结果。

同一项目的不同对话和历史分支**共享实际文件夹**。对话分支保留历史，不是项目文件快照，也不会把文件恢复到当时的状态。

### 4. 管理长对话

Latest 0.7.4 的“上下文管理”可以生成摘要草案，编辑并确认后才应用于后续请求；完整聊天历史仍保留，也可以恢复完整上下文。

Token 用量是估算值，不是模型服务的实际计费或分词统计。草稿显示“已保存到本机”后，可以在重新打开对应对话时恢复。

## 插件与 Skills

**Skill** 保存可复用的工作方法和参考资料；**插件**可以提供工具、成套 Skills、外观配置或受支持的软件功能。

### 使用扩展

- 在“扩展中心”导入本地 ZIP 或开发目录，查看详情、兼容范围、配置和诊断信息。
- 输入 `/` 选择 Skill，输入 `$` 选择工具插件；也可以使用输入区对应按钮。
- 为项目设置默认扩展，新对话自动带入，并显示可移除的标签。
- 按需导入、导出支持的扩展配置。

预置内容包括：

| 类型 | 内容 |
| --- | --- |
| Skills | 代码审查、问题排查、实施计划、文档总结、写作 |
| 工具插件 | 图片处理、项目概览、文档读取、文件整理 |
| 外观插件 | 配色、字体、图标、背景材质效果 |
| 软件功能插件 | 快捷短语、快捷键、桌面悬浮组件 |

实际可用效果受版本、插件配置及系统支持情况影响。安装预置插件不等于自动信任或启用其中的代码。

### 开发扩展

用户 Skill 默认放在：

```text
%LOCALAPPDATA%\LocalAgent\skills\<skill-id>\SKILL.md
```

配置了 `AGENT_DATA_DIR` 时，以配置的数据目录为准。修改用户 Skill 后，可在扩展中心重新扫描。

插件通过 `plugin.json` 声明身份、版本、支持范围和能力。当前采用本地 ZIP 与开发目录分发，尚无在线插件市场或插件自动更新服务。

- [扩展开发指南](docs/extensions.md)：格式、能力、权限、兼容性及限制。
- [纯 Skill 插件示例](examples/writing-kit)：打包可复用工作方法。
- [Python 工具插件示例](examples/project-stats)：工具声明与进程通信。

开发环境中可以执行安装前检查：

```powershell
python -m local_agent check-extension .\examples\project-stats
```

Skill 不能解除模式限制或跳过审批。代码插件在独立进程中执行，但独立进程不是操作系统级沙箱；只启用你信任的插件。

## 数据与权限

- **本地存储**：桌面版默认将配置、项目记录、会话和扩展数据保存在 `%LOCALAPPDATA%\LocalAgent`。源码运行和旧入口的默认值可能不同，可通过 `AGENT_DATA_DIR` 指定。
- **模型请求**：提供给模型的消息、文件内容、图片、工具结果和所选 Skill 内容会发送到配置的推理服务。局域网部署不等于数据始终只在客户端内流转。
- **联网搜索**：启用后，搜索请求会访问外部搜索服务。
- **文件边界**：内置文件工具会检查项目路径边界；这不构成对整个应用或插件的操作系统级隔离。
- **命令审批**：获批终端命令具有当前用户账户的权限，工作目录限制不等于文件访问权限限制。
- **变更回滚**：Agent 文件编辑可以记录并在检查通过时回滚；终端命令和插件造成的修改不保证可由 Luma 自动撤销。
- **本机服务**：客户端 API 监听回环地址并使用独立令牌，不应直接暴露到局域网或公网。

当前部署范围是可信局域网；使用 HTTP 的推理连接不提供传输加密。本项目目前不包含公网接入或 Tailscale 部署方案。

## 从源码运行

需要 Python 3.11+、Git，以及 Windows 桌面环境下的 WebView2 Runtime。以下命令使用 PowerShell：

```powershell
git clone https://github.com/ayr1k/Luma.git
cd Luma
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[desktop,web,test]"
.\.venv\Scripts\python.exe -m local_agent desktop
```

桌面入口会启动本机服务和应用窗口，无需再单独启动 `serve`。模型连接可在界面中配置。

若使用独立 CLI 或 API，请参考 [.env.example](.env.example) 建立自己的 `.env`，替换所有示例值：

| 配置项 | 含义 |
| --- | --- |
| `LITELLM_BASE_URL` | 模型网关的 OpenAI-compatible API 地址 |
| `LITELLM_API_KEY` | 当前客户端的模型服务密钥 |
| `AGENT_MODEL` | 模型标识，应与网关公布的名称一致 |
| `AGENT_LOCAL_TOKEN` | 本机 API 的独立随机令牌，不要复用模型密钥 |
| `AGENT_DATA_DIR` | 用户数据目录 |
| `AGENT_PORT` | 独立本机服务端口，默认 8765 |

连接检查及独立服务入口：

```powershell
.\.venv\Scripts\python.exe -m local_agent check --inference
.\.venv\Scripts\python.exe -m local_agent serve
```

不要让桌面版、独立服务或旧入口同时操作同一份用户数据。

### 模型主机

主机部署参考 [LiteLLM 配置示例](host/litellm.config.example.yaml) 和 [客户端密钥签发脚本](host/create_client_key.py)。使用前需替换示例中的主机地址、模型名称，并配置网关所需的数据库与环境变量。

密钥签发脚本只在主机运行。示例默认限制模型为 `local-agent-coder`，请根据自己的网关配置调整。模型服务、数据库和网关不由客户端安装程序自动部署。

### 测试与构建

```powershell
# 运行自动化测试
.\.venv\Scripts\python.exe -m pytest -q

# 使用模拟 HTTP 网关运行隔离演示
.\.venv\Scripts\python.exe scripts\demo.py
```

模拟测试验证客户端行为和通信协议，不代表所有真实模型都具有相同的工具调用或摘要质量。

Windows 安装包使用 PyInstaller 和 Inno Setup 构建。构建环境需要安装桌面及打包依赖，并准备独立的 LTS 源码目录：

```powershell
.\scripts\build-release.ps1 `
  -InnoCompiler "C:\path\to\ISCC.exe" `
  -LTSDirectory "C:\path\to\lts-source" `
  -PythonExe ".\.venv\Scripts\python.exe"
```

脚本生成一个包含 Latest/LTS 选择的安装包，以及对应的 `SHA256SUMS.txt`。LTS 基线标签为 `v0.7.2-lts`。

## 工程结构

```text
local_agent/     Agent Core、本机 API、模型通信、存储与桌面界面
host/            推理网关示例与客户端密钥签发脚本
presets/         预置 Skills
preset_plugins/  预置插件
examples/        扩展开发示例
scripts/         启动、演示与构建脚本
packaging/       桌面打包与安装程序配置
tests/           自动化测试
docs/            版本说明、LTS 政策、扩展指南与 API schema
```

API 的机器可读定义见 [OpenAPI schema](docs/openapi.json)。除健康检查外，本机 API 要求身份验证。

## 反馈与贡献

欢迎通过 [Issues](https://github.com/ayr1k/Luma/issues) 提交问题和建议，通过 Pull Request 提交改进。

报告问题时，尽量提供：

- Luma 版本、Latest/LTS 渠道及 Windows 版本。
- 模型和网关类型、复现步骤、预期行为与实际结果。
- 去除敏感信息后的截图或错误信息。

请勿上传 API Key、密码、完整个人会话或未经允许的项目内容。涉及凭据泄露或可利用安全漏洞的问题，请避免公开发布利用细节，先与维护者确认私下反馈渠道。

修改代码时，请说明改动目的及验证方法；涉及模型、工具、存储或扩展接口的改动，应补充相应测试并说明兼容性影响。功能建议不代表已纳入发布计划。

## 文档

- [0.7.4 更新说明](docs/release-0.7.4.md)
- [0.7.3 更新说明](docs/release-0.7.3.md)
- [LTS 说明与路线图](docs/lts.md)
- [插件与 Skills 开发指南](docs/extensions.md)
- [历史版本文档](docs/)

软件内的“帮助”菜单也提供说明书、更新日志和扩展开发指南入口。

## 许可证

Luma 采用 **GNU General Public License v3.0（GPL-3.0）**，完整条款见 [LICENSE](LICENSE)。

第三方组件、字体、图标及其他资源遵循各自的许可证。Luma 的许可证不替代这些第三方许可证；例如 Phosphor 图标的声明见 [第三方许可证文件](docs/phosphor-LICENSE.txt)。
