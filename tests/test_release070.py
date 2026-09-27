import json,hashlib
from pathlib import Path
import pytest
from local_agent.storage import Store,atomic_json,empty_session
from local_agent.extensions import Extensions,skill_metadata
from local_agent.bundled_skills import sync_skills,LEGACY_DIGESTS
from test_core import ScriptedModel,call,message
from test_tasks import setup,register,wait
ROOT=Path(__file__).resolve().parents[1]

def test_legacy_sessions_and_sibling_isolation(tmp_path):
 w=tmp_path/'workspace';w.mkdir();store=Store(tmp_path/'data');parent=store.add_project(w)
 state=store.load(w);state['visible_messages']=[{'role':'user','content':'legacy history'}];store.save(state)
 original=store.session_path(w).read_bytes();child=store.add_conversation(parent['id'],'Review')
 assert child['path']==str(w) and child['session_id']==child['id']
 assert store.session_path(w).read_bytes()==original
 childstate=store.load_project(child);assert not childstate['visible_messages']
 childstate['visible_messages']=[{'role':'user','content':'child only'}];store.save(childstate)
 assert store.load(w)['visible_messages'][0]['content']=='legacy history'
 restarted=Store(tmp_path/'data');assert restarted.load_project(child)['visible_messages'][0]['content']=='child only'
 assert (store.root/'backups/pre-0.7.0-projects.json').is_file()
 with pytest.raises(ValueError):store.load(w,'../escape')

def test_multi_conversation_execution_reset_delete_and_search(tmp_path):
 model=ScriptedModel(message(call('write_file',path='main.txt',content='main')),message(call('finish',summary='parent finished')),
  message(call('write_file',path='child.txt',content='child')),message(call('finish',summary='child finished')))
 c,w=setup(tmp_path,model)
 with c:
  parent=register(c,w);child=c.post(f'/v1/projects/{parent}/conversations',json={'name':'Review'}).json()['id']
  def send(pid,text):return wait(c,c.post(f'/v1/projects/{pid}/tasks',json={'content':text}).json()['id'])['session']
  a=send(parent,'Parent unique query');b=send(child,'Child unique query')
  assert set(a['agent_changes'])=={'main.txt'} and set(b['agent_changes'])=={'child.txt'}
  assert b['session_id']==child and a['session_id'] is None
  assert all(m.get('content')!='Parent unique query' for m in b['visible_messages'])
  result=c.get('/v1/projects',params={'q':'Child unique'}).json();assert [x['id'] for x in result]==[child]
  c.post(f'/v1/projects/{child}/session/reset')
  assert c.get(f'/v1/projects/{parent}/session').json()['visible_messages']
  assert not c.get(f'/v1/projects/{child}/session').json()['visible_messages']
  c.delete(f'/v1/projects/{parent}')
  assert c.get(f'/v1/projects/{child}/session').status_code==200
  again=c.post('/v1/projects',json={'path':str(w)}).json();assert again['id']==child
  assert (w/'main.txt').read_text()=='main' and (w/'child.txt').read_text()=='child'

def test_pending_approval_belongs_to_task_and_blocks_sibling(tmp_path):
 model=ScriptedModel(message(call('run_command',command='echo approved')),message(call('finish',summary='denied safely')))
 c,w=setup(tmp_path,model)
 with c:
  p=register(c,w);a=c.post(f'/v1/projects/{p}/conversations',json={}).json()['id'];b=c.post(f'/v1/projects/{p}/conversations',json={}).json()['id']
  task=c.post(f'/v1/projects/{a}/tasks',json={'content':'run command'}).json();result=wait(c,task['id']);pending=result['session']['pending_command']
  assert pending and not c.get(f'/v1/projects/{p}/session').json()['pending_command']
  assert c.post(f'/v1/projects/{b}/tasks',json={'content':'other'}).status_code==409
  assert c.post(f'/v1/projects/{b}/messages',json={'content':'other'}).status_code==409
  assert c.post(f'/v1/projects/{b}/changes/revert').status_code==409
  assert c.post(f'/v1/projects/{b}/approval-tasks',json={'approval_id':pending['approval_id'],'allow':True}).status_code==409
  reply=c.post(f'/v1/projects/{a}/approval-tasks',json={'approval_id':pending['approval_id'],'allow':False}).json();assert wait(c,reply['id'])['session']['status']=='completed'

