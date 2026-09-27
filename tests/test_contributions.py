import copy
import json
from pathlib import Path
import pytest
from local_agent.extensions import Extensions
from local_agent.contributions import configuration
from test_extensions import make_core

PACKAGES=Path(__file__).parents[1]/'preset_plugins'

def manager(tmp_path):
    e=Extensions(tmp_path);e.sync_bundled(PACKAGES);return e

def test_slots_combine_and_exclude_with_restore(tmp_path):
    e=manager(tmp_path)
    e.toggle('luma-palette',True);e.toggle('luma-typography',True)
    folder=tmp_path/'alternative';folder.mkdir()
    m=json.loads((PACKAGES/'luma-palette/plugin.json').read_text(encoding='utf-8'))
    m['id']='other-palette';(folder/'plugin.json').write_text(json.dumps(m),encoding='utf-8')
    p=e.inspect(directory=str(folder));e.install(directory=str(folder),expected_digest=p['digest'])
    e.toggle('other-palette',True)
    enabled={p['id'] for p in e.list()['plugins'] if p['enabled']}
    assert enabled=={'other-palette','luma-typography'}
    e.configure('other-palette',{'palette':'white','accent':'#224466'})
    e.reset_appearance()
    assert not any(p['enabled'] for p in e.list()['plugins'])
    assert e.state()['plugins']['other-palette']['config']['palette']=='white'

@pytest.mark.parametrize('key,values',[
    ('luma-palette',{'accent':'url(https://example.com)'}),
    ('luma-typography',{'ui_font':'x";background:url(x)'}),
    ('luma-material',{'opacity':0}),
    ('luma-hotkey',{'shortcut':'Ctrl+Alt+Delete'}),
    ('luma-widget',{'arbitrary_command':'powershell'}),
    ('luma-snippets',{'phrases':[{'title':'','text':'x'}]}),
])
def test_reject_invalid_config_without_mutation(tmp_path,key,values):
    e=manager(tmp_path);before=e.registry.read_bytes()
    with pytest.raises(ValueError):e.configure(key,values)
    assert e.registry.read_bytes()==before

def test_config_persists_upgrade_and_user_disabled_state(tmp_path):
    e=manager(tmp_path);e.configure('luma-hotkey',{'shortcut':'Ctrl+Shift+Space'});e.toggle('luma-hotkey',True)
    e.sync_bundled(PACKAGES)
    assert e.state()['plugins']['luma-hotkey']['enabled']
    p=e.inspect(directory=str(PACKAGES/'luma-hotkey'))
    e.install(directory=str(PACKAGES/'luma-hotkey'),expected_digest=p['digest'])
    row=Extensions(tmp_path).state()['plugins']['luma-hotkey']
    assert row['config']['shortcut']=='Ctrl+Shift+Space' and not row['enabled']

def test_declarative_package_cannot_smuggle_code(tmp_path):
    e=manager(tmp_path)
    m=copy.deepcopy(e.state()['plugins']['luma-palette']['manifest'])
    m['entrypoint']='main.py';m['permissions']=['local-code']
    with pytest.raises(ValueError):e.manifest({'plugin.json':json.dumps(m).encode(),'main.py':b'print(1)'})

def test_enabled_plugin_without_selection_cannot_run(tmp_path):
    core,_=make_core(tmp_path);core.submit('count')
    assert core.state['pending_command'] is None
    assert core.state['tool_logs'][0]['result'].startswith('ERROR:')
    assert 'plugin_tool' not in core.tool_names()
    assert 'count-files' not in core.state['agent_messages'][0]['content']

def test_selection_retained_on_revision_and_checked_before_truncation(tmp_path):
    core,_=make_core(tmp_path);core.submit('count',plugins=['project-stats'])
    core.approve(core.state['pending_command']['approval_id'],False)
    revision=core.prepare_revision(0,'again')
    assert revision['plugins']==['project-stats']
    core.extensions.toggle('project-stats',False)
    before=copy.deepcopy(core.state)
    with pytest.raises(ValueError):core.prepare_revision(0,'again')
    assert core.state==before

def test_declarative_never_in_tool_catalog(tmp_path):
    e=manager(tmp_path)
    for p in e.list()['plugins']:
        if p['contribution']:e.toggle(p['id'],True)
    assert e.catalog()==[]
    with pytest.raises(ValueError):e.selected_plugins(['luma-widget'])

def test_selected_subset_not_all_enabled(tmp_path):
    e=manager(tmp_path)
    for key in ['luma-project-overview','luma-image-tools']:e.toggle(key,True,True)
    assert {x['plugin'] for x in e.catalog(['luma-image-tools'])}=={'luma-image-tools'}
    assert e.catalog([])==[]
