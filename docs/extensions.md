# Luma 0.8.0 SoHo 扩展开发指南

## 使用与目录

扩展中心支持导入 ZIP（plugin.json 必须位于 ZIP 根目录）或导入开发目录。目录导入是副本，修改后重新导入。导入不执行代码，首次安装及更新均禁用插件；代码插件启用时需明确确认信任。

默认数据目录 `%LOCALAPPDATA%\LocalAgent`，配置了 AGENT_DATA_DIR 时以配置为准：

- `skills/<id>/SKILL.md`：用户 Skill，可直接编辑，在扩展中心重新扫描。
- `extensions/packages/<plugin-id>/`：已安装包，不要直接编辑；改变内容会使插件失效，需要重新导入。
- `extensions/data/<plugin-id>/`：插件持久数据，卸载后保留。
- `extensions/trash/`：更新前的包和卸载/删除的副本。不提供自动清理；如需恢复插件可将其目录重新导入，恢复用户 Skill 则复制回 skills 目录。

用户可在输入框输入 `/` 或点击 `/ Skills`，显式选择最多 8 个 Skill。只有已选择的正文载入当前系统提示；参考资料通过工具按需读取。消息保留 Skill 快照，编辑历史提问重生成时保留原快照。参考文件不是快照，读取时使用当前已启用版本。Skill 内容随消息发送到配置的模型主机，不要写入密钥。移除标签不删除已发送的历史内容。

## Skill 格式

每个 Skill 文件夹包含 UTF-8 `SKILL.md`，可附 `references/` 和 `templates/` 文本资料。文件名大小写按此规范。

```markdown
---
name: 清晰写作
description: 起草或改写中文说明
---
先给可用成稿，再说明必要的修改理由。
需要检查清单时读取 references/checklist.md。
```

当前 front matter 解析 name、description、author、version、min_luma、max_luma、tested_luma 单行字符串，不支持完整 YAML。正文最多 24000 字符，选择的正文合计最多 48000 字符；参考资料每个最多 64 KB，必须是 UTF-8 文本。文件夹 ID 为小写字母开头的小写字母、数字、短横线，最多 40 字符。插件内 Skill 为只读。

Skill 是工作说明，不能解除 Chat/Plan/Work 权限或跳过审批。Skill 中的脚本不会被自动执行。Chat 可读取所选 Skill 的附属资料但不能读取项目文件；Plan 可使用已有只读项目工具；代码插件仅在 Work 中执行。

## 纯 Skill 插件

```json
{
  "id": "writing-kit",
  "name": "写作助手",
  "description": "可复用的写作方法",
  "version": "1.0.0",
  "api_version": 1,
  "min_luma": "0.6.0",
  "max_luma": "0.7.99",
  "skills": ["clear-writing"]
}
```

结构：`plugin.json` 与 `skills/clear-writing/SKILL.md`。参见源码 `examples/writing-kit`。包和 Skill 均启用后才出现在调用列表。

## Python 工具插件

参见 `examples/project-stats/plugin.json` 和 `main.py`。额外声明：

```json
{
  "runtime": "python",
  "entrypoint": "main.py",
  "permissions": ["local-code"],
  "tools": [{
    "name": "count-files",
    "description": "统计当前项目顶层文件",
    "input_schema": {"type": "object", "properties": {}, "additionalProperties": false}
  }]
}
```

将这些字段与前面的 id/name/version/description/api_version 合并。工具名使用相同 ID 规则；参数使用 JSON Schema 2020-12，顶层必须是 object，不支持 $ref。每包最多 20 个工具、20 个 Skill。版本为 x.y.z，兼容范围含首尾；省略范围默认 0.6.0—0.7.99。

模型只获得本轮通过 $ 明确选择的已启用工具目录，通过 `plugin_tool(plugin, tool, input)` 调用；Luma 验证参数并展示审批。审批绑定包摘要、输入参数和项目。拒绝不运行，审批被消费后先写入磁盘再执行，崩溃不会自动重放。

