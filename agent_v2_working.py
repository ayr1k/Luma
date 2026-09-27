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
            ["git", "diff", "--no-ext-diff"],
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

    print("\n" + "=" * 60)
    print("Agent wants to run:")
    print(command)
    print("=" * 60)

    approval = input("Allow command? [y/N]: ").strip().lower()

    if approval not in {"y", "yes"}:
        return "DENIED BY USER: terminal command was not executed."

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
    {
        "type": "function",
        "function": {
            "name": "apply_patch",
            "description": (
                "Make a targeted edit to an existing text file. "
                "old_text must exactly match one unique block in the file. "
                "Prefer this over write_file when modifying existing files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file"
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Exact existing text to replace"
                    },
                    "new_text": {
                        "type": "string",
                        "description": "Replacement text"
                    }
                },
                "required": ["path", "old_text", "new_text"]
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "git_diff",
            "description": (
                "Show the current Git diff for the workspace. "
                "Use this after editing files to inspect changes."
            ),
            "parameters": {
                "type": "object",
                "properties": {}
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "Finish the task only when the requested work has been completed "
                "and verified. Provide a concise final summary."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": (
                            "Final summary including files changed, verification "
                            "performed, and any unresolved issues."
                        )
                    }
                },
                "required": ["summary"]
            },
        },
    },
]


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
        return run_command(workspace, args["command"])

    return f"ERROR: unknown tool {name}"


def run_agent(workspace: Path, user_prompt: str):
    client = OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY,
    )

    system_prompt = f"""
You are a local software engineering agent with direct access to a project workspace.

Workspace:
{workspace}

Operating rules:

1. Inspect before editing.
   Read relevant files before modifying existing code.

2. Prefer targeted edits.
   Use apply_patch for existing files.
   Use write_file mainly for new files or deliberate full rewrites.

3. Verify your work.
   After important edits, inspect the Git diff when available.

4. Test whenever possible.
   Use run_command to run tests, linters, builds, or the program itself.

5. React to failures.
   If a command fails, inspect the error and fix the root cause instead of guessing.

6. Stay inside the workspace.
   Never access or modify files outside the provided workspace.

7. Do not pretend.
   Never claim that a file was modified, a test passed, or a command succeeded unless a tool result confirms it.

8. Use tools proactively.
   When the user asks you to modify or investigate a project, perform the work instead of only describing how they could do it.

9. Keep changes minimal.
   Preserve existing project structure and behavior unless the task requires otherwise.

10. Finish with a concise summary of:
    - files changed
    - important implementation decisions
    - tests or commands executed
    - unresolved issues, if any

11. Every turn must use a tool.
    Continue using tools until the requested work is complete.
    Never stop after merely describing the next action.

12. Finish explicitly.
    When and only when the task is completed and verified,
    call the finish tool with the final summary.
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

    no_tool_streak = 0

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

        if msg.content:
            print(msg.content)

        if not msg.tool_calls:
            no_tool_streak += 1

            if no_tool_streak >= 3:
                return (
                    "ERROR: Model failed to issue a tool call after 3 retries. "
                    "Task stopped to avoid an infinite loop."
                )

            # Do not preserve non-action chatter in conversation history.
            # This prevents the model from reinforcing its own "I'll do it next" loop.
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Do not describe the next action. "
                        "Perform the next action now by calling one of the available tools. "
                        "If the task is fully completed and verified, call finish."
                    ),
                }
            )
            continue

        no_tool_streak = 0
        messages.append(msg)

        for call in msg.tool_calls:
            print(f"\n[TOOL] {call.function.name}")
            print(call.function.arguments)

            if call.function.name == "finish":
                args = json.loads(call.function.arguments or "{}")
                summary = args.get("summary", "Task completed.")
                print("\n=== FINAL ===")
                print(summary)
                return summary

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