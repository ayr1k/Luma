import hashlib
import difflib
import subprocess
from pathlib import Path
from .tools import safe_path as safe_workspace_file

def get_git_status(workspace: Path, executable=None) -> str:
    """Return short Git status for the current workspace."""
    try:
        result = subprocess.run(
            [executable or "git", "status", "--short"],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return ""

        return result.stdout.strip()

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

def get_git_diff(workspace: Path, executable=None) -> str:
    """Return the current unstaged Git diff for the workspace."""
    try:
        result = subprocess.run(
            [executable or "git", "diff", "--no-ext-diff", "--no-textconv", "--", "."],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return ""

        return result.stdout

    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

def file_sha256(path: Path):
    """Return SHA-256 for a file, or None if it does not exist."""
    if not path.exists() or not path.is_file():
        return None

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)

    return digest.hexdigest()

def agent_diff_for_file(workspace: Path, relative_path: str, change: dict) -> str:
    """Build a diff between the pre-agent snapshot and the current file."""
    target = safe_workspace_file(workspace, relative_path)

    before = change.get("before_content")
    if before is None:
        before = ""

    try:
        current = target.read_text(encoding="utf-8") if target.exists() else ""
    except UnicodeDecodeError:
        return "(binary or non-UTF-8 file; diff unavailable)"

    before_lines = before.splitlines(keepends=True)
    current_lines = current.splitlines(keepends=True)

    return "".join(
        difflib.unified_diff(
            before_lines,
            current_lines,
            fromfile=f"a/{relative_path}",
            tofile=f"b/{relative_path}",
        )
    ) or "(no text difference)"

def list_workspace_files(workspace: Path, query: str = "", max_files: int = 1000):
    """Return UTF-8-friendly workspace file paths for the sidebar browser."""
    workspace = workspace.resolve()
    query = query.strip().lower()
    files = []

    try:
        candidates = workspace.rglob("*")
    except OSError:
        return []

    for path in candidates:
        if len(files) >= max_files:
            break

        if not path.is_file():
            continue

        try:
            safe_workspace_file(workspace, str(path.relative_to(workspace)))
            relative = path.relative_to(workspace)
        except ValueError:
            continue

        if any(part in SKIP_BROWSER_DIRS for part in relative.parts):
            continue

        relative_text = relative.as_posix()

        if query and query not in relative_text.lower():
            continue

        files.append(relative_text)

    return sorted(files, key=lambda item: item.lower())

def preview_language(path: str) -> str:
    """Map common file extensions to Streamlit code languages."""
    suffix = Path(path).suffix.lower()

    mapping = {
        ".py": "python",
        ".js": "javascript",
        ".jsx": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".json": "json",
        ".yml": "yaml",
        ".yaml": "yaml",
        ".toml": "toml",
        ".html": "html",
        ".css": "css",
        ".scss": "scss",
        ".md": "markdown",
        ".sh": "bash",
        ".ps1": "powershell",
        ".bat": "batch",
        ".cmd": "batch",
        ".sql": "sql",
        ".xml": "xml",
        ".ini": "ini",
        ".cfg": "ini",
    }

    return mapping.get(suffix, "text")

def read_file_preview(workspace: Path, relative_path: str, max_bytes: int = 512_000):
    """Read a text file for preview without loading arbitrarily large files."""
    target = safe_workspace_file(workspace, relative_path)

    if not target.exists() or not target.is_file():
        return None, "文件不存在。"

    try:
        size = target.stat().st_size
    except OSError as exc:
        return None, f"无法读取文件信息：{exc}"

    if size > max_bytes:
        return None, f"文件过大（{size / 1024:.1f} KB），当前预览上限为 {max_bytes / 1024:.0f} KB。"

    try:
        return target.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return None, "该文件不是 UTF-8 文本文件，暂不支持预览。"
    except OSError as exc:
        return None, f"读取文件失败：{exc}"

SKIP_BROWSER_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".idea", ".pytest_cache"}