每次调用新建独立 Python 进程。入口脚本从标准输入读取一个 JSON：

```json
{"api_version":1,"tool":"count-files","input":{},"workspace":"C:\\my-project","data_directory":"C:\\plugin-data"}
```

标准输出必须是单个 JSON 对象 `{"text":"工具结果"}`。text 最多 64000 字符；进程输出文件最多 1 MB，运行上限 30 秒。调试输出使用 stderr，不要打印密钥。当前界面只显示受控错误，不展示原始 stderr。允许读取同目录模块，但只承诺 Python 标准库可用；不执行 pip 或安装脚本，不依赖用户另装 Python。

**独立进程不是操作系统沙箱。** 代码具有用户账户的本机文件与网络权限。插件修改不会自动纳入 agent_changes，不支持 Luma 自动撤销。仅安装可信代码。运行时不把 Luma API 密钥作为参数或环境变量传入；这不能阻止受信任代码主动访问用户能访问的文件。Windows 用 Job Object 管理进程及后代生命周期，任务取消、超时及正常退出后清理进程。

## 包限制与生命周期

ZIP 最大 8 MB，解压总计 25 MB，单文件 10 MB，最多 500 个文件。拒绝路径越界、驱动器路径、符号链接、目录联接、Windows 保留名称、不区分大小写的重复路径和 .env 文件。开发目录忽略 .git、.venv、node_modules、__pycache__。

最多安装 100 个插件、同时启用 20 个代码插件。安装先预览内容摘要，再暂存验证并替换。注册失败恢复旧包。更新会撤销旧信任；运行中或等待审批时禁止更改扩展。

本版不提供插件市场、远程自动更新、任意界面注入或第三方依赖安装。模型能否正确选择并调用工具仍取决于模型的工具调用能力。

## 验证示例

1. 导入 writing-kit ZIP，启用后在 Skills 中查看「清晰写作」。
2. 新建对话，在 `/ Skills` 勾选它，发送文案任务。
3. 导入 project-stats ZIP，确认信任后启用，打开一个测试项目切到 Work。
4. 通过 `$ 插件` 选择 project-stats，让模型调用统计工具；批准后结果包含 files/directories。
5. 拒绝另一轮调用，工具记录应显示 DENIED；切到 Chat/Plan 后代码工具不可用。

模型接入测试需要实际 LAN 主机；自动化测试使用确定性模型，验证客户端协议与权限而非模型判断质量。


## 0.6.2 新增字段与预置插件

清单 `category` 缺省为 `tools`。0.6.2 仅允许该类别；0.6.3 新增声明式 `appearance` / `software`，见下文。工具可以声明 `effect: "read"` 或 `"write"`，缺省按 write 显示；这是说明字段，不能授予权限或跳过审批，也不能作为不受信任代码的安全依据。

四个预置插件源码位于 `preset_plugins/`。它们的入口调用 Luma 自带 `local_agent.builtin_tools.dispatch`，依赖的 Pillow 与 pypdf 随应用打包；这个模块是本版内置实现，不是第三方插件的稳定 API。第三方插件仍仅承诺标准库运行，不自动安装依赖。

安装器只把勾选的包复制到程序目录 `Bundled-Plugins/`。应用启动时在数据目录写入包副本和导入摘要记录，来源为 bundled。首次安装及内容升级都默认禁用，逐次执行审批保持不变；未变化的包保留启用状态。卸载记录通过导入摘要保留，不在下次启动或捆绑更新时自动恢复；本地导入替换的包不会被覆盖。

文件整理 `plan-moves` 的返回包含 plan_id 和 moves。`apply-moves` 必须提交原样完整 moves，确保审批窗口显示具体路径，而非只显示不可读的 ID。计划保存源文件 SHA256；应用前检查所有项目范围、目标冲突和源摘要。调用先持久化 applying，再逐个独占创建目标、复制校验、移除源文件并记录。崩溃后不重放；它不是跨文件事务，部分完成时需人工核对，未提供自动撤销。每批最多 50 个文件、200 MB，单个不超过 50 MB。

