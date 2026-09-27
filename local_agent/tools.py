import json
import subprocess
from pathlib import Path

def safe_path(workspace: Path, relative_path: str) -> Path:
    target = (workspace / relative_path).resolve()
    workspace = workspace.resolve()

    try:
        target.relative_to(workspace)
    except ValueError:
        raise ValueError("Path escapes workspace sandbox")

    return target

def list_files(workspace: Path, path: str = "."):
    target = safe_path(workspace, path)

    if not target.exists():
        return f"ERROR: {path} does not exist"

    if not target.is_dir():
        return f"ERROR: {path} is not a directory"

    items = []

    for item in sorted(target.iterdir()):
        rel = item.relative_to(workspace)
        suffix = "/" if item.is_dir() else ""
        items.append(str(rel) + suffix)

    return "\n".join(items) if items else "(empty directory)"

def read_file(workspace: Path, path: str):
    target = safe_path(workspace, path)

    if not target.exists():
        return f"ERROR: {path} does not exist"

    if not target.is_file():
        return f"ERROR: {path} is not a file"

    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"ERROR: {path} is not a UTF-8 text file"

def write_file(workspace: Path, path: str, content: str):
    target = safe_path(workspace, path)

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return f"Successfully wrote {path}"

def apply_patch(workspace: Path, path: str, old_text: str, new_text: str):
    target = safe_path(workspace, path)

    if not target.exists():
        return f"ERROR: {path} does not exist"

    if not target.is_file():
        return f"ERROR: {path} is not a file"

    try:
        content = target.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return f"ERROR: {path} is not a UTF-8 text file"

    count = content.count(old_text)

    if count == 0:
        return (
            "ERROR: exact text to replace was not found. "
            "Read the file again before retrying."
        )

    if count > 1:
        return (
            f"ERROR: text occurs {count} times. "
            "Provide a larger, unique block of old_text."
        )

    updated = content.replace(old_text, new_text, 1)
    target.write_text(updated, encoding="utf-8")

    return f"Successfully patched {path}"

def git_diff(workspace: Path):
    try:
        result = subprocess.run(
            ["git", "diff", "--no-ext-diff", "--no-textconv", "--", "."],
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            return (
                "ERROR:\n"
                + (result.stderr or "git diff failed")
            )

        return result.stdout if result.stdout else "(no changes)"

    except FileNotFoundError:
        return "ERROR: git is not installed or not available in PATH"

    except subprocess.TimeoutExpired:
        return "ERROR: git diff timed out"

def search_files(workspace: Path, query: str, path: str = "."):
    root = safe_path(workspace, path)

    if not root.exists():
        return f"ERROR: {path} does not exist"

    results = []

    for file in root.rglob("*"):
        if not file.is_file():
            continue

        # Skip common noisy directories
        if any(
            part in {
                ".git",
                ".venv",
                "venv",
                "node_modules",
                "__pycache__",
                ".idea",
                ".vscode",
            }
            for part in file.parts
        ):
            continue

        try:
            text = safe_path(workspace, str(file.relative_to(workspace))).read_text(encoding="utf-8")
        except Exception:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if query.lower() in line.lower():
                rel = file.relative_to(workspace)
                results.append(f"{rel}:{lineno}: {line.strip()}")

                if len(results) >= 100:
                    return "\n".join(results)

    return "\n".join(results) if results else "(no matches)"

def execute_tool(workspace: Path, name: str, arguments: str):
    args = json.loads(arguments or "{}")

    if name == "list_files":
        return list_files(workspace, args.get("path", "."))

    if name == "apply_patch":
        return apply_patch(
            workspace,
            args["path"],
            args["old_text"],
            args["new_text"],
        )

    if name == "git_diff":
        return git_diff(workspace)

    if name == "read_file":
        return read_file(workspace, args["path"])

    if name == "write_file":
        return write_file(workspace, args["path"], args["content"])

    if name == "search_files":
        return search_files(
            workspace,
            args["query"],
            args.get("path", "."),
        )

    if name == "run_command":
        raise ValueError("run_command requires a Core approval")

    return f"ERROR: unknown tool {name}"

def execute_command(workspace: Path, command: str) -> str:
    """Execute an already-approved terminal command."""

    forbidden = [
        "format ",
        "shutdown",
        "restart-computer",
        "remove-item -recurse c:\\",
        "del /s c:\\",
        "rd /s c:\\",
    ]

    lowered = command.lower()

    for pattern in forbidden:
        if pattern in lowered:
            return f"ERROR: blocked unsafe command: {command}"

    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            shell=True,
            capture_output=True,
            text=True,
            timeout=120,
        )

        output = []

        if result.stdout:
            output.append("STDOUT:\n" + result.stdout)

        if result.stderr:
            output.append("STDERR:\n" + result.stderr)

        output.append(f"EXIT_CODE: {result.returncode}")

        return "\n".join(output)

    except subprocess.TimeoutExpired:
        return "ERROR: command timed out after 120 seconds"
