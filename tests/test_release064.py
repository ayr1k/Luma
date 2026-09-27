import copy
import json
import threading
from pathlib import Path
import pytest
from local_agent.extensions import Extensions,MAX_INSTALLED,MAX_ENABLED_CODE,MAX_SELECTED_PLUGINS
from local_agent.storage import Store,empty_session
from local_agent.core import AgentCore
from local_agent.preferences import Preferences
from local_agent.schemas import MessageCreate
from local_agent.tasks import Tasks
from local_agent.native_features import clamp_position,HOTKEYS
from local_agent.contributions import Hotkey
from test_core import ScriptedModel,call,message
from test_tasks import setup,register,wait

def test_actual_plugin_limit_boundaries(tmp_path):
    e=Extensions(tmp_path/'data');folder=tmp_path/'package';folder.mkdir()
    manifest={'id':'plugin-a','name':'Test','description':'fixture','version':'1.0.0','api_version':1,
        'runtime':'python','permissions':['local-code'],'entrypoint':'main.py',
        'tools':[{'name':'sample','description':'fixture','input_schema':{'type':'object'}}]}
    (folder/'main.py').write_text('print(1)',encoding='utf-8')
    for index in range(100):
        manifest['id']='plugin-'+str(index)
        (folder/'plugin.json').write_text(json.dumps(manifest),encoding='utf-8')
        preview=e.inspect(directory=str(folder));e.install(directory=str(folder),expected_digest=preview['digest'])
    manifest['id']='overflow';(folder/'plugin.json').write_text(json.dumps(manifest),encoding='utf-8')
    preview=e.inspect(directory=str(folder))
    with pytest.raises(ValueError,match='100'):e.install(directory=str(folder),expected_digest=preview['digest'])
    for index in range(20):e.toggle('plugin-'+str(index),True,True)
    with pytest.raises(ValueError,match='20'):e.toggle('plugin-20',True,True)
    chosen=['plugin-'+str(i) for i in range(12)]
    assert e.selected_plugins(chosen)==chosen
    with pytest.raises(ValueError,match='12'):e.selected_plugins(chosen+['plugin-12'])
    assert MessageCreate(content='test',plugins=chosen).plugins==chosen
    with pytest.raises(ValueError):MessageCreate(plugins=chosen+['plugin-12'])
    assert (MAX_INSTALLED,MAX_ENABLED_CODE,MAX_SELECTED_PLUGINS)==(100,20,12)

def test_metadata_archive_search_and_restore(tmp_path):
    c,ws=setup(tmp_path,ScriptedModel(message(call('finish',summary='needle-in-history'))))
    with c:
        pid=register(c,ws);url=f'/v1/projects/{pid}/metadata'
        assert c.put(url,json={'name':'  自定义标题  ','pinned':True}).json()['name']=='自定义标题'
        task=c.post(f'/v1/projects/{pid}/tasks',json={'content':'test'}).json();wait(c,task['id'])
        archived=c.put(url,json={'archived':True});assert archived.status_code==200 and archived.json()['pinned']
        rows=c.get('/v1/projects',params={'q':'needle-in-history'}).json()
        assert len(rows)==1 and rows[0]['archived'] and 'needle-in-history' in rows[0]['match_excerpt']
        assert c.get('/v1/projects',params={'q':'unmatched'}).json()==[]
        assert c.put(url,json={'name':'   '}).status_code==409
        assert c.put(url,json={'archived':False}).json()['archived'] is False
        assert c.get(f'/v1/projects/{pid}/session').json()['visible_messages']
        assert ws.is_dir()

def test_archive_cannot_hide_pending_approval(tmp_path):
    c,ws=setup(tmp_path,ScriptedModel(message(call('run_command',command='echo fixture'))))
    with c:
        pid=register(c,ws);task=c.post(f'/v1/projects/{pid}/tasks',json={'content':'test'}).json();wait(c,task['id'])
        assert c.put(f'/v1/projects/{pid}/metadata',json={'archived':True}).status_code==409