## 0.6.3 声明式界面插件

外观与软件功能插件使用受控的宿主能力，不加载包内 JavaScript、CSS、动态网页或本地代码。`contribution` 只接受 `slot` 与 `defaults`。下面是完整的配色插件示例：

```json
{
  "id": "my-midnight", "name": "我的午夜主题", "version": "1.0.0",
  "description": "午夜蓝与青色强调色", "api_version": 1,
  "min_luma": "0.6.3", "category": "appearance",
  "contribution": {"slot": "palette", "defaults": {"palette": "midnight", "accent": "#65c9ce"}}
}
```

将 plugin.json 放在 ZIP 根目录，或直接导入开发目录。配置在扩展中心保存到注册表 config，与包文件分离，不改变包摘要；重新导入保留兼容配置并禁用插件。开发者不应在包中包含用户设置。无代码插件无需 local-code 信任，但仍默认禁用。同一 slot 只能启用一个；其他 slot 可组合。

| 分类 / slot | 配置与范围 |
|---|---|
| appearance / palette | palette: graphite、white、midnight、warm；accent: #RRGGBB |
| appearance / typography | ui_font、body_font、code_font: 本机字体名；size: 12—24；line_height: 1.3—2.5；width: 520—1200 |
| appearance / icons | style: thin、rounded，改变核心导航和操作图标 |
| appearance / material | opacity: 0.7—1；blur: 0—20，仅应用内面板 |
| software / widget | topmost: true/false，标题栏或状态文字可拖动，共用主窗口任务 |
| software / hotkey | shortcut: Ctrl+Alt+L、Ctrl+Shift+Space、Alt+Shift+L；注册冲突在配置页报告 |
| software / snippets | phrases: 最多 50 条，每条 title 1—80、category 最多 40、text 1—8000 字符 |

未知字段、越界值、代码入口与权限声明会被拒绝。主题目前限于宿主提供的四套配色及自选强调色；图标限于两种宿主样式。暂不支持任意主题 CSS、自带字体文件、第三方原生窗口或任意软件功能脚本。透明效果是应用内面板材质，非 Windows 桌面穿透或系统云母材质。缺失本机字体时回退系统字体。预置包既是可安装插件，也是最小开发示例。

`POST /v1/extensions` 新动作：`configure`（id、config）、`reset-appearance`。`GET /v1/extensions` 返回 contribution、config、config_schema。服务端校验配置，并在启用时检查包摘要。扩展变更仍禁止在运行中或有待审批任务时进行。

发送消息增加 `plugins: ["plugin-id"]`，最多 12 个；不传表示本轮不启用任何代码插件。只选择 Skill 不会授予所属插件工具权限。后端校验每次工具调用属于本轮选择；Chat/Plan 仍不能执行插件工具。会话 active_plugins 和历史用户消息保留选择，重生成时复用并重新校验。旧会话未声明此字段时按空选择处理，已有待审批请求保留原审批流程。

默认安装包含 11 个插件（4 工具、4 外观、3 功能）和 5 个独立 Skill，自定义可逐项选择；新插件默认禁用，原先启用的未变化包保持状态。取消勾选不是卸载已有包；请在扩展中心卸载。


## 0.6.4 数量与桌面能力更新

安装上限从 30 调整为 100，启用代码插件从 8 调整为 20，每轮工具插件选择从 8 调整为 12。声明式外观/软件插件占安装名额，但不占代码插件启用名额；同一 slot 仍只能启用一个。Skill 每轮 8 项及 48000 字符总量保持不变。扩展列表 API 返回 limits，发送消息 plugins 数组最多 12 项。不会因放宽上限自动启用或自动选择插件。

