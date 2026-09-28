import json,shutil
from pathlib import Path
import pytest
import local_agent.extensions as module
from local_agent.extensions import Extensions
from local_agent.storage import atomic_json
from local_agent.updates import Updates,select_releases
from local_agent.upgrade import audit
from local_agent.git_manager import GitManager

ROOT=Path(__file__).resolve().parents[1]

def package(tmp_path,version='1.1.0',maximum='0.7.99'):
    p=tmp_path/version;shutil.copytree(ROOT/'preset_plugins/luma-palette',p)
    m=json.loads((p/'plugin.json').read_text(encoding='utf-8'));m.update(version=version,max_luma=maximum)
    (p/'plugin.json').write_text(json.dumps(m),encoding='utf-8');return p

def put(e,p,origin='bundled'):
    v=e.inspect(directory=str(p));return e.install(directory=str(p),expected_digest=v['digest'],origin=origin)

def test_incompatible_old_bundle_updates_without_deleting_data(tmp_path,monkeypatch):
    e=Extensions(tmp_path/'data');old=package(tmp_path)
    monkeypatch.setattr(module,'VERSION',(0,7,3));put(e,old)
    e.configure('luma-palette',{'palette':'midnight','accent':'#aabbcc'})
    saved=e.state()['plugins']['luma-palette']['config']
    (e.base/'data/luma-palette').mkdir();(e.base/'data/luma-palette/user.txt').write_text('keep')
    atomic_json(e.base/'bundled-receipts.json',{'luma-palette':e.state()['plugins']['luma-palette']['digest']})
    monkeypatch.setattr(module,'VERSION',(0,8,0));assert e.list()['plugins'][0]['error']
    e.sync_bundled(ROOT/'preset_plugins');row=e.state()['plugins']['luma-palette']
    assert row['manifest']['version']=='1.2.0' and row['config']==saved
    assert not row['enabled'] and not e.list()['errors']
    assert (e.base/'data/luma-palette/user.txt').read_text()=='keep'
    assert row['history'] and (e.base/'trash'/row['history'][-1]['directory']).exists()
    with pytest.raises(ValueError,match='不兼容'):e.rollback('luma-palette')

def test_legacy_origin_adoption_registry_refresh_and_local_modification(tmp_path,monkeypatch):
    e=Extensions(tmp_path/'data');old=package(tmp_path,'1.1.0','0.8.99');put(e,old,origin='local')
    key='luma-palette';digest=e.state()['plugins'][key]['digest']
    monkeypatch.setitem(module.PLUGIN_DIGESTS,key,[digest])
    e.sync_bundled(ROOT/'preset_plugins');assert e.state()['plugins'][key]['origin']=='bundled'
    state=e.state();state['plugins'][key]['manifest']['tested_luma']='stale';atomic_json(e.registry,state)
    e.sync_bundled(ROOT/'preset_plugins');assert e.details(key)['tested_luma']=='0.8.0'
    (e.packages/key/'user.txt').write_text('custom')
    e.sync_bundled(ROOT/'preset_plugins');assert (e.packages/key/'user.txt').read_text()=='custom'
    assert e.bundle_errors

def test_bundle_user_uninstall_and_rollback_are_respected(tmp_path):
    e=Extensions(tmp_path/'data');old=package(tmp_path,'1.1.0','0.8.99');put(e,old)
    e.sync_bundled(ROOT/'preset_plugins');e.rollback('luma-palette')
    e.sync_bundled(ROOT/'preset_plugins');assert e.details('luma-palette')['version']=='1.1.0'
    assert not e.state()['plugins']['luma-palette']['enabled']
    e.uninstall('luma-palette');e.sync_bundled(ROOT/'preset_plugins');assert 'luma-palette' not in e.state()['plugins']

def test_local_unknown_replacement_not_overwritten(tmp_path):
    e=Extensions(tmp_path/'data');p=package(tmp_path,'4.0.0','0.8.99');put(e,p,origin='local')
    e.sync_bundled(ROOT/'preset_plugins');assert e.details('luma-palette')['version']=='4.0.0'