def test_real_progress_and_tool_results_survive_reload(tmp_path):
    ws=tmp_path/'project';ws.mkdir();store=Store(tmp_path/'data');saved=[]
    def save(state):saved.append(copy.deepcopy(state));store.save(state)
    model=ScriptedModel(message(call('write_file',path='hello.txt',content='hello')),
                        message(call('read_file',path='missing.txt')),message(call('finish',summary='done')))
    core=AgentCore(empty_session(ws),model,save);core.submit('create')
    assert {'requesting','executing','completed'} <= {s.get('progress',{}).get('stage') for s in saved}
    logs=store.load(ws)['tool_logs']
    assert logs[0]['outcome']=='succeeded' and logs[1]['outcome']=='failed'
    assert logs[0]['duration_seconds']>=0 and logs[0]['after_message']==0
    assert logs[0]['turn_id']==core.state['turn_id']
    assert (ws/'hello.txt').read_text()=='hello'

def test_revisions_keep_audit_but_do_not_reassign_old_cards(tmp_path):
    ws=tmp_path/'project';ws.mkdir();store=Store(tmp_path/'data')
    model=ScriptedModel(message(call('read_file',path='missing')),message(call('finish',summary='done')),
                        message(call('finish',summary='again')),message(call('finish',summary='third')))
    core=AgentCore(empty_session(ws),model,store.save);core.submit('test')
    core.revise('again',core.prepare_revision(0,'again'))
    core.revise('third',core.prepare_revision(0,'third'))
    assert len(core.state['tool_logs'])==4
    assert core.state['tool_logs'][0]['after_message'] is None

def test_notification_event_identifies_finished_project(tmp_path):
    ws=tmp_path/'project';ws.mkdir();store=Store(tmp_path/'data')
    core=AgentCore(empty_session(ws),ScriptedModel({'role':'assistant','content':'done'}),store.save,options=Preferences(mode='chat'))
    tasks=Tasks(threading.Lock(),lambda _:core,store);arrived=threading.Event();events=[]
    def event(value):events.append(value);arrived.set()
    tasks.on_event=event;job=tasks.start('target-project','send',MessageCreate(content='test'))
    assert arrived.wait(3)
    assert events==[dict(project_id='target-project',task_id=job['id'],status='completed')]
    tasks.shutdown()

def test_notification_navigation_and_hotkey_validation():
    from test_tray import make
    c=make();opened=[];c.navigate=opened.append;c.closing();c.completed('completed','target')
    c.show_notification();assert opened==['target'] and not c.hidden
    assert len(HOTKEYS)==18
    for key in HOTKEYS:assert Hotkey(shortcut=key).shortcut==key
    with pytest.raises(ValueError):Hotkey(shortcut='Ctrl+Alt+Delete')

def test_preparation_is_published_before_worker_and_navigation_consumed_once(tmp_path):
    from local_agent.desktop import Bridge
    ws=tmp_path/'project';ws.mkdir();store=Store(tmp_path/'data');stages=[]
    state=empty_session(ws);state.update(status='completed',progress={'stage':'completed'})
    def save(value):stages.append(value.get('progress',{}).get('stage'));store.save(value)
    core=AgentCore(state,ScriptedModel({'role':'assistant','content':'done'}),save,options=Preferences(mode='chat'))
    tasks=Tasks(threading.Lock(),lambda _:core,store)
    tasks.start('project','send',MessageCreate(content='next'));tasks.shutdown()
    assert stages[0]=='queued'
    bridge=Bridge('http://127.0.0.1:1','unused');bridge._navigation_project='test-project'
    assert bridge.request('take-navigation')['data']=='test-project'
    assert bridge.request('take-navigation')['data'] is None

@pytest.mark.parametrize('x,y,bounds,expected',[(9999,9999,(0,0,1920,1080),(1676,988)),(-1500,50,(-1920,0,0,1080),(-1500,50)),(-9999,-9999,(0,0,800,600),(0,0))])
def test_widget_position_clamped_to_available_monitor(x,y,bounds,expected):
    assert clamp_position(x,y,244,92,bounds)==expected