def test_group_defaults_and_archive_are_separate(tmp_path):
 c,w=setup(tmp_path,ScriptedModel())
 with c:
  p=register(c,w);e=Extensions(tmp_path/'data');e.save_skill('review','Review')
  c.put(f'/v1/projects/{p}/metadata',json={'default_skills':['user:review']})
  child=c.post(f'/v1/projects/{p}/conversations',json={}).json();assert child['default_skills']==['user:review']
  c.put(f"/v1/projects/{child['id']}/metadata",json={'archived':True,'default_skills':[]})
  rows=c.get('/v1/projects').json();parent=next(x for x in rows if x['id']==p)
  assert not parent['archived'] and parent['default_skills']==[]
  assert next(x for x in rows if x['id']==child['id'])['archived']

def test_all_bundled_compatibility_and_skill_updates(tmp_path):
 e=Extensions(tmp_path/'data');e.sync_bundled(ROOT/'preset_plugins');listing=e.list()
 assert len(listing['plugins'])==11 and not listing['errors']
 for p in listing['plugins']:
  detail=e.details(p['id']);assert detail['compatibility']['max']=='0.7.99' and detail['tested_luma']=='0.7.0'
  assert e.validate_package(directory=str(ROOT/'preset_plugins'/p['id']))['ok']
  e.toggle(p['id'],True,p['requires_trust'])
 assert len([s for s in e.list()['skills'] if s['enabled']])==4
 sync_skills(e,ROOT/'presets');assert len([s for s in e.list()['skills'] if s['id'].startswith('user:')])==5
 for path in list((ROOT/'presets').rglob('SKILL.md'))+list((ROOT/'preset_plugins').rglob('SKILL.md')):
  meta=skill_metadata(path.read_text(encoding='utf-8'),path.parent.name);assert meta['max_luma']=='0.7.99' and meta['tested_luma']=='0.7.0'
 edited=e.skills/'luma-code-review/SKILL.md';edited.write_text('User edited content',encoding='utf-8')
 sync_skills(e,ROOT/'presets');assert edited.read_text()=='User edited content'
 with pytest.raises(ValueError,match='不兼容'):skill_metadata('---\nmax_luma: 0.6.99\n---\nold','old')
 files=e.package_files(directory=str(ROOT/'preset_plugins/luma-project-overview'));m=json.loads(files['plugin.json']);m['max_luma']='0.6.99';files['plugin.json']=json.dumps(m).encode()
 with pytest.raises(ValueError,match='不兼容'):e.manifest(files)

def test_unchanged_legacy_skill_upgrade_and_receipt(tmp_path):
 import re
 e=Extensions(tmp_path/'data');source=tmp_path/'bundles';folder=source/'luma-code-review';folder.mkdir(parents=True)
 current=(ROOT/'presets/luma-code-review/SKILL.md').read_text(encoding='utf-8')
 old=re.sub(r'^(version|author|min_luma|max_luma|tested_luma):.*\n','',current.split('\n多任务使用：')[0],flags=re.M)
 assert hashlib.sha256(old.encode()).hexdigest()==LEGACY_DIGESTS['luma-code-review']
 e.save_skill('luma-code-review',old);(folder/'SKILL.md').write_text(current,encoding='utf-8')
 sync_skills(e,source);assert e.read_skill('user:luma-code-review')['content']==current
 updated=current+'\nAdditional shipped instructions.\n';(folder/'SKILL.md').write_text(updated,encoding='utf-8')
 sync_skills(e,source);assert e.read_skill('user:luma-code-review')['content']==updated
 e.delete_skill('user:luma-code-review');sync_skills(e,source);assert not (e.skills/'luma-code-review').exists()


def test_read_session_does_not_change_last_activity(tmp_path):
 c,w=setup(tmp_path,ScriptedModel())
 with c:
  p=register(c,w);store=Store(tmp_path/'data');state=store.load(w);store.save(state);before=store.session_path(w).read_bytes()
  assert c.get(f'/v1/projects/{p}/session').status_code==200
  assert store.session_path(w).read_bytes()==before

def test_shared_file_rollback_does_not_overwrite_sibling_changes(tmp_path):
 model=ScriptedModel(message(call('write_file',path='shared.txt',content='first')),message(call('finish',summary='one')),
  message(call('write_file',path='shared.txt',content='second')),message(call('finish',summary='two')))
 c,w=setup(tmp_path,model)
 with c:
  p=register(c,w);child=c.post(f'/v1/projects/{p}/conversations',json={}).json()['id']
  for pid in [p,child]:
   task=c.post(f'/v1/projects/{pid}/tasks',json={'content':'write'}).json();assert wait(c,task['id'])['session']['status']=='completed'
  result=c.post(f'/v1/projects/{p}/changes/revert').json()
  assert 'shared.txt' in result['skipped'] and (w/'shared.txt').read_text()=='second'
