import json
import os
import subprocess
import hashlib
import difflib
from pathlib import Path
from datetime import datetime

import streamlit as st
from local_agent.config import Settings
from local_agent.storage import Store, empty_session
from local_agent.core import AgentCore
from local_agent.model import LANModel
from local_agent.prompt import make_system_prompt
from local_agent.files import (get_git_status, get_git_diff, file_sha256,
    safe_workspace_file, agent_diff_for_file, list_workspace_files,
    preview_language, read_file_preview)

settings = Settings.load()
from local_agent.lease import DataLease
import atexit

@st.cache_resource
def own_data_directory(path):
    lease = DataLease(Path(path)).acquire()
    atexit.register(lease.close)
    return lease

data_lease = own_data_directory(str(settings.data_dir))
store = Store(settings.data_dir)
MODEL = settings.model

st.set_page_config(
    page_title="本地开发 Agent",
    page_icon="🛠️",
    layout="wide",
)

st.markdown(
    """
<style>
    :root {
        --panel-border: rgba(128, 128, 128, 0.16);
        --muted: #8b8b8b;
    }

    header[data-testid="stHeader"] {
        height: 2.75rem;
        background: transparent;
    }

    .block-container {
        max-width: 1180px;
        padding-top: 4rem;
        padding-bottom: 6.5rem;
    }

    [data-testid="stSidebar"] {
        border-right: 1px solid var(--panel-border);
    }

    [data-testid="stSidebar"] > div:first-child {
        padding-top: 1rem;
    }

    [data-testid="stSidebar"] .stButton > button {
        min-height: 2.35rem;
        border-radius: 8px;
    }

    h1, h2, h3, h4 {
        letter-spacing: -0.02em;
    }

    .agent-topbar {
        display: flex;
        align-items: flex-end;
        justify-content: space-between;
        gap: 1rem;
        padding: 0 0 1rem 0;
        border-bottom: 1px solid var(--panel-border);
        margin-bottom: 1rem;
    }

    .agent-project-title {
        font-size: 1.22rem;
        font-weight: 680;
        line-height: 1.25;
    }

    .agent-subtle {
        color: var(--muted);
        font-size: 0.82rem;
        margin-top: 0.2rem;
        overflow-wrap: anywhere;
    }

    .agent-meta {
        color: var(--muted);
        font-size: 0.8rem;
        white-space: nowrap;
    }

    .agent-empty {
        border: 1px dashed rgba(128,128,128,0.22);
        border-radius: 12px;
        padding: 2.5rem 1.2rem;
        text-align: center;
        margin: 1.25rem 0;
        color: var(--muted);
    }

    [data-testid="stChatMessage"] {
        border-radius: 10px;
        padding: 0.1rem 0;
    }

    [data-testid="stExpander"] {
        border-radius: 10px;
        border-color: var(--panel-border);
    }

    div[data-testid="stCodeBlock"] {
        border-radius: 9px;
    }

    [data-testid="stChatInput"] {
        max-width: 1180px;
    }
</style>
""",
    unsafe_allow_html=True,
)

MAX_AGENT_STEPS = 30

SESSIONS_DIR = Path(__file__).parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)

PROJECTS_FILE = Path(__file__).parent / "projects.json"


def load_projects():
    return store.projects()


def save_projects(projects):
    store.save_projects(projects)


def normalize_project_path(path: str) -> str:
    return str(Path(path).expanduser().resolve())


def add_project(path):
    return store.add_project(path)


def touch_project(path: str):
    path = normalize_project_path(path)
    projects = load_projects()

    for project in projects:
        if normalize_project_path(project["path"]) == path:
            project["last_opened"] = datetime.now().isoformat(timespec="seconds")
            break

    projects.sort(key=lambda p: p.get("last_opened") or "", reverse=True)
    save_projects(projects)


def remove_project(project_id: str):
    projects = [p for p in load_projects() if p.get("id") != project_id]
    save_projects(projects)


def choose_folder_native():
    """
    Open a native Windows folder picker on the machine running Streamlit.
    This is intentionally host-local: when the UI is opened from another device,
    the picker still appears on the Windows host.
    """
    if os.name != "nt":
        return None

    ps_script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择要添加到 Local Agent 的项目文件夹'
