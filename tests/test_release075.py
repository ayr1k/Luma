import copy
import json
import pytest
from local_agent.core import AgentCore
from local_agent.storage import Store, empty_session
from local_agent.review import overview, detail, resolve, PREVIEW_LIMIT
from test_core import ScriptedModel, call, message
from test_service import client, TOKEN


def make_engine(tmp_path):
    work = tmp_path/'project'
    work.mkdir()
    store = Store(tmp_path/'data')
    engine = AgentCore(empty_session(work), ScriptedModel(), store.save)
    engine.state['turn_id'] = 'turn1'
    engine.state['visible_messages'] = [{'role':'user','content':'完善计算器'}]
    return engine, store


def write(engine, path, content):
    args = dict(path=path, content=content)
    assert not engine.edit('write_file', args, json.dumps(args)).startswith('ERROR:')
    engine.persist()


def selected(engine, path):
    r = next(r for r in overview(engine.state)['files'] if r['path']==path)
    return dict(path=path, revision=r['revision'])


def test_round_snapshots_and_cumulative(tmp_path):
    e, store = make_engine(tmp_path)
    (e.workspace/'a.py').write_bytes(b'old\r\n')
    write(e,'a.py','first\n')
    write(e,'a.py','second\n')
    e.state['turn_id']='turn2'
    write(e,'a.py','third\n')
    restored = store.load(e.workspace)
    assert len(overview(restored)['rounds'])==2
    assert detail(restored,'a.py','turn1')['before']=='old\r\n'
    assert detail(restored,'a.py','turn1')['after'].replace('\r\n','\n')=='second\n'
    assert detail(restored,'a.py','turn2')['before'].replace('\r\n','\n')=='second\n'
    assert detail(restored,'a.py')['after'].replace('\r\n','\n')=='third\n'
    d=detail(restored,'a.py','turn2')
    assert (d['additions'],d['deletions'])==(1,1)
    assert resolve(e,'revert',[selected(e,'a.py')])['done']==['a.py']
    assert (e.workspace/'a.py').read_bytes()==b'old\r\n'


def test_per_file_keep_and_new_file_revert(tmp_path):
    e,_=make_engine(tmp_path)
    write(e,'one','one');write(e,'two','two')
    assert resolve(e,'keep',[selected(e,'one')])['done']==['one']
    assert (e.workspace/'one').read_text()=='one'
    assert set(e.state['agent_changes'])=={'two'}
    assert resolve(e,'revert',[selected(e,'two')])['done']==['two']
    assert not (e.workspace/'two').exists()


def test_stale_review_and_manual_edit_never_overwrite(tmp_path):
    e,_=make_engine(tmp_path);write(e,'a','agent')
    token=selected(e,'a');(e.workspace/'a').write_text('manual')
    assert resolve(e,'keep',[token])['skipped']
    assert resolve(e,'revert',[selected(e,'a')])['skipped']
    assert (e.workspace/'a').read_text()=='manual'
    assert overview(e.state)['files'][0]['warning']
    # Explicit keep can acknowledge the latest manual edit without writing it.
    assert resolve(e,'keep',[selected(e,'a')])['done']==['a']


def test_replaced_directory_and_missing_file(tmp_path):
    e,_=make_engine(tmp_path);write(e,'a','agent')
    (e.workspace/'a').unlink();(e.workspace/'a').mkdir()
    row=overview(e.state)['files'][0]
    assert not row['can_revert']
    assert e.revert()['skipped']==['a']
    (e.workspace/'a').rmdir()
    d=detail(e.state,'a')
    assert d['after_missing'] and d['warning']


def test_legacy_and_non_text_limits(tmp_path):
    e,_=make_engine(tmp_path);write(e,'a','agent')
    e.state['agent_changes']['a'].pop('review_rounds')
    assert not overview(e.state)['rounds']
    assert detail(e.state,'a')['before_missing']
    (e.workspace/'a').write_bytes(b'\x00binary')
    assert detail(e.state,'a')['preview_error']
    (e.workspace/'a').write_bytes(b'x'*(PREVIEW_LIMIT+1))
    assert detail(e.state,'a')['after'] is None


@pytest.mark.parametrize('status',['running','paused','interrupted'])
def test_unfinished_work_blocks_review_mutation(tmp_path,status):
    e,_=make_engine(tmp_path);write(e,'a','agent')
    token=selected(e,'a');e.state['status']=status
    with pytest.raises(ValueError):resolve(e,'revert',[token])
    assert (e.workspace/'a').exists()


def test_selection_validated_before_writes_and_snapshot_integrity(tmp_path):
    e,_=make_engine(tmp_path);(e.workspace/'a').write_text('original');write(e,'a','agent')
    with pytest.raises(ValueError):resolve(e,'revert',[selected(e,'a'),dict(path='../bad',revision='0'*64)])
    assert (e.workspace/'a').read_text()=='agent'
    e.state['agent_changes']['a']['before_bytes']='dGFtcGVyZWQ='
    assert not overview(e.state)['files'][0]['can_revert']
    assert resolve(e,'revert',[selected(e,'a')])['skipped']


def test_fork_does_not_inherit_review_ownership(tmp_path):
    e,store=make_engine(tmp_path);p=store.add_project(str(e.workspace));write(e,'a','agent')
    fork=store.fork_conversation(p['id'])
    assert not overview(store.load_project(fork))['files']
    assert overview(store.load_project(p))['files']


def test_review_api_auth_preview_and_selection(tmp_path):
    model=ScriptedModel(message(call('write_file',path='a.txt',content='<script>hello</script>')),message(call('finish',summary='done')))
    with client(tmp_path,model) as c:
        assert c.get('/v1/projects/unknown/review').status_code==401
        c.headers['Authorization']='Bearer '+TOKEN
        p=c.post('/v1/projects',json={'path':str(tmp_path)}).json()['id'];base='/v1/projects/'+p
        assert c.post(base+'/messages',json={'content':'create'}).status_code==200
        rows=c.get(base+'/review').json()['files'];assert rows[0]['path']=='a.txt'
        d=c.get(base+'/review/file',params={'path':'a.txt'}).json()
        assert d['after']=='<script>hello</script>'
        assert c.get(base+'/review/file',params={'path':'../outside'}).status_code==409
        assert c.post(base+'/review',json={'action':'revert','files':[dict(path='a.txt',revision=rows[0]['revision'])]}).json()['done']==['a.txt']
        assert not (tmp_path/'a.txt').exists()
        assert 'ReviewAction' in c.get('/openapi.json').json()['components']['schemas']


def test_batch_partial_conflict_preserves_only_conflicted_file(tmp_path):
    e,_=make_engine(tmp_path);write(e,'a','a');write(e,'b','b')
    choices=[selected(e,p) for p in ['a','b']]
    (e.workspace/'b').write_text('manual')
    result=resolve(e,'revert',choices)
    assert result['done']==['a'] and result['skipped'][0]['path']=='b'
    assert set(e.state['agent_changes'])=={'b'}

