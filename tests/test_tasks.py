import threading
import time
from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.service import create_app
from local_agent.lease import DataLease
from test_core import call, message, ScriptedModel
import pytest

TOKEN='t'*40

def setup(tmp_path,model):
    workspace=tmp_path/'project'
    workspace.mkdir()
    client=TestClient(create_app(Settings(data_dir=tmp_path/'data',local_token=TOKEN),model),base_url='http://localhost')
    return client,workspace

def register(client,workspace):
    client.headers['Authorization']='Bearer '+TOKEN
    return client.post('/v1/projects',json={'path':str(workspace)}).json()['id']

def wait(client,task_id):
    for _ in range(200):
        response=client.get('/v1/tasks/'+task_id)
        assert response.status_code==200,response.text
        task=response.json()
        if not task['running']:
            return task
        time.sleep(.01)
    pytest.fail('task did not finish')

class SlowModel:
    def __init__(self):
        self.entered=threading.Event()
        self.release=threading.Event()
    def complete(self,history):
        if history[-1].get('content') == 'again':
            return message(call('finish', summary='continued after stop'))
        self.entered.set()
        assert self.release.wait(5)
        return message(call('write_file',path='must-not-exist.txt',content='bad'))

def test_cancel_during_model_preserves_history_without_edit(tmp_path):
    model=SlowModel()
    c,workspace=setup(tmp_path,model)
    with c:
        p=register(c,workspace)
        response=c.post(f'/v1/projects/{p}/tasks',json={'content':'test'})
        assert response.status_code==202
        task_id=response.json()['id']
        assert model.entered.wait(2)
        snapshot=c.get(f'/v1/projects/{p}/session').json()
        assert snapshot['status']=='running'
        assert c.post(f'/v1/projects/{p}/tasks',json={'content':'double'}).status_code==409
        assert c.post(f'/v1/projects/{p}/session/reset').status_code==409
        cancelled=c.post(f'/v1/tasks/{task_id}/cancel').json()
        assert cancelled['cancel_requested'] and cancelled['running']
        model.release.set()
        result=wait(c,task_id)
        assert result['session']['status']=='cancelled'
        assert not (workspace/'must-not-exist.txt').exists()
        assert result['session']['tool_queue']==[]
        assert result['session']['agent_messages'][-1]['role']=='tool'
        again=c.post(f'/v1/projects/{p}/tasks',json={'content':'again'}).json()
        assert wait(c,again['id'])['session']['status']=='completed'

def test_async_approval_cannot_be_replayed(tmp_path):
    model=ScriptedModel(message(call('run_command',command='echo progress')),
        message(call('write_file',path='done.txt',content='done')),message(call('finish',summary='done')))
    c,workspace=setup(tmp_path,model)
    with c:
        p=register(c,workspace)
        first=c.post(f'/v1/projects/{p}/tasks',json={'content':'test'}).json()
        result=wait(c,first['id'])
        pending=result['session']['pending_command']
        assert result['session']['status']=='waiting_approval'
        second=c.post(f'/v1/projects/{p}/approval-tasks',json={'approval_id':pending['approval_id'],'allow':True})
        assert second.status_code==202
        done=wait(c,second.json()['id'])
        assert done['session']['status']=='completed'
        assert (workspace/'done.txt').read_text()=='done'
        assert c.post(f'/v1/projects/{p}/approval-tasks',json={'approval_id':pending['approval_id'],'allow':True}).status_code==409

def test_stop_waits_for_command_and_skips_following_tools(tmp_path,monkeypatch):
    entered,release=threading.Event(),threading.Event()
    def command(*args):
        entered.set()
        assert release.wait(5)
        return 'EXIT_CODE: 0'
    monkeypatch.setattr('local_agent.core.execute_command',command)
    model=ScriptedModel(message(call('run_command',command='test'),call('write_file',path='skipped.txt',content='no')))
    c,workspace=setup(tmp_path,model)
    with c:
        p=register(c,workspace)
        start=c.post(f'/v1/projects/{p}/tasks',json={'content':'test'}).json()
        pending=wait(c,start['id'])['session']['pending_command']
        running=c.post(f'/v1/projects/{p}/approval-tasks',json={'approval_id':pending['approval_id'],'allow':True}).json()
        assert entered.wait(2)
        c.post('/v1/tasks/'+running['id']+'/cancel')
        release.set()
        end=wait(c,running['id'])
        assert end['session']['status']=='cancelled'
        assert not (workspace/'skipped.txt').exists()
        assert end['session']['tool_logs'][0]['result']=='EXIT_CODE: 0'

def test_service_lease_conflict_and_release(tmp_path):
    settings=Settings(data_dir=tmp_path,local_token=TOKEN)
    with TestClient(create_app(settings),base_url='http://localhost'):
        with pytest.raises(RuntimeError,match='数据目录'):
            DataLease(tmp_path).acquire()
    with DataLease(tmp_path):
        pass

def test_unknown_task_is_404(tmp_path):
    c,_=setup(tmp_path,ScriptedModel())
    with c:
        c.headers['Authorization']='Bearer '+TOKEN
        assert c.get('/v1/tasks/missing').status_code==404
        assert c.post('/v1/tasks/missing/cancel').status_code==404

def test_storage_failure_is_reported_without_executing_tools(tmp_path,monkeypatch):
    from local_agent.storage import Store
    original=Store.save
    def fail_after_start(self,state):
        if state['status']!='idle':
            raise OSError('disk full')
        return original(self,state)
    monkeypatch.setattr(Store,'save',fail_after_start)
    model=ScriptedModel(message(call('write_file',path='bad.txt',content='no')))
    c,workspace=setup(tmp_path,model)
    with c:
        p=register(c,workspace)
        start=c.post(f'/v1/projects/{p}/tasks',json={'content':'test'}).json()
        result=wait(c,start['id'])
        assert result['session']['status']=='failed'
        assert result['error']
        assert not (workspace/'bad.txt').exists()