def test_release_selection_semver_and_channels():
    rows=[{'tag_name':t} for t in ['legacy','v0.7.8','v0.10.0','v0.9.0','v0.7.2LTS','v0.7.2-lts-r2']]
    rows +=[{'tag_name':'v1.0.0','prerelease':True},{'tag_name':'v2.0.0','draft':True}]
    r=select_releases(rows)
    assert r['Latest']['version']=='0.10.0' and r['LTS']['revision']==2
    assert r['LTS']['url'].startswith('https://github.com/ayr1k/Luma/releases/tag/')

def test_update_failure_keeps_previous_result_and_settings(tmp_path,monkeypatch):
    u=Updates(tmp_path);u.configure(False,'LTS');u.state['channels']={'Latest':{'version':'0.8.0'}}
    class BadClient:
        def __init__(self,**kw):raise OSError('network')
    monkeypatch.setattr('local_agent.updates.httpx.Client',BadClient);u._fetch()
    r=u.snapshot();assert r['error'] and r['channels']['Latest']['version']=='0.8.0'
    assert not u.check()['checking'] and Updates(tmp_path).snapshot()['channel']=='LTS'

def test_upgrade_audit_preserves_broken_sessions_and_settings(tmp_path):
    (tmp_path/'sessions').mkdir();(tmp_path/'sessions/bad.json').write_text('{broken')
    atomic_json(tmp_path/'preferences.json',{'theme':'light'})
    r=audit(tmp_path);assert r['issues'] and (Path(r['backup'])/'preferences.json').exists()
    assert (tmp_path/'sessions/bad.json').read_text()=='{broken'
    assert audit(tmp_path)==r

def test_git_clone_adds_new_directory_without_overwriting(tmp_path):
    g=GitManager(tmp_path/'data');source=tmp_path/'source';source.mkdir()
    g.run(source,'init','-b','main');g.run(source,'config','user.name','Test');g.run(source,'config','user.email','test@example.invalid')
    (source/'file.txt').write_text('hello');g.run(source,'add','.');g.run(source,'commit','-m','initial')
    path=g.clone(str(source),str(tmp_path),'copy');assert (Path(path)/'file.txt').read_text()=='hello'
    assert g.operations()[0]['action']=='clone'
    with pytest.raises(ValueError,match='已经存在'):g.clone(str(source),str(tmp_path),'copy')
    for name in ['../escape','CON','bad.']:
        with pytest.raises(ValueError):g.clone(str(source),str(tmp_path),name)
    with pytest.raises(ValueError):g.clone('https://token@example.com/repo',str(tmp_path),'other')

def test_configuration_mismatch_does_not_swap_package(tmp_path):
    e=Extensions(tmp_path/'data');p=package(tmp_path,'1.1.0','0.8.99');put(e,p)
    original=(e.packages/'luma-palette/plugin.json').read_bytes()
    state=e.state();state['plugins']['luma-palette']['config']['future-field']=True;atomic_json(e.registry,state)
    with pytest.raises(ValueError,match='配置'):put(e,ROOT/'preset_plugins/luma-palette')
    assert e.state()==state and (e.packages/'luma-palette/plugin.json').read_bytes()==original

def test_update_success_and_api_options(tmp_path,monkeypatch):
    from test_service import client,TOKEN
    from test_core import ScriptedModel
    import httpx
    real=httpx.Client
    transport=httpx.MockTransport(lambda req:httpx.Response(200,json=[{'tag_name':'v0.8.1'},{'tag_name':'v0.7.2-lts'}]))
    monkeypatch.setattr('local_agent.updates.httpx.Client',lambda **kw:real(transport=transport,**kw))
    u=Updates(tmp_path/'checker');u._fetch();assert u.snapshot()['channels']['Latest']['version']=='0.8.1'
    with client(tmp_path,ScriptedModel()) as c:
        assert c.get('/v1/updates').status_code==401
        c.headers['Authorization']='Bearer '+TOKEN
        assert c.put('/v1/updates',json={'automatic':False,'channel':'LTS'}).json()['channel']=='LTS'
        assert c.get('/v1/updates').json()['codename']=='SoHo'
        assert c.get('/v1/upgrade-report').json()['version']=='0.8.0'
        assert c.get('/v1/git/operations').json()==[]
        assert c.post('/v1/git/clone',json={'url':'https://token@example.com/r','parent':str(tmp_path),'name':'new'}).status_code==409
        assert not (tmp_path/'new').exists()
