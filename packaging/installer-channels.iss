#ifndef SourceDir
  #define SourceDir "..\dist\Luma"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif
#ifndef LTSSourceDir
  #define LTSSourceDir "..\dist\Luma-LTS"
#endif
[Setup]
AppId={{F0720B19-4EE9-42AE-B5C0-3FF362DB8B3A}
AppName=Luma
AppVersion={code:SelectedVersion}
VersionInfoVersion=0.7.5
AppVerName={code:SelectedName}
DefaultDirName={localappdata}\Programs\LocalAgent
DefaultGroupName=Luma
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Luma-Setup-0.7.5
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Luma.exe
[InstallDelete]
Type: files; Name: "{app}\LocalAgent.exe"
Type: files; Name: "{autodesktop}\Local Agent.lnk"
Type: files; Name: "{userprograms}\Local Agent\Local Agent.lnk"
[Types]
Name: "default"; Description: "默认安装（包含全部预置插件和 Skill）"
Name: "custom"; Description: "自定义安装（选择插件和 Skill）"; Flags: iscustom
[Components]
Name: "core"; Description: "Luma 主程序"; Types: default custom; Flags: fixed
Name: "skills"; Description: "预置 Skill（可编辑，不覆盖已有文件）"; Types: default
Name: "skills\luma_writing"; Description: "写作与润色"; Types: default
Name: "skills\luma_code_review"; Description: "代码审查"; Types: default
Name: "skills\luma_debugging"; Description: "故障排查"; Types: default
Name: "skills\luma_implementation_plan"; Description: "需求拆解与实施计划"; Types: default
Name: "skills\luma_document_summary"; Description: "文档总结与行动项"; Types: default
Name: "plugins"; Description: "预置工具插件（安装后需启用）"; Types: default
Name: "plugins\luma_project_overview"; Description: "项目概览"; Types: default
Name: "plugins\luma_document_reader"; Description: "文档读取"; Types: default
Name: "plugins\luma_image_tools"; Description: "图片处理"; Types: default
Name: "plugins\luma_file_organizer"; Description: "文件整理"; Types: default
Name: "appearance"; Description: "预置外观插件（安装后需启用）"; Types: default
Name: "appearance\luma_palette"; Description: "配色工作室"; Types: default
Name: "appearance\luma_typography"; Description: "阅读排版"; Types: default
Name: "appearance\luma_icons"; Description: "轻盈图标"; Types: default
Name: "appearance\luma_material"; Description: "半透明面板"; Types: default
Name: "software"; Description: "预置软件功能插件（安装后需启用）"; Types: default
Name: "software\luma_widget"; Description: "桌面悬浮组件"; Types: default
Name: "software\luma_hotkey"; Description: "全局唤起"; Types: default
Name: "software\luma_snippets"; Description: "快捷短语"; Types: default
[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked
[Files]
Source: "..\LICENSE"; DestDir: "{app}"; Components: core; Flags: ignoreversion
Source: "..\docs\phosphor-LICENSE.txt"; DestDir: "{app}\licenses"; Components: core; Flags: ignoreversion
Source: "{#SourceDir}\*"; Excludes: "Bundled-Plugins\*,Preset-Skills\*"; DestDir: "{app}"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs; Check: IsLatest
Source: "{#LTSSourceDir}\*"; Excludes: "Bundled-Plugins\*,Preset-Skills\*"; DestDir: "{app}"; Components: core; Flags: ignoreversion recursesubdirs createallsubdirs; Check: IsLTS
Source: "..\presets\luma-writing\SKILL.md"; DestDir: "{code:SkillsDirectory}\luma-writing"; Components: skills\luma_writing; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\presets\luma-writing\SKILL.md"; DestDir: "{app}\Preset-Skills\luma-writing"; Components: skills\luma_writing; Flags: ignoreversion
Source: "..\presets\luma-code-review\SKILL.md"; DestDir: "{code:SkillsDirectory}\luma-code-review"; Components: skills\luma_code_review; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\presets\luma-code-review\SKILL.md"; DestDir: "{app}\Preset-Skills\luma-code-review"; Components: skills\luma_code_review; Flags: ignoreversion
Source: "..\presets\luma-debugging\SKILL.md"; DestDir: "{code:SkillsDirectory}\luma-debugging"; Components: skills\luma_debugging; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\presets\luma-debugging\SKILL.md"; DestDir: "{app}\Preset-Skills\luma-debugging"; Components: skills\luma_debugging; Flags: ignoreversion
Source: "..\presets\luma-implementation-plan\SKILL.md"; DestDir: "{code:SkillsDirectory}\luma-implementation-plan"; Components: skills\luma_implementation_plan; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\presets\luma-implementation-plan\SKILL.md"; DestDir: "{app}\Preset-Skills\luma-implementation-plan"; Components: skills\luma_implementation_plan; Flags: ignoreversion
Source: "..\presets\luma-document-summary\SKILL.md"; DestDir: "{code:SkillsDirectory}\luma-document-summary"; Components: skills\luma_document_summary; Flags: onlyifdoesntexist uninsneveruninstall
Source: "..\presets\luma-document-summary\SKILL.md"; DestDir: "{app}\Preset-Skills\luma-document-summary"; Components: skills\luma_document_summary; Flags: ignoreversion
Source: "..\preset_plugins\luma-project-overview\*"; DestDir: "{app}\Bundled-Plugins\luma-project-overview"; Components: plugins\luma_project_overview; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-document-reader\*"; DestDir: "{app}\Bundled-Plugins\luma-document-reader"; Components: plugins\luma_document_reader; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-image-tools\*"; DestDir: "{app}\Bundled-Plugins\luma-image-tools"; Components: plugins\luma_image_tools; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-file-organizer\*"; DestDir: "{app}\Bundled-Plugins\luma-file-organizer"; Components: plugins\luma_file_organizer; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-palette\*"; DestDir: "{app}\Bundled-Plugins\luma-palette"; Components: appearance\luma_palette; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-typography\*"; DestDir: "{app}\Bundled-Plugins\luma-typography"; Components: appearance\luma_typography; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-icons\*"; DestDir: "{app}\Bundled-Plugins\luma-icons"; Components: appearance\luma_icons; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-material\*"; DestDir: "{app}\Bundled-Plugins\luma-material"; Components: appearance\luma_material; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-widget\*"; DestDir: "{app}\Bundled-Plugins\luma-widget"; Components: software\luma_widget; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-hotkey\*"; DestDir: "{app}\Bundled-Plugins\luma-hotkey"; Components: software\luma_hotkey; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\preset_plugins\luma-snippets\*"; DestDir: "{app}\Bundled-Plugins\luma-snippets"; Components: software\luma_snippets; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Luma"; Filename: "{app}\Luma.exe"
Name: "{autodesktop}\Luma"; Filename: "{app}\Luma.exe"; Tasks: desktopicon
[Run]
Filename: "{app}\Luma.exe"; Description: "Launch Luma"; Flags: nowait postinstall skipifsilent

[Code]

var ChannelPage: TInputOptionWizardPage;
function IsLTS: Boolean;
begin
  Result := False;
  if Assigned(ChannelPage) then Result := ChannelPage.SelectedValueIndex = 1;
end;
function IsLatest: Boolean;
begin Result := not IsLTS; end;
function SelectedVersion(Param: String): String;
begin
  if IsLTS then Result := '0.7.2' else Result := '0.7.5';
end;
function SelectedName(Param: String): String;
begin
  if IsLTS then Result := 'Luma 0.7.2 LTS' else Result := 'Luma 0.7.5 Latest';
end;
procedure InitializeWizard;
begin
  ChannelPage := CreateInputOptionPage(wpWelcome, '选择更新渠道',
    'Latest 或长期支持版 LTS',
    'Latest 提供最新功能；LTS 以稳定使用和插件兼容为优先。覆盖切换前请退出托盘并备份用户数据。两条渠道共用安装位置，不能同时运行。', True, False);
  ChannelPage.Add('Latest 0.7.5 — 文件变更审阅与安全撤销');
  ChannelPage.Add('LTS 0.7.2 — 首个长期支持锚点');
  ChannelPage.SelectedValueIndex := 0;
  if Lowercase(ExpandConstant('{param:CHANNEL|latest}')) = 'lts' then ChannelPage.SelectedValueIndex := 1;
end;

function SkillsDirectory(Param: String): String;
var DataDir: String;
begin
  DataDir := GetEnv('AGENT_DATA_DIR');
  if DataDir = '' then
    DataDir := ExpandConstant('{localappdata}\LocalAgent');
  if (DataDir = '~') then
    DataDir := GetEnv('USERPROFILE')
  else if (Copy(DataDir, 1, 2) = '~\') or (Copy(DataDir, 1, 2) = '~/') then
    DataDir := GetEnv('USERPROFILE') + Copy(DataDir, 2, Length(DataDir));
  Result := AddBackslash(ExpandFileName(DataDir)) + 'skills';
end;
