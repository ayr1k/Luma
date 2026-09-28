import subprocess
from pathlib import Path
import pytest
from local_agent.git_manager import GitManager
from local_agent.schemas import GitAction
from test_service import client,TOKEN
from test_core import ScriptedModel

@pytest.fixture
def repo(tmp_path,monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_GLOBAL',str(tmp_path/'empty-global'))
    monkeypatch.setenv('GIT_CONFIG_SYSTEM',str(tmp_path/'empty-system'))
    root=tmp_path/'project';root.mkdir();manager=GitManager(tmp_path/'settings')
    if not manager.executable():pytest.skip('Git unavailable')
    return manager,root

def act(m,p,action,**kw):
    state=m.status(p)
    return m.action(p,GitAction(action=action,root=state.get('root',''),token=state.get('token',''),**kw))

def init(m,p):
    act(m,p,'init',branch='main')
    act(m,p,'identity',name='Luma Test',email='test@example.invalid')

def test_onboarding_missing_and_existing_ignore(repo,monkeypatch):
    m,p=repo
    assert m.status(p)['state']=='uninitialized'
    (p/'.gitignore').write_text('keep-me\n')
    act(m,p,'init',ignore=True,branch='main')
    assert (p/'.gitignore').read_text()=='keep-me\n'
    assert m.status(p)['identity']=={'name':'','email':''}
    monkeypatch.setattr(m,'executable',lambda:None)
    assert m.status(p)['state']=='missing'

def test_full_flow_unicode_space_delete_history(repo):
    m,p=repo;init(m,p)
    name='中文 文件.txt';(p/name).write_text('first\n',encoding='utf-8')
    assert 'first' in m.detail(p,name)['after']
    act(m,p,'stage',paths=[name]);assert m.status(p)['files'][0]['staged']
    act(m,p,'unstage',paths=[name]);assert (p/name).exists()
    act(m,p,'stage',paths=[name]);act(m,p,'commit',message='Initial')
    history=m.history(p)['commits'];assert history[0]['title']=='Initial'
    assert m.history(p,history[0]['id'])['files']==[name]
    assert m.detail(p,name,'history',history[0]['id'])['after'].replace('\r\n','\n')=='first\n'
    (p/name).write_text('second\n',encoding='utf-8');act(m,p,'stage',paths=[name])
    (p/name).write_text('third\n',encoding='utf-8')
    assert m.detail(p,name,'index')['after'].replace('\r\n','\n')=='second\n'
    assert m.detail(p,name)['before'].replace('\r\n','\n')=='second\n'
    act(m,p,'commit',message='Only staged')
    assert (p/name).read_text(encoding='utf-8')=='third\n'
    assert m.detail(p,name)['before'].replace('\r\n','\n')=='second\n'
    (p/name).unlink();act(m,p,'stage',paths=[name]);act(m,p,'commit',message='Delete')
    assert not m.status(p)['files']

def test_rename_unstage_preserves_files(repo):
    m,p=repo;init(m,p);(p/'before.txt').write_text('content\n');act(m,p,'stage',paths=['before.txt']);act(m,p,'commit',message='initial')
    (p/'before.txt').rename(p/'after.txt');act(m,p,'stage',paths=['before.txt','after.txt'])
    row=m.status(p)['files'][0];assert row['old_path']=='before.txt'
    act(m,p,'unstage',paths=['after.txt']);assert (p/'after.txt').read_text()=='content\n'

def test_branch_and_dirty_protection(repo):
    m,p=repo;init(m,p);(p/'a').write_text('a');act(m,p,'stage',paths=['a']);act(m,p,'commit',message='initial')
    act(m,p,'branch',branch='feature/test');assert m.status(p)['branch']=='feature/test'
    act(m,p,'switch',branch='main');(p/'a').write_text('dirty')
    with pytest.raises(ValueError,match='未提交'):act(m,p,'switch',branch='feature/test')
    assert (p/'a').read_text()=='dirty'

def test_stale_index_and_literal_pathspec(repo):
    m,p=repo;init(m,p)
    (p/'[ab].txt').write_text('literal');(p/'a.txt').write_text('other')
    state=m.status(p);act(m,p,'stage',paths=['[ab].txt'])
    assert [r['path'] for r in m.status(p)['files'] if r['staged']]==['[ab].txt']
    with pytest.raises(ValueError,match='状态已变化'):
        m.action(p,GitAction(action='commit',root=state['root'],token=state['token'],message='stale'))
    with pytest.raises(ValueError):act(m,p,'stage',paths=['../outside'])

def test_parent_repo_identity_scope_and_binary(repo):
    m,p=repo;init(m,p);sub=p/'child';sub.mkdir()
    assert m.status(sub)['root']==str(p.resolve())
    assert m.status(sub)['parent_repository']
    assert m.text(p,'config','--global','user.name',allow=True)==''
    (p/'binary').write_bytes(b'abc\0xyz');assert m.detail(p,'binary')['binary']
    act(m,p,'stage',paths=['binary']);patch,_=m.staged_prompt(p,m.status(p)['token']);assert 'Binary' in patch

def test_conflict_and_missing_identity(repo):
    m,p=repo;act(m,p,'init',branch='main');(p/'a').write_text('a');act(m,p,'stage',paths=['a'])
    with pytest.raises(ValueError,match='身份'):act(m,p,'commit',message='fail')
    act(m,p,'identity',name='Test',email='test@example.invalid');act(m,p,'commit',message='first')
    (p/'.git/MERGE_HEAD').write_text(m.status(p)['head'])
    with pytest.raises(ValueError,match='未完成'):act(m,p,'branch',branch='blocked')

def test_path_configuration(repo):
    m,p=repo;exe=m.executable();assert m.configure_path(exe)['installed']
    with pytest.raises(ValueError):m.configure_path(str(p/'not-git.exe'))
    assert m.configure_path('')['installed']

def test_api_auth_schema_and_draft_only_suggestion(tmp_path,monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_GLOBAL',str(tmp_path/'global'))
    root=tmp_path/'repo';root.mkdir()
    with client(tmp_path,ScriptedModel({'role':'assistant','content':'添加说明文件'})) as c:
        assert c.get('/v1/git/environment').status_code==401
        c.headers['Authorization']='Bearer '+TOKEN
        p=c.post('/v1/projects',json={'path':str(root)}).json()['id'];url='/v1/projects/'+p+'/git'
        assert c.post(url,json={'action':'force-push'}).status_code==422
        assert c.post(url,json={'action':'init','branch':'main'}).status_code==200
        (root/'a').write_text('a');state=c.get(url).json()
        assert c.post(url,json={'action':'stage','root':state['root'],'token':state['token'],'paths':['a']}).status_code==200
        state=c.get(url).json();result=c.post(url,json={'action':'suggest','token':state['token'],'root':state['root']})
        assert result.status_code==200 and result.json()['message']=='添加说明文件'
        assert c.get(url).json()['head']==''
        assert c.get(url+'/file',params={'path':'../outside'}).status_code==409
        assert c.get(url+'/history',params={'commit':'HEAD;bad'}).status_code==409


def test_custom_git_path_used_by_agent_tool(repo):
    from local_agent.tools import execute_tool
    m,p=repo;init(m,p);(p/'a').write_text('before');act(m,p,'stage',paths=['a']);act(m,p,'commit',message='initial')
    (p/'a').write_text('after')
    assert '+after' in execute_tool(p,'git_diff','{}',m.executable())


def test_commit_hook_failure_keeps_index(repo):
    m,p=repo;init(m,p);(p/'a').write_text('content');act(m,p,'stage',paths=['a'])
    hook=p/'.git/hooks/pre-commit';hook.write_text('#!/bin/sh\necho simulated-failure >&2\nexit 1\n',encoding='utf-8',newline='\n');hook.chmod(0o755)
    with pytest.raises(ValueError,match='simulated-failure'):act(m,p,'commit',message='retain this message')
    assert not m.status(p)['head'] and m.status(p)['files'][0]['staged']
    assert (p/'a').read_text()=='content'
