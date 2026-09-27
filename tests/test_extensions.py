import base64,io,json,threading,zipfile
from pathlib import Path
import pytest
from local_agent.extensions import Extensions
from local_agent.plugin_worker import run_plugin
from local_agent.core import AgentCore
from local_agent.storage import Store,empty_session
from local_agent.preferences import Preferences
from test_core import ScriptedModel,call,message
from test_service import client,TOKEN

EXAMPLES=Path(__file__).resolve().parents[1]/'examples'
def zipped(files):
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for name,value in files.items():z.writestr(name,value)
    return base64.b64encode(stream.getvalue()).decode()
def install(manager,name='project-stats'):
    folder=str(EXAMPLES/name);preview=manager.inspect(directory=folder)
    manager.install(directory=folder,expected_digest=preview['digest'])
    return folder

def test_import_never_executes_and_trust_revoked_on_update(tmp_path):
    e=Extensions(tmp_path);folder=install(e)
    assert not e.list()['plugins'][0]['enabled']
    with pytest.raises(ValueError):e.prepare_tool('project-stats','count-files',{})
    with pytest.raises(ValueError):e.toggle('project-stats',True)
    e.toggle('project-stats',True,True)
    req=e.prepare_tool('project-stats','count-files',{})
    with pytest.raises(ValueError):e.prepare_tool('project-stats','count-files',{'unexpected':True})
    install(e)
    with pytest.raises(ValueError):e.execute(req,tmp_path,threading.Event())
    assert not e.list()['plugins'][0]['enabled']

@pytest.mark.parametrize('name',['../escape','/absolute','C:/drive','foo\\bar','CON.txt','foo./bar','a/../../escape'])
def test_zip_paths_rejected(tmp_path,name):
    with pytest.raises(ValueError):Extensions(tmp_path).inspect(data=zipped({name:'bad'}))
    assert not (tmp_path.parent/'escape').exists()

def test_duplicate_paths_and_symlink_and_oversized_package(tmp_path):
    e=Extensions(tmp_path)
    with pytest.raises(ValueError):e.inspect(data=zipped({'A.txt':'a','a.txt':'b'}))
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        info=zipfile.ZipInfo('link');info.external_attr=0o120777<<16;z.writestr(info,'../out')
    with pytest.raises(ValueError):e.inspect(data=base64.b64encode(data.getvalue()).decode())
    with pytest.raises(ValueError):e.inspect(data=zipped({'large':b'a'*(11*1024*1024)}))

def test_compatibility_schema_and_preview_pin(tmp_path):
    e=Extensions(tmp_path);files=e.package_files(directory=str(EXAMPLES/'project-stats'))
    m=json.loads(files['plugin.json']);m['min_luma']='0.8.0';files['plugin.json']=json.dumps(m).encode()
    with pytest.raises(ValueError):e.inspect(data=zipped(files))
    with pytest.raises(ValueError):e.install(directory=str(EXAMPLES/'project-stats'),expected_digest='wrong')
    assert not e.list()['plugins']

def test_upgrade_rollback_keeps_old_package(tmp_path,monkeypatch):
    import local_agent.extensions as module
    e=Extensions(tmp_path);folder=install(e);e.toggle('project-stats',True,True)
    old=e.state()
    def fail(*a):raise OSError('disk full')
    monkeypatch.setattr(module,'atomic_json',fail)
    with pytest.raises(OSError):install(e)
    assert e.state()==old
    assert e.list()['plugins'][0]['enabled']

def test_skill_explicit_selection_references_and_readonly(tmp_path):
    e=Extensions(tmp_path);install(e,'writing-kit');e.toggle('writing-kit',True)
    key='plugin:writing-kit:clear-writing'
    selected=e.selected([key]);assert '清晰写作'==selected[0]['name']
    assert '逐项检查' in e.reference(selected,key,'references/checklist.md')
    with pytest.raises(ValueError):e.reference([],key,'references/checklist.md')
    with pytest.raises(ValueError):e.reference(selected,key,'../plugin.json')
    with pytest.raises(ValueError):e.reference(selected,key,'scripts/main.py')
    with pytest.raises(ValueError):e.delete_skill(key)
    e.save_skill('mine','---\nname: Mine\n---\nHello')
    assert e.read_skill('user:mine')['editable']
    e.toggle('user:mine',False)
    with pytest.raises(ValueError):e.selected(['user:mine'])
    e.delete_skill('user:mine');assert not (e.skills/'mine').exists()

def test_tampered_plugin_is_disabled(tmp_path):
    e=Extensions(tmp_path);install(e);e.toggle('project-stats',True,True)
    (e.packages/'project-stats/main.py').write_text('raise Exception()',encoding='utf-8')
    row=e.list()['plugins'][0];assert row['error'] and not row['enabled']
    with pytest.raises(ValueError):e.prepare_tool('project-stats','count-files',{})

