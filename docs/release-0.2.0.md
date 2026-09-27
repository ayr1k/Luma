# Local Agent 0.2.0 预览版

## 安装和首次使用

1. 关闭旧 API/Streamlit 服务，避免它们同时修改现有会话。
2. 运行 `LocalAgent-Setup-0.2.0-preview.exe`。默认安装到当前用户的 `%LOCALAPPDATA%\Programs\LocalAgent`，不要求管理员权限；可以选择创建桌面快捷方式。
3. 从开始菜单或快捷方式打开 Local Agent。首次进入“连接你的局域网主机”：填写 `http://192.168.1.77:4000/v1`、模型 `local-agent-coder`、管理员给本客户端的 Virtual Key。
4. 点击“保存并测试连接”。成功后添加本地项目并开始任务。若 Windows 无法加密保存，可取消“在这台电脑上保存”并仅本次使用；关闭后需要重新输入。

Windows 10/11 x64，需要 Microsoft Edge WebView2 Runtime 和 .NET Framework 4.8。Python 已随程序打包，客户端无需另装 Python 来启动软件。项目自己的运行环境、Git 和测试工具仍按项目需要安装。

本预览包未做代码签名，Windows 可能显示未知发布者。WebView2 Runtime 官方说明：https://developer.microsoft.com/en-us/microsoft-edge/webview2/ 。

## 用户数据与升级

- 安装版数据独立位于 `%LOCALAPPDATA%\LocalAgent`：projects.json、sessions、client-config.json、启动日志和 WebView 缓存。
- 密钥使用 Windows CurrentUser DPAPI 加密，不能直接把加密文件复制给另一个 Windows 用户使用。只在窗口中输入/更换密钥；接口不会返回已保存的密钥。
- “仅本次使用”不写入配置文件，已有磁盘配置也不改变。网络错误不会把明文密钥写到日志。
- 原源码工程的 `.env`、projects.json、sessions 不迁移、不打包、不删除。源码模式仍沿用原数据位置。
- 新安装版有独立项目列表，需要重新添加项目。不要让源码版和安装版同时操作同一个项目文件。
- 升级覆盖程序目录，不覆盖用户数据目录；卸载保留 `%LOCALAPPDATA%\LocalAgent` 和实际项目文件。
- 主机的 PostgreSQL/Virtual Key 签发仍需管理员完成；安装包不包含主机 Master Key。

## 本次验证

- Python：24 passed、2 skipped；跳过 Windows 符号链接权限及当前执行环境不可用的用户 DPAPI 集成测试。
- 首次配置 UI：自动打开设置、仅本次使用、连接测试、提交后清空密码输入框均通过；使用 Edge 自动化和模拟 API 数据。
- 独立 exe 自检通过：冻结运行、本机 API、界面资源、开发者密钥缺省均符合预期。
- 安装包编译成功；解包后的 LocalAgent.exe 与已验证程序 SHA-256 一致。
- 分发目录扫描通过：未发现开发者密钥、`.env`、projects.json、client-config.json。
- **尚未完成正常 Windows 用户桌面的安装/卸载和原生 WebView 窗口验收。** 当前执行环境无法解析部分 Windows 用户 shell folder（系统错误 2），DPAPI 同样返回错误 2，最小 WebView2 控件初始化超时。不能将预览包当作已经完成跨机器验收的正式版本。

启动异常时查看 `%LOCALAPPDATA%\LocalAgent\startup.log`。源码模式日志在工程数据目录。该日志记录启动问题，不记录提示词、文件内容或密钥。

## 构建

安装 `.[desktop,test]` 和 `pyinstaller>=6.19,<7`，使用 Inno Setup 6+ 编译器：

```powershell
.\scripts\build-release.ps1 -InnoCompiler 'C:\path\to\ISCC.exe'
```

每次构建输出到独立的 dist 时间戳目录，保留旧包。默认不会打包用户配置或会话。

参考：[PyInstaller](https://pyinstaller.org/en/stable/usage.html)、[Inno Setup 非管理员安装](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm)。
