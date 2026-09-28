import pytest
from local_agent.schemas import GitAction
from test_git_manager import repo,init,act


def remote(m,p,action,**kwargs):
    state=m.status(p)
    return m.action(p,GitAction(action=action,root=state['root'],token=state['token'],remote_token=state['remote_token'],**kwargs))

def test_local_remote_roundtrip_and_divergence(repo,tmp_path):
    m,p=repo;init(m,p)
    bare=tmp_path/'server.git';m.text(tmp_path,'init','--bare',str(bare))
    remote(m,p,'remote-add',remote='origin',url=str(bare))
    assert m.status(p)['remotes'][0]['usable']
    assert '连接成功' in remote(m,p,'test-remote',remote='origin')['message']
    (p/'a.txt').write_text('one');act(m,p,'stage',paths=['a.txt']);act(m,p,'commit',message='first')
    remote(m,p,'push',remote='origin',branch='main')
    assert m.status(p)['upstream']=='origin/main'
    assert m.status(p)['ahead']==0
    other=tmp_path/'other';m.text(tmp_path,'clone','--branch','main',str(bare),str(other))
    act(m,other,'identity',name='Other',email='other@example.invalid')
    (other/'b').write_text('two');act(m,other,'stage',paths=['b']);act(m,other,'commit',message='second');remote(m,other,'push',remote='origin',branch='main')
    remote(m,p,'fetch',remote='origin');assert m.status(p)['behind']==1 and not (p/'b').exists()
    remote(m,p,'pull',remote='origin',branch='main');assert (p/'b').read_text()=='two'
    (p/'local').write_text('local');act(m,p,'stage',paths=['local']);act(m,p,'commit',message='local')
    (other/'remote').write_text('remote');act(m,other,'stage',paths=['remote']);act(m,other,'commit',message='remote');remote(m,other,'push',remote='origin',branch='main')
    remote(m,p,'fetch',remote='origin');state=m.status(p);assert (state['ahead'],state['behind'])==(1,1)
    with pytest.raises(ValueError,match='快进'):remote(m,p,'pull',remote='origin',branch='main')
    with pytest.raises(ValueError):remote(m,p,'push',remote='origin',branch='main')
    assert m.status(p)['head']==state['head'] and not (p/'remote').exists()
    (p/'untracked').write_text('keep')
    with pytest.raises(ValueError,match='工作区'):remote(m,p,'pull',remote='origin',branch='main')


def test_remote_validation_and_stale_confirmation(repo,tmp_path):
    m,p=repo;init(m,p)
    for url in ['ext::echo exploit','https://token@github.com/a/b.git','https://github.com/a/b?token=secret','http://example.com/repo','-flag']:
        with pytest.raises(ValueError):remote(m,p,'remote-add',remote='origin',url=url)
    with pytest.raises(ValueError):remote(m,p,'remote-add',remote='--evil',url='https://github.com/a/b.git')
    remote(m,p,'remote-add',remote='origin',url='https://github.com/a/b.git')
    state=m.status(p);assert state['remotes'][0]['web_url']=='https://github.com/a/b'
    m.text(p,'remote','set-url','origin','https://github.com/a/changed.git')
    with pytest.raises(ValueError,match='变化'):
        m.action(p,GitAction(action='fetch',root=state['root'],token=state['token'],remote_token=state['remote_token'],remote='origin'))
    remote(m,p,'remote-edit',remote='origin',url='https://github.com/a/updated.git')
    m.text(p,'config','remote.origin.pushurl','https://github.com/a/push.git')
    with pytest.raises(ValueError,match='独立推送'):remote(m,p,'remote-edit',remote='origin',url='https://github.com/a/final.git')
    remote(m,p,'remote-remove',remote='origin');assert m.status(p)['remotes']==[]


def test_network_errors_are_actionable_and_redacted(repo,monkeypatch):
    m,p=repo;init(m,p);remote(m,p,'remote-add',remote='origin',url='https://github.com/a/b.git')
    original=m.run
    def fail(root,*args,**kwargs):
        if kwargs.get('network'):raise ValueError('Authentication failed https://secret:token@github.com/a/b.git')
        return original(root,*args,**kwargs)
    monkeypatch.setattr(m,'run',fail)
    with pytest.raises(ValueError) as result:remote(m,p,'test-remote',remote='origin')
    assert '认证' in str(result.value) and 'secret' not in str(result.value)
