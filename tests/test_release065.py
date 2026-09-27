import json
from pathlib import Path
import pytest
from local_agent.extensions import Extensions
from test_tasks import setup,register
from test_core import ScriptedModel
ROOT=Path(__file__).resolve().parents[1]
def installed(tmp_path):
 e=Extensions(tmp_path);e.sync_bundled(ROOT/'preset_plugins');return e

def test_details_diagnosis_changed_files(tmp_path):
 e=installed(tmp_path);p=e.details('luma-project-overview')
 assert p['author']=='Luma' and p['examples'] and p['tools']
 assert any(x['status']=='未启用' for x in e.diagnose()['items'])
 e.toggle('luma-project-overview',True,True)
 (e.packages/'luma-project-overview/plugin.json').write_text('{}')
 row=next(x for x in e.diagnose()['items'] if x['id']=='luma-project-overview')
 assert row['status']=='不可用' and '修改' in row['reason']

def test_transfer_atomic_validated_and_no_trust(tmp_path):
 e=installed(tmp_path);e.toggle('luma-palette',True)
 doc=e.export_config();assert len(doc['plugins'])==7
 assert all(set(p)=={'id','slot','version','config'} for p in doc['plugins'])
 pal=next(p for p in doc['plugins'] if p['id']=='luma-palette');pal['config']['accent']='#123456'
 before=e.registry.read_bytes();preview=e.import_config(doc)
 assert preview['changes'] and not preview['applied'] and e.registry.read_bytes()==before
 bad=json.loads(json.dumps(doc));bad['plugins'][-1]['config']['invalid-key']=True
 with pytest.raises(ValueError,match='config'):e.import_config(bad,True)
 assert e.registry.read_bytes()==before
 e.import_config(doc,True);s=e.state()
 assert s['plugins']['luma-palette']['config']['accent']=='#123456'
 assert s['plugins']['luma-palette']['enabled']
 assert not s['plugins']['luma-project-overview']['enabled']
 doc['plugins'].append(dict(doc['plugins'][0]))
 with pytest.raises(ValueError,match='重复'):e.import_config(doc,True)

def test_developer_locations_and_no_execution(tmp_path):
 e=Extensions(tmp_path/'data');p=tmp_path/'package';p.mkdir()
 (p/'plugin.json').write_text('{\n "bad": }')
 r=e.validate_package(directory=str(p));assert not r['ok'] and r['issues'][0]['path'].startswith('plugin.json:2:')
 manifest=json.loads((ROOT/'preset_plugins/luma-project-overview/plugin.json').read_text(encoding='utf-8'))
 manifest['skills']=[]
 (p/'plugin.json').write_text(json.dumps(manifest));(p/manifest['entrypoint']).write_text('this is invalid python !!!')
 r=e.validate_package(directory=str(p));assert not r['ok'] and any(x['path'].startswith(manifest['entrypoint']+':1:') for x in r['issues'])
 (p/manifest['entrypoint']).write_text("raise RuntimeError('MUST NOT EXECUTE')")
 # Overview has no bundled skill files; static validation accepts raising code without running it.
 r=e.validate_package(directory=str(p));assert r['ok'],r
 manifest['tools'][0]['input_schema']={'type':'object','properties':{'path':{'type':'not-a-type'}}}
 (p/'plugin.json').write_text(json.dumps(manifest))
 r=e.validate_package(directory=str(p));assert not r['ok'] and any('tools[0].input_schema' in x['path'] for x in r['issues'])

def test_project_defaults_api_survive_and_invalid_atomic(tmp_path):
 c,w=setup(tmp_path,ScriptedModel([]))
 with c:
  pid=register(c,w);e=Extensions(tmp_path/'data');e.save_skill('review','Review carefully')
  e.sync_bundled(ROOT/'preset_plugins');e.toggle('luma-project-overview',True,True)
  url=f'/v1/projects/{pid}/metadata'
  result=c.put(url,json={'default_skills':['user:review'],'default_plugins':['luma-project-overview']})
  assert result.status_code==200,result.text
  assert result.json()['default_skills']==['user:review']
  assert c.get('/v1/projects').json()[0]['default_plugins']==['luma-project-overview']
  assert c.put(url,json={'default_skills':['missing'],'default_plugins':[]}).status_code==409
  assert c.get('/v1/projects').json()[0]['default_plugins']==['luma-project-overview']
  assert c.post('/v1/extensions',json={'action':'details','id':'luma-palette'}).status_code==200
  assert c.post('/v1/extensions',json={'action':'diagnose'}).status_code==200


def test_checker_handles_missing_or_malformed_schema(tmp_path):
 e=Extensions(tmp_path/'data');p=tmp_path/'package';p.mkdir()
 for value in [None,[],True,{'type':'not-real'}]:
  m={'id':'test','api_version':1,'version':'1.0.0','name':'test','description':'test','tools':[{'name':'run','description':'test'}]}
  if value is not None:m['tools'][0]['input_schema']=value
  (p/'plugin.json').write_text(json.dumps(m))
  result=e.validate_package(directory=str(p))
  assert not result['ok'] and result['issues']