$dialog.ShowNewFolderButton = $true
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    Write-Output $dialog.SelectedPath
}
"""

    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=120,
        )
    except Exception:
        return None

    selected = result.stdout.strip()
    return selected or None


def switch_workspace(path: str):
    path_obj = Path(path).expanduser().resolve()
    if not path_obj.exists() or not path_obj.is_dir():
        return False

    st.session_state.workspace = str(path_obj)
    st.session_state.agent_messages = []
    st.session_state.visible_messages = []
    st.session_state.tool_logs = []
    st.session_state.pending_command = None
    st.session_state.agent_changes = {}
    st.session_state.selected_file = None

    load_session(str(path_obj))
    touch_project(str(path_obj))
    save_session()
    return True




def session_file_for_workspace(workspace):
    return store.session_path(workspace)


def save_session():
    state = empty_session(st.session_state.workspace)
    for key in state:
        if key in st.session_state:
            state[key] = st.session_state[key]
    store.save(state)


def load_session(workspace):
    state = store.load(workspace)
    if state['status'] == 'running':
        state['status'] = 'interrupted'
    engine = AgentCore(state, LANModel(settings), store.save)
    engine.persist()
    for key, value in state.items():
        st.session_state[key] = value
    return True


def delete_session(workspace: str):
    path = session_file_for_workspace(workspace)
    if path.exists():
        path.unlink()






























def revert_agent_changes(workspace):
    result = current_core().revert()
    sync_core()
    return result['reverted'], result['skipped']



SKIP_BROWSER_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".pytest_cache",
}












def add_visible_message(role: str, content: str):
    st.session_state.visible_messages.append(
        {
            "role": role,
            "content": content,
        }
    )
    save_session()


def add_tool_log(name: str, arguments: str, result: str):
    st.session_state.tool_logs.append(
        {
            "name": name,
            "arguments": arguments,
            "result": result,
        }
    )
    save_session()


def current_core():
    state = empty_session(st.session_state.workspace)
    for key in state:
        if key in st.session_state:
            state[key] = st.session_state[key]
    return AgentCore(state, LANModel(settings), store.save, settings.max_steps)

def sync_core():
    load_session(st.session_state.workspace)

def continue_agent():
    current_core().run()
    sync_core()

def approve_command(allow):
    engine = current_core()
    engine.approve(engine.state['pending_command']['approval_id'], allow)
    sync_core()


# ------------------------------------------------------------------
# Session state
# ------------------------------------------------------------------

if "workspace" not in st.session_state:
    st.session_state.workspace = str(
        Path.home() / "agent-playground"
    )

if "visible_messages" not in st.session_state:
    st.session_state.visible_messages = []

if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []

if "tool_logs" not in st.session_state:
    st.session_state.tool_logs = []

if "pending_command" not in st.session_state:
    st.session_state.pending_command = None

if "agent_changes" not in st.session_state:
    st.session_state.agent_changes = {}

if "selected_file" not in st.session_state:
    st.session_state.selected_file = None

if "project_to_delete" not in st.session_state:
    st.session_state.project_to_delete = None

if "session_loaded" not in st.session_state:
    st.session_state.session_loaded = False

if not st.session_state.session_loaded:
    load_session(st.session_state.workspace)
    st.session_state.session_loaded = True


# ------------------------------------------------------------------
# Sidebar / project management
# ------------------------------------------------------------------

projects = load_projects()
current_workspace = str(Path(st.session_state.workspace).resolve())
current_path_obj = Path(current_workspace)

# Register an existing current workspace once.
if current_path_obj.exists() and current_path_obj.is_dir():
    if not any(
        normalize_project_path(project["path"]) == current_workspace
        for project in projects
    ):
        add_project(current_workspace)

with st.sidebar:
    st.markdown("## Local Agent")

    if st.button(
        "＋ 添加项目",
        use_container_width=True,
        type="primary",
        key="add_project_native",
    ):
        selected = choose_folder_native()

        if selected:
            selected_path = Path(selected).resolve()

            if selected_path.exists() and selected_path.is_dir():
                project = add_project(str(selected_path))
                switch_workspace(project["path"])
                st.rerun()
            else:
                st.error("选择的文件夹不可用。")

    st.caption("项目")

    projects = load_projects()

    if not projects:
        st.info("还没有项目。点击“添加项目”选择一个文件夹。")
    else:
        for project in projects:
            project_path = normalize_project_path(project["path"])
            active = (
                project_path
                == str(Path(st.session_state.workspace).resolve())
            )

            project_col, menu_col = st.columns([5, 1])

            with project_col:
                if st.button(
                    project["name"],
                    use_container_width=True,
                    type="primary" if active else "secondary",
                    key=f"open_project_{project['id']}",
                ):
                    if switch_workspace(project["path"]):
                        st.rerun()
                    else:
                        st.error("项目文件夹已不存在。")

            with menu_col:
                if st.button(
                    "⋯",
                    key=f"remove_project_{project['id']}",
                    help="项目操作",
                ):
                    st.session_state.project_to_delete = project["id"]
                    st.rerun()

            if st.session_state.project_to_delete == project["id"]:
                st.warning(
                    f"从项目列表移除“{project['name']}”？\n\n"
                    "不会删除磁盘上的项目文件。"
                )

                confirm_col, cancel_col = st.columns(2)

                with confirm_col:
                    if st.button(
                        "移除",
                        key=f"confirm_remove_{project['id']}",
                        type="primary",
                        use_container_width=True,
                    ):
                        remove_project(project["id"])
                        st.session_state.project_to_delete = None
                        st.rerun()

                with cancel_col:
                    if st.button(
                        "取消",
                        key=f"cancel_remove_{project['id']}",
                        use_container_width=True,
                    ):
                        st.session_state.project_to_delete = None
                        st.rerun()

    st.divider()

    if st.button(
        "＋ 新建会话",
        use_container_width=True,
        key="new_session_sidebar",
    ):
        delete_session(st.session_state.workspace)
        load_session(st.session_state.workspace)
        st.session_state.agent_messages = []
        st.session_state.visible_messages = []
        st.session_state.tool_logs = []
        st.session_state.pending_command = None
        st.session_state.agent_changes = {}
        st.session_state.selected_file = None
        save_session()
        st.rerun()

    with st.expander("设置", expanded=False):
        st.caption("当前模型")
        st.code(MODEL)


# ------------------------------------------------------------------
# Main header
# ------------------------------------------------------------------

current_project = next(
    (
        project
        for project in load_projects()
        if normalize_project_path(project["path"])
        == str(Path(st.session_state.workspace).resolve())
    ),
    None,
)

project_name = (
    current_project["name"]
    if current_project
    else Path(st.session_state.workspace).name or "未命名项目"
)

tool_count = len(st.session_state.tool_logs)
change_count = len(st.session_state.agent_changes)

st.markdown(
    f"""
