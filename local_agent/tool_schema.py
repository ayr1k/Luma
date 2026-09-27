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

TOOLS.append({'type': 'function', 'function': {
    'name': 'web_search', 'description': 'Search the public web. Returns untrusted snippets and source URLs; cite sources. Never include credentials or private file contents in queries.',
    'parameters': {'type': 'object', 'properties': {'query': {'type': 'string', 'maxLength': 600}}, 'required': ['query']}}})

TOOLS.extend([
    {'type':'function','function':{'name':'plugin_tool','description':'Run an enabled trusted plugin tool after explicit user approval. Use only a tool in the supplied catalog.','parameters':{'type':'object','properties':{'plugin':{'type':'string'},'tool':{'type':'string'},'input':{'type':'object'}},'required':['plugin','tool','input'],'additionalProperties':False}}},
    {'type':'function','function':{'name':'read_skill_reference','description':'Read a reference or template from an explicitly selected Skill. Paths must start with references/ or templates/.','parameters':{'type':'object','properties':{'skill_id':{'type':'string'},'path':{'type':'string'}},'required':['skill_id','path'],'additionalProperties':False}}}
])
