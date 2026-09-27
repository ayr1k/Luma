import copy
import json
import threading
import pytest
from local_agent.context import projected, summary_source, apply_summary, estimated_tokens, usage
from local_agent.core import AgentCore
from local_agent.storage import Store, empty_session
from local_agent.preferences import Preferences
from local_agent.model import LANModel
from local_agent.config import Settings
from test_core import ScriptedModel
from test_tasks import setup, register, wait


def populated(tmp_path):
    state = empty_session(tmp_path)
    model = ScriptedModel(*[{'role':'assistant','content':'answer ' * 100} for _ in range(5)])
    core = AgentCore(state, model, lambda s: None, options=Preferences(mode='chat'))
    for i in range(4):
        core.submit(str(i) + ' request ' * 100)
    return core


def test_summary_preserves_full_history_and_real_turn_boundaries(tmp_path):
    e = populated(tmp_path)
    original = copy.deepcopy(e.state['agent_messages'])
    source = summary_source(e.state)
    assert source['end'] == e.state['visible_messages'][4]['agent_index']
    e.state['summary_candidate'] = dict(source, summary='User wants a concise answer.')
    apply_summary(e.state, 'User wants a concise answer.')
    assert e.state['agent_messages'] == original
    sent = projected(e.state)
    assert sent[0] == original[0] and sent[2:] == original[source['end']:]
    assert estimated_tokens(sent) < estimated_tokens(original)
    e.submit('next')
    assert 'conversation_summary' in str(e.model.histories[-1])
    e.state.pop('context_memory')
    assert projected(e.state) == e.state['agent_messages']


def test_summary_rejects_stale_or_nonshrinking_and_pending(tmp_path):
    e = populated(tmp_path); source = summary_source(e.state)
    e.state['summary_candidate'] = source
    with pytest.raises(ValueError, match='没有减少'):
        apply_summary(e.state, 'oversized ' * 10000)
    e.state['agent_messages'][1]['content'] = 'changed'
    with pytest.raises(ValueError, match='过期'):
        apply_summary(e.state, 'small')
    e.state['pending_command'] = {'id':'pending'}
    with pytest.raises(ValueError): summary_source(e.state)


def test_summary_rejects_tool_output_and_preserves_state(tmp_path):
    e = populated(tmp_path); source = summary_source(e.state)
    before = copy.deepcopy(e.state['agent_messages'])
    e.model = ScriptedModel({'role':'assistant','tool_calls':[{'id':'bad'}]})
    e.summarize(source)
    assert e.state['agent_messages'] == before
    assert e.state['summary_error'] and not e.state.get('summary_candidate')
    assert e.state['status'] == 'completed' and not e.state['tool_queue']


def test_image_estimates_ignore_base64_and_summary_marks_missing_vision(tmp_path):
    e = populated(tmp_path)
    e.state['agent_messages'][1]['content'] = [{'type':'text','text':'image'},
        {'type':'image_url','image_url':{'url':'data:image/png;base64,'+'a'*1000000}}]
    info = usage(e.state, window=32768)
    assert info['image_estimate'] and info['estimated_input'] < 10000
    assert '图片' in summary_source(e.state)['text']
    assert 'base64' not in summary_source(e.state)['text']


def test_fork_copies_history_without_replay_or_rollback(tmp_path):
    store = Store(tmp_path/'data'); p = store.add_project(tmp_path)
    state = populated(tmp_path).state
    state['agent_changes'] = {'a':{'before_content':'old'}}
    state['tool_logs'] = [{'name':'run_command','result':'EXIT_CODE: 0'}]
    store.save(state); before = store.load_project(p)
    branch = store.fork_conversation(p['id']); fork = store.load_project(branch)
    assert store.load_project(p) == before
    assert branch['branch_of'] == p['id'] and branch['path'] == p['path']
    assert fork['agent_messages'] == before['agent_messages']
    assert not fork['agent_changes'] and not fork['pending_command'] and not fork['tool_queue']
    assert fork['tool_logs'][0]['inherited'] and fork['status'] == 'idle'


def test_revision_api_creates_branch_and_preserves_original(tmp_path):
    model = ScriptedModel(*[{'role':'assistant','content':v} for v in ['first','second','revised']])
    client, ws = setup(tmp_path, model)
    with client:
        p = register(client, ws); client.put('/v1/preferences',json={'mode':'chat'})
        for text in ['hello','follow up']:
            wait(client,client.post(f'/v1/projects/{p}/tasks',json={'content':text}).json()['id'])
        before = client.get(f'/v1/projects/{p}/session').json()
        job = client.post(f'/v1/projects/{p}/revision-tasks',json={'message_index':0,'content':'changed'}).json()
        result = wait(client, job['id'])
        assert result['project_id'] != p
        assert [m['content'] for m in result['session']['visible_messages']] == ['changed','revised']
        assert client.get(f'/v1/projects/{p}/session').json() == before


