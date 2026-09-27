import json
import sys
import pytest
from local_agent.core import AgentCore
from local_agent.storage import Store, empty_session
from local_agent.tools import safe_path, search_files, execute_tool

def call(name, **args):
    return {'id': name + str(len(str(args))), 'type': 'function',
            'function': {'name': name, 'arguments': json.dumps(args)}}

def message(*calls):
    return {'role': 'assistant', 'content': None, 'tool_calls': list(calls)}

class ScriptedModel:
    def __init__(self, *messages):
        self.messages = iter(messages)
        self.histories = []

    def complete(self, history):
        self.histories.append(json.loads(json.dumps(history)))
        return next(self.messages)

def engine(tmp_path, *messages):
    workspace = tmp_path / 'project'
    workspace.mkdir()
    store = Store(tmp_path / 'data')
    return AgentCore(empty_session(workspace), ScriptedModel(*messages), store.save), store

def test_approval_restart_queue_and_replay(tmp_path):
    core, store = engine(tmp_path,
        message(call('run_command', command='echo approved'), call('write_file', path='after.txt', content='ok')),
        message(call('finish', summary='done')))
    core.submit('do it')
    assert core.state['status'] == 'waiting_approval'
    assert not (core.workspace / 'after.txt').exists()
    approval_id = core.state['pending_command']['approval_id']
    core = AgentCore(store.load(core.workspace), core.model, store.save)
    core.approve(approval_id, True)
    assert core.state['status'] == 'completed'
    assert (core.workspace / 'after.txt').read_text() == 'ok'
    assert 'EXIT_CODE: 0' in core.state['tool_logs'][0]['result']
    with pytest.raises(ValueError):
        core.approve(approval_id, True)
    # Every assistant call, including finish, has a matching result.
    calls = [c['id'] for m in core.state['agent_messages'] for c in m.get('tool_calls', [])]
    results = [m['tool_call_id'] for m in core.state['agent_messages'] if m['role'] == 'tool']
    assert calls == results

def test_denial_never_executes(tmp_path, monkeypatch):
    core, _ = engine(tmp_path, message(call('run_command', command='echo nope')), message(call('finish', summary='denied')))
    monkeypatch.setattr('local_agent.core.execute_command', lambda *a: pytest.fail('must not execute'))
    core.submit('test')
    with pytest.raises(ValueError):
        core.approve('wrong', True)
    core.approve(core.state['pending_command']['approval_id'], False)
    assert core.state['tool_logs'][0]['result'].startswith('DENIED')

def test_exact_rollback_and_manual_edit_guard(tmp_path):
    core, _ = engine(tmp_path, message(call('apply_patch', path='a.txt', old_text='old', new_text='new')),
                     message(call('finish', summary='done')))
    target = core.workspace / 'a.txt'
    target.write_bytes(b'old\r\nsecond\r\n')
    core.submit('edit')
    assert core.state['agent_changes']
    target.write_text('manual', encoding='utf-8')
    assert core.revert()['skipped'] == ['a.txt']
    assert target.read_text() == 'manual'
    target.write_bytes(b'new\r\nsecond\r\n')
    assert core.revert()['reverted'] == ['a.txt']
    assert target.read_bytes() == b'old\r\nsecond\r\n'

def test_failed_patch_not_tracked(tmp_path):
    core, _ = engine(tmp_path, message(call('apply_patch', path='a', old_text='missing', new_text='new')),
                     message(call('finish', summary='done')))
    (core.workspace / 'a').write_text('actual')
    core.submit('edit')
    assert core.state['agent_changes'] == {}

def test_path_escape_and_terminal_bypass(tmp_path):
    with pytest.raises(ValueError):
        safe_path(tmp_path, '../secret')
    with pytest.raises(ValueError):
        execute_tool(tmp_path, 'run_command', '{"command":"echo unsafe"}')

def test_search_symlink_escape(tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside.txt'
    outside.write_text('SECRET')
    try:
        (workspace / 'link.txt').symlink_to(outside)
    except OSError:
        pytest.skip('Symlinks require Windows developer mode/privilege')
    assert search_files(workspace, 'SECRET') == '(no matches)'

def test_step_limit_includes_approval_continuations(tmp_path):
    core, _ = engine(tmp_path, message(call('run_command', command='echo x')))
    core.max_steps = 1
    core.submit('test')
    core.approve(core.state['pending_command']['approval_id'], False)
    assert core.state['status'] == 'paused'
    assert core.state['pause_reason'] == 'step_limit'
    assert core.state['steps'] == 1

def test_malformed_arguments_are_tool_result(tmp_path):
    bad = call('write_file')
    bad['function']['arguments'] = '{invalid'
    core, _ = engine(tmp_path, message(bad), message(call('finish', summary='done')))
    core.submit('test')
    assert core.state['tool_logs'][0]['result'].startswith('ERROR:')

def test_legacy_session_and_projects(tmp_path):
    store = Store(tmp_path / 'data')
    project = store.add_project(str(tmp_path))
    assert store.add_project(str(tmp_path))['id'] == project['id']
    legacy = empty_session(tmp_path)
    for key in ['tool_queue', 'status', 'steps', 'no_tool_streak']:
        legacy.pop(key)
    store.save(legacy)
    assert store.load(tmp_path)['status'] == 'idle'
    assert len(store.projects()) == 1

def test_crash_consumes_approval(tmp_path, monkeypatch):
    core, store = engine(tmp_path, message(call('run_command', command='echo x')))
    core.submit('test')
    def crash(*a):
        raise KeyboardInterrupt()
    monkeypatch.setattr('local_agent.core.execute_command', crash)
    with pytest.raises(KeyboardInterrupt):
        core.approve(core.state['pending_command']['approval_id'], True)
    saved = store.load(core.workspace)
    assert saved['pending_command'] is None
    assert saved['status'] == 'interrupted'

def test_legacy_finish_history_is_repaired_without_execution(tmp_path):
    store = Store(tmp_path / 'data')
    state = empty_session(tmp_path)
    state.pop('status')
    state['agent_messages'] = [message(call('finish', summary='legacy done'))]
    store.save(state)
    migrated = store.load(tmp_path)
    assert migrated['agent_messages'][-1]['role'] == 'tool'
    assert migrated['agent_messages'][-1]['content'] == 'legacy done'