全局唤起支持 Ctrl+Alt、Ctrl+Shift、Alt+Shift 与 L、K、J、Space、F8、F9 的 18 个组合；仍需 Windows 注册成功，占用时会报告失败。API 返回的配置 schema 包含可选组合。悬浮窗位置保存在用户数据目录 widget-position.json，恢复时按可用显示器区域限位。插件清单不变，旧配置可继续使用。


## 0.6.5 详情、检查与配置迁移
清单可选字段：`author`、`changelog`（字符串，各最多 8000 字符），`examples`（最多 20 条字符串，每条最多 2000 字符）。旧包仍兼容。

`python -m local_agent check-extension ./my-plugin` 检查目录或 ZIP，输出 JSON；成功退出码 0，失败 1。静态检查不会导入或执行插件，包含包路径/大小规则、清单兼容性、配置和工具参数 schema、Python 语法及文件存在性。

配置迁移仅覆盖宿主定义的 contribution 配置。格式为 `{ "format":"luma-extension-settings", "version":1, "plugins":[{"id":"luma-palette","slot":"palette","version":"1.0.0","config":{"palette":"midnight","accent":"#b7dbc8"}}] }`。预览和应用均重新校验；整批校验成功后原子保存。不导入 enabled/trusted，不运行代码；不存在的插件跳过，贡献类型不一致拒绝。

API extension-action 新增 details、diagnose、validate、export-config、preview-config、import-config。项目 metadata 增加 default_skills 和 default_plugins；默认设置不会作为隐式授权覆盖请求中明确的扩展选择。


## 0.7.0 多任务兼容与帮助入口
本指南已打包到“帮助 → 扩展开发指南”，离线可读。

插件 API 仍为 1；每次调用的 workspace 是当前任务所属项目的真实目录。同项目任务共享文件，但历史、工具队列、审批、变更追踪独立。不要缓存上一任务的授权；读写前重新检查当前文件。宿主串行执行任务，并在同项目其他会话待审批时阻止新执行和回滚。

11 个预置插件更新为 1.1.0，max_luma 更新为 0.7.99，tested_luma 为 0.7.0；min_luma 保留原最低版本。插件详情分别显示声明范围和实际验证版本。第三方包显式声明 max_luma=0.6.99 时仍被拒绝；未提供上限的 API 1 包默认按 0.7.99 校验，应主动声明范围。

Skill front matter 支持 author、version、min_luma、max_luma、tested_luma。范围不兼容或格式无效会出现在诊断中；未声明范围的旧 Skill 保持兼容。5 个独立预置 Skill 和 4 个插件附带 Skill 均补充多任务说明及兼容声明。

安装升级只自动替换未修改过的预置 Skill；用户编辑版本保留。预置插件包更新后按原机制撤销启用和信任，配置保留，需重新启用。更新不是自动授权。

## 0.8.0：版本与升级

请显式填写 min_luma、max_luma、tested_luma。API 仍为 1。未填写最高版本时沿用旧默认 0.7.99，因此旧包需要作者核验后声明新范围，不能仅删除范围绕过检查。

预置插件和 Skill 的独立版本为 1.2.0，已验证 Luma 0.8.0，最高支持 0.8.99。LTS 安装选择使用其原有预置包。

详情页显示实际安装来源、目录和可回退版本；重新导入 ZIP/目录进行升级。安装前可检查新旧版本和权限，安装后保留配置及 extensions/data。更新不是自动授权：请重新启用可信插件。

“回退上一个版本”恢复已保存的包，保留当前配置并按目标版本校验。最多提供最近 5 个历史版本入口；trash 中旧副本不会自动清理。旧包不兼容主程序时拒绝回退，使用作者发布的适配版。

预置更新先验证旧文件完整性，再验证新包兼容性。历史包按完整校验识别，用户修改过的文件不会被覆盖；主动卸载不会自动恢复。遇到升级提示可先使用“检查预置更新”，无需清理所有缓存。检查仍失败时保留数据并重新导入官方包。
