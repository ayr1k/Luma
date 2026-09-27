# Luma 0.5.0 design QA

final result: passed

Target: user-provided dark desktop screenshot, 1280 px wide. Implementation: Luma running through an isolated loopback API and the native Bridge adapter, captured in Codex in-app browser at 1280 × 960. Source OS title bar cropped for comparison. Side-by-side evidence saved to the task's work/luma-design-comparison.png; final user-facing image is outputs/Luma-0.5.0界面.png.

Scope is a stylistic redesign, not a literal clone of ChatGPT data or branding. Intentional differences: Luma name/icon, actual available project list, three modes and dedicated settings controls; no unsupported microphone, account, sharing, or pinning controls. Both views show a populated conversation. Message content and count intentionally differ because implementation uses isolated test conversations.

Composition: narrow icon rail, secondary project sidebar, neutral dark canvas, right-aligned user bubbles, unboxed assistant replies, and rounded bottom composer match the reference's hierarchy. Main content is capped at 780 px; sidebar plus rail is 324 px. Chinese system font, understated borders, gray tokens, and consistent monochrome library icons reviewed. Full capture has enough detail to inspect the composer and navigation; no additional crop was required. In-app capture compression softens text in the exported image; this is not an application font effect.

Interaction verification: Chat response; Plan reads README and returns plan without writing; Work writes the isolated demo file, pauses for echo approval, resumes and completes. Parameter form saves Temperature 0.3. Software form changes light/dark appearance and retains the choice after reload. Model list, project selection, native mode selector, current-mode hints, busy controls and approval cards were inspected.

Resolved P1: model-list refresh inadvertently cleared loaded preferences, preventing settings dialogs from opening. Removed the extra reset; verified both settings pages save successfully after reload. No new console errors appeared after the fix; old captured errors remain in browser history.

Final P0/P1/P2: none within the requested desktop scope. P3: extensive Markdown tables and syntax highlighting remain future enhancements. Minimum native window size remains 850 × 600; this release is a desktop application, not a mobile product.


## 0.7.1
- 1280×720 深色/浅色验证；搜索与筛选左边缘均 x=72。
- 模式菜单向上展开，鼠标选择与 Home/Enter/Esc、菜单互斥验证；执行中禁用。
- 项目创建子任务、选中强调、完成状态、搜索与筛选验证。
- 文件高亮保留；清空选择后代码行数为 0，提示使用 Segoe UI / Microsoft YaHei。
- 166 项测试通过，2 项环境限制跳过。

## 0.7.2
- 深浅色状态菜单、Home/End/Enter/Esc、筛选复位验证。
- 运行期间侧栏 7 个按钮 disabled=true 且 opacity=1，结束后临时锁定类为 0。
- 主页面 page-enter 220ms，弹窗 panel-enter 180ms，菜单 menu-enter 140ms；流式内容不触发入场动画。
- 浅色菜单背景 rgb(255,255,255)，文字 rgb(37,37,37)；深色外观检查通过。
- 166 passed / 2 skipped；凭据存储自检的既有环境限制不变。