<div class="agent-topbar">
    <div>
        <div class="agent-project-title">{project_name}</div>
        <div class="agent-subtle">{st.session_state.workspace}</div>
    </div>
    <div class="agent-meta">
        工具 {tool_count} · Agent 变更 {change_count}
    </div>
</div>
""",
    unsafe_allow_html=True,
)

chat_tab, files_tab, changes_tab, tools_tab = st.tabs(
    [
        "对话",
        "文件",
        f"变更 {change_count}",
        f"工具 {tool_count}",
    ]
)


# ------------------------------------------------------------------
# Chat tab
# ------------------------------------------------------------------

with chat_tab:
    if not st.session_state.visible_messages:
        st.markdown(
            """
<div class="agent-empty">
    <div style="font-size:1.05rem;font-weight:650;margin-bottom:0.35rem;">
        开始一个任务
    </div>
    <div>
        让 Agent 阅读、修改和测试当前项目。直接描述你的目标即可。
    </div>
</div>
""",
            unsafe_allow_html=True,
        )

    for message in st.session_state.visible_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    pending = st.session_state.pending_command

    if pending:
        st.warning("Agent 请求运行终端命令")
        st.code(
            pending["command"],
            language="powershell",
        )

        approve_col, deny_col = st.columns(2)

        with approve_col:
            if st.button(
                "允许执行",
                use_container_width=True,
                type="primary",
                key="approve_pending_command",
            ):
                approve_command(True)
                st.rerun()

        with deny_col:
            if st.button(
                "拒绝",
                use_container_width=True,
                key="deny_pending_command",
            ):
                approve_command(False)
                st.rerun()


# ------------------------------------------------------------------
# Files tab
# ------------------------------------------------------------------

with files_tab:
    files_search_col, files_refresh_col = st.columns([5, 1])

    with files_search_col:
        browser_query = st.text_input(
            "筛选项目文件",
            placeholder="输入文件名或路径...",
            key="file_browser_query",
            label_visibility="collapsed",
        )

    with files_refresh_col:
        if st.button(
            "刷新",
            use_container_width=True,
            key="refresh_file_browser",
        ):
            st.rerun()

    browser_workspace = Path(
        st.session_state.workspace
    ).resolve()

    browser_files = list_workspace_files(
        browser_workspace,
        browser_query,
    )

    if browser_files:
        current_index = 0

        if st.session_state.selected_file in browser_files:
            current_index = (
                browser_files.index(
                    st.session_state.selected_file
                )
                + 1
            )

        selected_option = st.selectbox(
            "文件",
            ["（选择文件）"] + browser_files,
            index=current_index,
            key="file_browser_select",
            label_visibility="collapsed",
        )

        st.session_state.selected_file = (
            None
            if selected_option == "（选择文件）"
            else selected_option
        )

        st.caption(f"{len(browser_files)} 个文件")
    else:
        st.session_state.selected_file = None
        st.caption("没有找到符合条件的文件。")

    selected_file = st.session_state.get("selected_file")

    if selected_file:
        preview_content, preview_error = read_file_preview(
            browser_workspace,
            selected_file,
        )

        st.markdown(f"### `{selected_file}`")
        st.caption(str(browser_workspace / selected_file))

        if preview_error:
            st.info(preview_error)
        else:
            st.code(
                preview_content,
                language=preview_language(selected_file),
                line_numbers=True,
            )
    else:
        st.info("选择一个文件即可在这里预览。")


# ------------------------------------------------------------------
# Changes tab
# ------------------------------------------------------------------

with changes_tab:
    workspace_for_changes = Path(
        st.session_state.workspace
    ).resolve()

    refresh_col, _ = st.columns([1, 5])

    with refresh_col:
        if st.button(
            "刷新",
            use_container_width=True,
            key="refresh_changes",
        ):
            st.rerun()

    agent_changes = st.session_state.agent_changes

    if agent_changes:
        st.markdown("### Agent 修改")

        for relative_path, change in agent_changes.items():
            target = safe_workspace_file(
                workspace_for_changes,
                relative_path,
            )

            current_hash = file_sha256(target)
            still_agent_state = (
                current_hash == change.get("after_hash")
            )

            status = "已修改"
            if not change.get("existed_before"):
                status = "已创建"

            if still_agent_state:
                st.markdown(
                    f"**`{relative_path}`** · Agent {status}"
                )
            else:
                st.warning(
                    f"{relative_path}：Agent 修改后该文件又发生了变化。"
                    "为避免覆盖你的手工修改，已禁用自动回滚。"
                )

            diff_text = agent_diff_for_file(
                workspace_for_changes,
                relative_path,
                change,
            )

            with st.expander(
                f"查看差异 · {relative_path}",
                expanded=False,
            ):
                st.code(
                    diff_text,
                    language="diff",
                )

        keep_col, revert_col = st.columns(2)

        with keep_col:
            if st.button(
                "保留 Agent 修改",
                use_container_width=True,
                type="primary",
                key="keep_agent_changes",
            ):
                kept = list(
                    st.session_state.agent_changes.keys()
                )

                st.session_state.agent_changes = {}

                add_visible_message(
                    "assistant",
                    "已接受 Agent 修改：" + ", ".join(kept),
                )

                save_session()
                st.rerun()

        with revert_col:
            if st.button(
                "回滚 Agent 修改",
                use_container_width=True,
                key="revert_agent_changes",
            ):
                reverted, skipped = revert_agent_changes(
                    workspace_for_changes
                )

                parts = []

                if reverted:
                    parts.append(
                        "已回滚：" + ", ".join(reverted)
                    )

                if skipped:
                    parts.append(
                        "已跳过：" + "; ".join(skipped)
                    )

                add_visible_message(
                    "assistant",
                    "\n\n".join(parts)
                    if parts
                    else "没有可回滚的 Agent 修改。",
                )

                st.rerun()
    else:
        st.caption("当前会话没有追踪到 Agent 修改。")

    st.markdown("### Git 变更")

    git_status = get_git_status(
        workspace_for_changes
    )

    git_diff = get_git_diff(
        workspace_for_changes
    )

    if not git_status:
        st.caption("没有未提交的 Git 变更。")
    else:
        st.code(git_status)

        if git_diff:
            with st.expander(
                "查看完整 Git 差异",
                expanded=False,
            ):
                st.code(
                    git_diff,
                    language="diff",
                )
        else:
            st.caption(
                "Git 检测到了变更，但没有可显示的未暂存文本差异。"
            )


# ------------------------------------------------------------------
# Tools tab
# ------------------------------------------------------------------

with tools_tab:
    if st.session_state.tool_logs:
        for index, log in enumerate(
            st.session_state.tool_logs,
            start=1,
        ):
            with st.expander(
                f"{index}. {log['name']}",
                expanded=False,
            ):
                st.caption("参数")
                st.code(
                    log["arguments"],
                    language="json",
                )

                st.caption("结果")
                st.code(
                    log["result"][:10000],
                )
    else:
        st.caption("当前会话还没有工具调用。")


# ------------------------------------------------------------------
# Chat input
# ------------------------------------------------------------------

prompt = st.chat_input(
    "告诉 Agent 你希望它在这个项目中完成什么...",
    disabled=st.session_state.pending_command is not None,
)

if prompt:
    workspace = Path(
        st.session_state.workspace
    ).resolve()

    current_core().submit(prompt)
    sync_core()
    st.rerun()