def make_core(tmp_path,mode='work'):
    e=Extensions(tmp_path/'data');install(e);e.toggle('project-stats',True,True)
    ws=tmp_path/'project';ws.mkdir();(ws/'file.txt').write_text('ok')
    store=Store(tmp_path/'data')
    model=ScriptedModel(message(call('plugin_tool',plugin='project-stats',tool='count-files',input={})),message(call('finish',summary='done')))
    return AgentCore(empty_session(ws),model,store.save,options=Preferences(mode=mode),extensions=e),store

def test_tool_requires_approval_restart_and_cannot_replay(tmp_path):
    core,store=make_core(tmp_path)
    core.submit('count',plugins=['project-stats'])
    assert core.state['status']=='waiting_approval' and not core.state['tool_logs']
    approval=core.state['pending_command']['approval_id']
    core=AgentCore(store.load(core.workspace),core.model,store.save,extensions=core.extensions)
    core.approve(approval,True)
    assert core.state['status']=='completed'
    assert json.loads(core.state['tool_logs'][0]['result'])=={'files':1,'directories':0}
    with pytest.raises(ValueError):core.approve(approval,True)

@pytest.mark.parametrize('mode',['chat','plan'])
def test_plugin_forbidden_in_readonly_modes(tmp_path,mode):
    core,_=make_core(tmp_path,mode);core.submit('count',plugins=['project-stats'])
    assert core.state['pending_command'] is None
    assert core.state['tool_logs'][0]['result'].startswith('ERROR:')

def test_deny_does_not_execute(tmp_path,monkeypatch):
    core,_=make_core(tmp_path);core.submit('count',plugins=['project-stats'])
    def fail(*a):pytest.fail('execution without approval')
    monkeypatch.setattr(core.extensions,'execute',fail)
    core.approve(core.state['pending_command']['approval_id'],False)
    assert core.state['tool_logs'][0]['result'].startswith('DENIED')

def test_selected_skill_scope_and_revision_snapshot(tmp_path):
    e=Extensions(tmp_path/'data');e.save_skill('one','Use short sentences.');e.save_skill('two','Not selected')
    store=Store(tmp_path/'data');ws=tmp_path/'project';ws.mkdir()
    model=ScriptedModel(*[{'role':'assistant','content':'done'}]*3)
    core=AgentCore(empty_session(ws),model,store.save,options=Preferences(mode='chat'),extensions=e)
    core.submit('hello',skills=e.selected(['user:one']))
    assert 'Use short sentences.' in model.histories[0][0]['content']
    assert 'Not selected' not in model.histories[0][0]['content']
    e.save_skill('one','Changed')
    rev=core.prepare_revision(0,'again');core.revise('again',rev)
    assert 'Use short sentences.' in model.histories[1][0]['content']
    core.submit('plain')
    assert 'Use short sentences.' not in model.histories[2][0]['content']
    assert core.state['active_skills']==[]

def test_worker_invalid_output_timeout_cancel_and_no_key_env(tmp_path,monkeypatch):
    entry=tmp_path/'main.py';args=(entry,{'tool':'test','input':{}},tmp_path,tmp_path,threading.Event())
    monkeypatch.setenv('OPENAI_API_KEY','must-not-inherit')
    entry.write_text("import os,json; print(json.dumps({'text':str('OPENAI_API_KEY' in os.environ)}))",encoding='utf-8')
    assert run_plugin(*args)=='False'
    entry.write_text("print('bad output')",encoding='utf-8')
    with pytest.raises(ValueError,match='JSON'):run_plugin(*args)
    entry.write_text('import time; time.sleep(10)',encoding='utf-8')
    with pytest.raises(ValueError,match='超时'):run_plugin(*args,timeout=.15)
    args[-1].set()
    with pytest.raises(ValueError,match='取消'):run_plugin(*args)

def test_api_auth_install_skills_and_pending_lock(tmp_path):
    model=ScriptedModel(message(call('plugin_tool',plugin='project-stats',tool='count-files',input={})))
    with client(tmp_path,model) as c:
        assert c.get('/v1/extensions').status_code==401
        c.headers['Authorization']='Bearer '+TOKEN
        endpoint='/v1/extensions';directory=str(EXAMPLES/'project-stats')
        preview=c.post(endpoint,json={'action':'inspect','directory':directory}).json()
        assert c.post(endpoint,json={'action':'install','directory':directory,'digest':preview['digest']}).status_code==200
        assert c.post(endpoint,json={'action':'toggle','id':'project-stats','enabled':True}).status_code==409
        assert c.post(endpoint,json={'action':'toggle','id':'project-stats','enabled':True,'trusted':True}).status_code==200
        p=c.post('/v1/projects',json={'path':str(tmp_path)}).json()['id']
        response=c.post('/v1/projects/'+p+'/messages',json={'content':'count','plugins':['project-stats'],'skills':['plugin:project-stats:project-overview']})
        assert response.status_code==200,response.text
        state=response.json();assert state['pending_command']['kind']=='plugin'
        assert len(state['active_skills'])==1
        assert c.post(endpoint,json={'action':'uninstall','id':'project-stats'}).status_code==409