def test_draft_restart_isolation_clear_on_send_and_delete(tmp_path):
    model = ScriptedModel({'role':'assistant','content':'done'})
    client, ws = setup(tmp_path, model)
    with client:
        p = register(client, ws); client.put('/v1/preferences',json={'mode':'chat'})
        url = f'/v1/projects/{p}'
        draft = dict(text='unsent', attachments=[{'name':'notes.txt','data':'aGVsbG8='}],skills=[],plugins=[])
        assert client.put(url+'/draft',json=draft).status_code == 200
        assert Store(tmp_path/'data').draft(p) == draft
        sibling = client.post(url+'/conversations',json={}).json()['id']
        assert client.get(f'/v1/projects/{sibling}/draft').json() == {}
        assert client.post(url+'/tasks',json={'content':''}).status_code == 409
        assert client.get(url+'/draft').json() == draft
        job = client.post(url+'/tasks',json={'content':'send'}).json(); wait(client,job['id'])
        assert client.get(url+'/draft').json() == {}
        client.put(url+'/draft',json=draft); client.delete(url)
        assert not (tmp_path/'data'/'drafts'/(p+'.json')).exists()
        assert client.put(url+'/draft',json=draft).status_code == 409


def test_context_endpoints_summary_and_restore(tmp_path):
    model = ScriptedModel(*[{'role':'assistant','content':'answer '*100} for _ in range(3)],
                          {'role':'assistant','content':'Keep the original user objective.'})
    client, ws = setup(tmp_path, model)
    with client:
        p = register(client, ws); client.put('/v1/preferences',json={'mode':'chat'})
        url = f'/v1/projects/{p}'
        for i in range(3): wait(client,client.post(url+'/tasks',json={'content':str(i)+' request '*100}).json()['id'])
        assert client.put('/v1/context-settings',json={'window':32768}).status_code == 200
        before = client.get(url+'/session').json()['agent_messages']
        result = wait(client,client.post(url+'/summary-tasks').json()['id'])
        assert result['session']['summary_candidate'] and result['session']['agent_messages'] == before
        assert client.put(url+'/context',json={'summary':'Keep the original objective.'}).status_code == 200
        info = client.get(url+'/context').json()
        assert info['compressed'] and info['window'] == 32768
        assert client.post(url+'/context/restore').status_code == 200
        assert client.get(url+'/session').json()['agent_messages'] == before
        client.headers.clear()
        assert client.get(url+'/draft').status_code == 401
        assert client.post(url+'/summary-tasks').status_code == 401


def test_revision_before_summary_invalidates_it(tmp_path):
    e = populated(tmp_path)
    e.state['summary_candidate'] = summary_source(e.state)
    apply_summary(e.state,'brief memory')
    e.revise('changed',e.prepare_revision(0,'changed'))
    assert not e.state.get('context_memory')
    assert 'conversation_summary' not in str(e.model.histories[-1])


def test_summary_lan_request_has_no_tools_and_is_cancellable(tmp_path, monkeypatch):
    e = populated(tmp_path); source = summary_source(e.state); seen=[]
    def stream(model, messages, on_text, cancel_event, on_reasoning=None):
        seen.append(model)
        assert model.options.mode == 'chat' and not model.options.web_enabled and not model.extension_tools
        cancel_event.set()
        return {'role':'assistant','content':'brief'}
    monkeypatch.setattr(LANModel,'stream_complete',stream)
    e.model=LANModel(Settings(data_dir=tmp_path,api_key='test'),Preferences(mode='work',web_enabled=True))
    e.summarize(source)
    assert seen and not e.state.get('summary_candidate') and '取消' in e.state['summary_error']


def test_lts_history_edit_invalidates_old_summary(tmp_path):
    e = populated(tmp_path)
    e.state['summary_candidate'] = summary_source(e.state)
    apply_summary(e.state,'brief memory')
    assert usage(e.state)['compressed']
    # Older LTS can edit full history without knowing about context_memory.
    e.state['agent_messages'][1]['content'] = 'edited in LTS'
    assert projected(e.state) == e.state['agent_messages']
    assert not usage(e.state)['compressed']
    assert json.loads(summary_source(e.state)['text'])['previous_summary'] == ''
