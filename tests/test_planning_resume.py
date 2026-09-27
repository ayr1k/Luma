import threading,time
from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.service import create_app
from local_agent.core import AgentCore
from local_agent.preferences import Preferences
from local_agent.storage import empty_session,Store
from test_core import ScriptedModel,call,message
from test_stream_delete import stream_model

def text(value='planning'):
    return {'role':'assistant','content':value}

def make(tmp_path,*messages,**options):
    return AgentCore(empty_session(tmp_path),ScriptedModel(*messages),lambda s:None,options=Preferences(**options))

def test_four_planning_responses_can_execute(tmp_path):
    e=make(tmp_path,*[text() for _ in range(4)],message(call('write_file',path='x.txt',content='done')),message(call('finish',summary='done')))
    e.submit('create file')
    assert e.state['status']=='completed' and (tmp_path/'x.txt').read_text()=='done'
    assert len(e.state['tool_logs'])==2
    assert sum('If your plan is sufficient' in str(m) for m in e.state['agent_messages'])==1

def test_six_replies_pause_then_resume_without_replay(tmp_path):
    e=make(tmp_path,*[text() for _ in range(6)],message(call('write_file',path='x.txt',content='once')),text('Created the file.'))
    e.submit('create')
    assert e.state['status']=='paused' and e.state['no_tool_streak']==6
    e.resume()
    assert e.state['status']=='completed'
    assert sum(l['name']=='write_file' for l in e.state['tool_logs'])==1


def test_question_waits_and_supplement_keeps_history(tmp_path):
    e=make(tmp_path,text('[NEED_INPUT] 请提供文件名称？'),message(call('finish',summary='done')))
    e.submit('create');assert e.state['pause_reason']=='input'
    e.submit('a.py');assert e.state['status']=='completed'
    assert any(m['content']=='create' for m in e.state['agent_messages'])

def test_custom_limit_and_stop(tmp_path):
    e=make(tmp_path,*[text() for _ in range(3)],no_tool_limit=3)
    e.submit('test');assert e.state['status']=='paused'
    e.cancel();assert e.state['status']=='cancelled'

def test_total_budget_requires_explicit_resume(tmp_path):
    e=make(tmp_path,text(),message(call('finish',summary='done')),max_steps=1)
    e.submit('test');assert e.state['pause_reason']=='step_limit'
    e.resume();assert e.state['status']=='completed'

def test_reasoning_stream_display_preserve_and_parameter(tmp_path,monkeypatch):
    model,requests=stream_model(monkeypatch,[({'reasoning_content':'analysis'},None),({'content':'answer'},'stop')])
    model.options=Preferences(mode='chat',reasoning_effort='high')
    e=AgentCore(empty_session(tmp_path),model,lambda s:None,options=model.options)
    e.submit('test')
    assert e.state['visible_messages'][1]['reasoning']=='analysis'
    assert e.state['visible_messages'][1]['content']=='answer'
    assert e.state['agent_messages'][-1]['reasoning_content']=='analysis'
    assert requests[0]['reasoning_effort']=='high'

def test_default_reasoning_omits_parameter(monkeypatch):
    model,requests=stream_model(monkeypatch,[({'content':'answer'},'stop')])
    model.stream_complete([],lambda _:None,threading.Event())
    assert 'reasoning_effort' not in requests[0]

def test_resume_api_persisted_pause_auth_and_stale(tmp_path):
    project=tmp_path/'p';project.mkdir();store=Store(tmp_path/'data');row=store.add_project(str(project))
    state=empty_session(project);state.update(status='paused',pause_reason='no_tool');store.save(state)
    settings=Settings(data_dir=tmp_path/'data',local_token='t'*40)
    with TestClient(create_app(settings,ScriptedModel(message(call('finish',summary='done')))),base_url='http://localhost',headers={'Authorization':'Bearer '+'t'*40}) as client:
        url='/v1/projects/'+row['id']+'/continue'
        assert client.post(url,headers={'Authorization':'Bearer wrong'}).status_code==401
        res=client.post(url);assert res.status_code==202
        for _ in range(100):
            job=client.get('/v1/tasks/'+res.json()['id']).json()
            if not job['running']:break
            time.sleep(.01)
        assert job['session']['status']=='completed'
        assert client.post(url).status_code in {400,409}
