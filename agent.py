"""Compatibility entrypoint; all execution lives in local_agent."""
from pathlib import Path
from local_agent.tools import safe_path, list_files, read_file, write_file, apply_patch, search_files, git_diff, execute_tool
from local_agent.tool_schema import TOOLS
from local_agent.config import Settings
from local_agent.core import AgentCore
from local_agent.model import LANModel
from local_agent.storage import Store

def run_agent(workspace: Path, user_prompt: str):
    settings = Settings.load()
    from local_agent.lease import DataLease
    with DataLease(settings.data_dir):
        store = Store(settings.data_dir)
        store.add_project(str(workspace))
        core = AgentCore(store.load(workspace), LANModel(settings), store.save)
        core.submit(user_prompt)
        while core.state.get('pending_command'):
            pending = core.state['pending_command']
            print(pending['workspace'], pending['command'], sep='\n')
            core.approve(pending['approval_id'], input('Allow command? [y/N]: ').lower() in {'y', 'yes'})
        return core.state['visible_messages'][-1]['content']


if __name__ == '__main__':
    import sys
    from local_agent.__main__ import main
    sys.argv.insert(1, 'chat')
    main()
