import json
import threading
import time
import httpx
import pytest
from openai import OpenAI
from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.model import LANModel
from local_agent.preferences import Preferences
from local_agent.core import AgentCore
from local_agent.storage import Store, empty_session
from local_agent.service import create_app
from local_agent.streaming import StreamCancelled

def stream_model(monkeypatch, chunks):
    requests=[]
    class Body(httpx.SyncByteStream):
        def __iter__(self):
            for delta, reason in chunks:
                yield ('data: '+json.dumps({'id':'test','object':'chat.completion.chunk','created':0,'model':'test',
                    'choices':[{'index':0,'delta':delta,'finish_reason':reason}]})+'\n\n').encode()
            yield b'data: [DONE]\n\n'
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,headers={'Content-Type':'text/event-stream'},stream=Body())
    monkeypatch.setattr(LANModel,'_client',lambda self:OpenAI(api_key='test',http_client=httpx.Client(transport=httpx.MockTransport(handler))))
    return LANModel(Settings()),requests

def test_real_sdk_stream_text_and_fragmented_tool(monkeypatch):
    model,requests=stream_model(monkeypatch,[({'content':'你好'},None),({'content':'世界'},None),
        ({'tool_calls':[{'index':0,'id':'call1','type':'function','function':{'name':'write_file','arguments':'{"path":"a.txt",'}}]},None),
        ({'tool_calls':[{'index':0,'function':{'arguments':'"content":"ok"}'}}]},'tool_calls')])
    pieces=[]
    msg=model.stream_complete([],pieces.append,threading.Event())
    assert requests[0]['stream'] is True and pieces==['你好','世界']
    assert msg['content']=='你好世界'
    assert json.loads(msg['tool_calls'][0]['function']['arguments'])=={'path':'a.txt','content':'ok'}

def test_truncated_tool_never_executes_and_partial_text_retained(tmp_path,monkeypatch):
    model,_=stream_model(monkeypatch,[({'content':'正在分析'},None),
        ({'tool_calls':[{'index':0,'id':'call1','function':{'name':'write_file','arguments':'{"path":"bad.txt","content":"bad"}'}}]},None)])
    state=empty_session(tmp_path)
    result=AgentCore(state,model,lambda s:None).submit('test')
    assert result['status']=='failed' and not (tmp_path/'bad.txt').exists()
    assert result['visible_messages'][1]['content']=='正在分析'
    assert not result['visible_messages'][1].get('streaming')
    assert not result['tool_logs']

def test_cancel_stream_closes_before_tools(tmp_path,monkeypatch):
    model,_=stream_model(monkeypatch,[({'content':'first'},None),({'content':'second'},'stop')])
    cancel=threading.Event();parts=[]
    def receive(text):parts.append(text);cancel.set()
    with pytest.raises(StreamCancelled):model.stream_complete([],receive,cancel)
    assert parts==['first']

def test_partial_snapshot_before_completion_and_delete_safety(tmp_path):
    started,release=threading.Event(),threading.Event()
    class Slow:
        def stream_complete(self,history,on_text,event):
            on_text('已经生成的第一段');started.set();assert release.wait(5)
            on_text('，以及第二段。')
            return {'role':'assistant','content':'已经生成的第一段，以及第二段。'}
    root=tmp_path/'data';project=tmp_path/'project';project.mkdir();(project/'keep.txt').write_text('keep')
    settings=Settings(data_dir=root,local_token='t'*40)
    with TestClient(create_app(settings,Slow()),base_url='http://localhost',headers={'Authorization':'Bearer '+settings.local_token}) as c:
        c.put('/v1/preferences',json={'mode':'chat'})
        p=c.post('/v1/projects',json={'path':str(project)}).json()['id']
        task=c.post(f'/v1/projects/{p}/tasks',json={'content':'hello'}).json()['id']
        try:
            assert started.wait(2)
            partial=c.get('/v1/tasks/'+task).json()
            assert partial['running'] and partial['session']['visible_messages'][-1]['content']=='已经生成的第一段'
            assert c.delete('/v1/projects/'+p).status_code==409
        finally:release.set()
        for _ in range(100):
            state=c.get('/v1/tasks/'+task).json()
            if not state['running']:break
            time.sleep(.01)
        assert state['session']['visible_messages'][-1]['content']=='已经生成的第一段，以及第二段。'
        assert len(state['session']['visible_messages'])==2
        assert c.delete('/v1/projects/'+p,headers={'Authorization':'Bearer wrong'}).status_code==401
        assert c.delete('/v1/projects/'+p).status_code==200
        assert c.get('/v1/tasks/'+task).status_code==404
        assert c.get('/v1/projects').json()==[]
        assert (project/'keep.txt').read_text()=='keep'
        assert Store(root).load(project)['visible_messages']==[]
        c.post('/v1/projects',json={'path':str(project)})
        assert c.get(f'/v1/projects/{p}/session').json()['agent_messages']==[]

def test_delete_pending_conversation_discards_approval(tmp_path):
    root=tmp_path/'data';project=tmp_path/'project';project.mkdir()
    store=Store(root);p=store.add_project(str(project));s=empty_session(project)
    s['pending_command']={'approval_id':'old','workspace':str(project),'command':'echo never','arguments':'{}','tool_call_id':'a'}
    s['status']='waiting_approval';store.save(s)
    with TestClient(create_app(Settings(data_dir=root,local_token='t'*40)),base_url='http://localhost',headers={'Authorization':'Bearer '+'t'*40}) as c:
        assert c.delete('/v1/projects/'+p['id']).status_code==200
        assert c.post(f"/v1/projects/{p['id']}/approvals",json={'approval_id':'old','allow':True}).status_code==404
        assert store.load(project)['pending_command'] is None
