import json
import pytest
from fastapi.testclient import TestClient
from local_agent.core import AgentCore
from local_agent.config import Settings
from local_agent.service import create_app
from local_agent.preferences import Preferences, load_preferences
from local_agent.storage import empty_session, Store
from local_agent.search import web_search
from test_core import ScriptedModel, message, call

@pytest.mark.parametrize('mode', ['chat','plan'])
def test_readonly_modes_reject_unadvertised_mutations(tmp_path, mode, monkeypatch):
    executed=[]
    monkeypatch.setattr('local_agent.core.execute_command', lambda *a: executed.append(a))
    state=empty_session(tmp_path)
    model=ScriptedModel(*[message(call('write_file',path='no.txt',content='bad'),
                                call('apply_patch',path='no.txt',patch='bad'),
                                call('run_command',command='echo bad')),
                         {'role':'assistant','content':'Here is the plan.'}])
    engine=AgentCore(state,model,lambda state:None,options=Preferences(mode=mode))
    result=engine.submit('test')
    assert result['status']=='completed'
    assert not (tmp_path/'no.txt').exists() and not executed
    assert result['pending_command'] is None
    assert all('not allowed' in t['result'] for t in result['tool_logs'])

def test_chat_blocks_reads_but_plan_can_read(tmp_path):
    (tmp_path/'hello.txt').write_text('local-only')
    for mode in ['chat','plan']:
        model=ScriptedModel(*[message(call('read_file',path='hello.txt')),{'role':'assistant','content':'done'}])
        engine=AgentCore(empty_session(tmp_path),model,lambda s:None,options=Preferences(mode=mode))
        result=engine.submit('read')
        log=result['tool_logs'][0]['result']
        assert ('not allowed' in log) if mode=='chat' else ('local-only' in log)

def test_search_opt_in_and_sources(tmp_path,monkeypatch):
    calls=[]
    def search(q,n):
        calls.append((q,n));return json.dumps({'results':[{'title':'Python','url':'https://python.org','snippet':'Documentation'}]})
    monkeypatch.setattr('local_agent.core.web_search', search)
    for enabled in [False,True]:
        model=ScriptedModel(*[message(call('web_search',query='python docs')),{'role':'assistant','content':'done'}])
        engine=AgentCore(empty_session(tmp_path),model,lambda s:None,options=Preferences(mode='chat',web_enabled=enabled,search_results=3))
        result=engine.submit('search')
        assert result['status']=='completed'
    assert calls==[('python docs',3)]

def test_search_normalizes_and_rejects_unsafe_urls(monkeypatch):
    class Search:
        def __init__(self,**kwargs):assert kwargs['timeout']==12
        def text(self,q,**kwargs):
            assert kwargs['backend']=='duckduckgo'
            return [{'title':'Python','href':'https://python.org','body':'docs'},
                    {'title':'bad','href':'javascript:alert(1)','body':'evil'}]
    monkeypatch.setattr('ddgs.DDGS',Search)
    data=json.loads(web_search('python',5))
    assert len(data['results'])==1 and data['results'][0]['url']=='https://python.org'
    assert web_search('x'*601).startswith('ERROR')

def test_preferences_persist_and_reject_invalid_values(tmp_path):
    settings=Settings(data_dir=tmp_path,local_token='t'*40)
    with TestClient(create_app(settings),base_url='http://localhost',headers={'Authorization':'Bearer '+settings.local_token}) as c:
        assert c.get('/v1/preferences').json()['mode']=='work'
        assert c.put('/v1/preferences',json={'mode':'plan','temperature':.4,'font_size':16}).status_code==200
        assert load_preferences(tmp_path).mode=='plan'
        for bad in [{'mode':'admin'},{'temperature':3},{'max_steps':0},{'timeout':1000},{'max_tokens':1}]:
            assert c.put('/v1/preferences',json=bad).status_code==422
        assert c.get('/v1/preferences').json()['temperature']==.4
        assert c.get('/v1/preferences',headers={'Authorization':'Bearer bad'}).status_code==401

def test_pending_options_survive_restart(tmp_path):
    workspace=tmp_path/'project';workspace.mkdir()
    settings=Settings(data_dir=tmp_path/'data',local_token='t'*40)
    store=Store(settings.data_dir);p=store.add_project(str(workspace))
    original=AgentCore(store.load(workspace),ScriptedModel(*[message(call('run_command',command='echo ok'))]),store.save,
                       options=Preferences(mode='work',temperature=.3))
    original.submit('test')
    # Simulate a preference file changed while service was stopped.
    from local_agent.preferences import save_preferences
    save_preferences(settings.data_dir,Preferences(mode='chat'))
    model=ScriptedModel(*[message(call('finish',summary='done'))])
    with TestClient(create_app(settings,model),base_url='http://localhost',headers={'Authorization':'Bearer '+settings.local_token}) as c:
        assert c.put('/v1/preferences',json={'mode':'plan'}).status_code==409
        pending=store.load(workspace)['pending_command']
        result=c.post(f"/v1/projects/{p['id']}/approvals",json={'approval_id':pending['approval_id'],'allow':False})
        assert result.status_code==200 and result.json()['status']=='completed'

def test_request_parameters_and_chat_tool_omission(tmp_path,monkeypatch):
    from local_agent.model import LANModel
    from openai import OpenAI
    import httpx
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'id':'test','object':'chat.completion','created':0,'model':'m','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'ok'}}]})
    monkeypatch.setattr(LANModel,'_client',lambda s:OpenAI(api_key='test',http_client=httpx.Client(transport=httpx.MockTransport(respond))))
    for mode in ['chat','plan','work']:
        LANModel(Settings(),Preferences(mode=mode,temperature=.7,top_p=.9,max_tokens=1024)).complete([{'role':'user','content':'hi'}])
        request=requests[-1]
        assert request['temperature']==.7 and request['top_p']==.9 and request['max_tokens']==1024
        names={t['function']['name'] for t in request.get('tools',[])}
        if mode=='chat':assert 'tools' not in request
        if mode=='plan':assert 'read_file' in names and not names & {'write_file','run_command','apply_patch'}
        if mode=='work':assert 'run_command' in names

def test_standalone_chat_names_and_keeps_session(tmp_path):
    import time
    settings=Settings(data_dir=tmp_path,local_token='t'*40)
    model=ScriptedModel({'role':'assistant','content':'hello'})
    with TestClient(create_app(settings,model),base_url='http://localhost',headers={'Authorization':'Bearer '+settings.local_token}) as c:
        c.put('/v1/preferences',json={'mode':'chat'})
        project=c.post('/v1/chat').json()
        task=c.post(f"/v1/projects/{project['id']}/tasks",json={'content':'讨论一个新想法'}).json()
        for _ in range(100):
            state=c.get('/v1/tasks/'+task['id']).json()
            if not state['running']:break
            time.sleep(.01)
        assert state['session']['status']=='completed'
        assert c.get('/v1/projects').json()[0]['name']=='讨论一个新想法'
        assert Store(tmp_path).load(project['path'])['visible_messages'][-1]['content']=='hello'

