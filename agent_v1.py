import os
import json
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()

BASE_URL = os.getenv("LITELLM_BASE_URL")
API_KEY = os.getenv("LITELLM_API_KEY")
MODEL = os.getenv("AGENT_MODEL", "local-agent-coder")

if not BASE_URL or not API_KEY:
    raise RuntimeError("Missing LITELLM_BASE_URL or LITELLM_API_KEY in .env")


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
            text = file.read_text(encoding="utf-8")
        except Exception:
            continue

        for lineno, line in enumerate(text.splitlines(), start=1):
            if query.lower() in line.lower():
                rel = file.relative_to(workspace)
                results.append(f"{rel}:{lineno}: {line.strip()}")

                if len(results) >= 100:
                    return "\n".join(results)

    return "\n".join(results) if results else "(no matches)"


def run_command(workspace: Path, command: str):
    # Basic safety block
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


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List files and directories inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative directory path inside the workspace"
                    }
                }
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a UTF-8 text file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path inside the workspace"
                    }
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Create or overwrite a UTF-8 text file inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path inside the workspace"
                    },
                    "content": {
                        "type": "string",
                        "description": "Complete file contents"
                    },
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_files",
            "description": "Search for text inside files in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for"
                    },
                    "path": {
                        "type": "string",
                        "description": "Relative directory path to search"
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_command",
            "description": "Run a shell command inside the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell command to execute"
                    }
                },
                "required": ["command"],
            },
        },
    },
]


def execute_tool(workspace: Path, name: str, arguments: str):
    args = json.loads(arguments or "{}")

    if name == "list_files":
        return list_files(workspace, args.get("path", "."))

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
        return run_command(workspace, args["command"])

    return f"ERROR: unknown tool {name}"


def run_agent(workspace: Path, user_prompt: str):
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
    )

    system_prompt = f"""
You are a local software engineering agent.

Workspace:
{workspace}

Rules:
- Work only inside the provided workspace.
- Inspect relevant files before modifying them.
- Use tools instead of merely describing changes.
- Prefer small, targeted changes.
- Run tests or validation when possible.
- Do not claim success unless you verified it.
- Do not modify files outside the workspace.
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt.strip(),
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    for step in range(30):
        print(f"\n--- Agent step {step + 1} ---")

        response = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0,
        )

        msg = response.choices[0].message
        messages.append(msg)

        if msg.content:
            print(msg.content)

        if not msg.tool_calls:
            return msg.content

        for call in msg.tool_calls:
            print(f"\n[TOOL] {call.function.name}")
            print(call.function.arguments)

            result = execute_tool(
                workspace,
                call.function.name,
                call.function.arguments,
            )

            print("\n[RESULT]")
            print(result[:5000])

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": result,
                }
            )

    return "Stopped after 30 agent steps."


def main():
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python agent.py <workspace>")
        sys.exit(1)

    workspace = Path(sys.argv[1]).resolve()

    if not workspace.exists():
        print(f"Workspace does not exist: {workspace}")
        sys.exit(1)

    print(f"Workspace: {workspace}")
    print(f"Model: {MODEL}")
    print("Type 'exit' to quit.\n")

    while True:
        prompt = input("You> ").strip()

        if not prompt:
            continue

        if prompt.lower() in {"exit", "quit"}:
            break

        try:
            final = run_agent(workspace, prompt)

            print("\n=== FINAL ===")
            print(final)

        except Exception as exc:
            print("\nERROR:")
            print(exc)


if __name__ == "__main__":
    main()