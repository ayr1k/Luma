import json
from dataclasses import replace
from types import SimpleNamespace as NS
import pytest
from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.preferences import Preferences,load_preferences,save_preferences
from local_agent.model_profiles import ModelProfiles,CapabilityOverrides,safe_failure
from local_agent.service import create_app
from local_agent.diagnostics import run_probe
from local_agent.model import LANModel

def test_profiles_isolate_models_hosts_and_survive_restart(tmp_path):
    a=Settings(data_dir=tmp_path,model='A');b=replace(a,model='B');other=replace(a,base_url='http://other/v1')
    old=Preferences(temperature=.3);save_preferences(tmp_path,old)
    p=ModelProfiles(tmp_path,old);p.save_parameters(a,Preferences(temperature=.9,reasoning_effort='high'))
    assert p.effective(b,old).temperature==.3
    assert p.effective(other,old).reasoning_effort=='default'
    p.set_manual(a,CapabilityOverrides(tools='supported'))
    p.record(a,'tools',False,'request_rejected')
    p=ModelProfiles(tmp_path,old)
    assert p.effective(a,old).temperature==.9
    assert p.describe(a)['capabilities']['tools']['manual']=='supported'
    assert p.describe(a)['capabilities']['tools']['tested']['passed'] is False
    assert load_preferences(tmp_path)==old # LTS format is unchanged
    assert a.base_url not in p.path.read_text() and 'api_key' not in p.path.read_text()
    p.save_parameters(a,Preferences(temperature=.1))
    assert p.describe(a)['capabilities']['tools']['tested'] is None
    assert p.describe(a)['capabilities']['tools']['manual']=='supported'

def test_model_selection_restores_parameters_and_exports_allowlist(tmp_path,monkeypatch):
    class Model:
        def list_models(self):return ['A','B']
    settings=Settings(data_dir=tmp_path,model='A',api_key='secret-never-export',local_token='t'*40)
    with TestClient(create_app(settings,Model()),base_url='http://localhost') as c:
        assert c.get('/v1/model-profile').status_code==401
        c.headers['Authorization']='Bearer '+'t'*40
        prefs=c.get('/v1/preferences').json();prefs['temperature']=.8
        assert c.put('/v1/preferences',json=prefs).status_code==200
        assert c.put('/v1/models/selection',json={'model':'B'}).status_code==200
        assert c.get('/v1/preferences').json()['temperature']==0
        c.put('/v1/models/selection',json={'model':'A'})
        assert c.get('/v1/preferences').json()['temperature']==.8
        assert c.put('/v1/model-profile',json={'tools':'invalid'}).status_code==422
        monkeypatch.setattr('local_agent.diagnostics.run_probe',lambda *a:{'passed':False,'code':'timeout','detail':'Fixed message'})
        assert c.post('/v1/model-diagnostics',json={'probe':'tools'}).json()['code']=='timeout'
        report=c.get('/v1/model-diagnostics/report').json()
        assert report['tests']['tools']['passed'] is False
        assert set(report)=={'format','version','luma','parameters','manual','tests'}
        assert 'secret-never-export' not in json.dumps(report) and settings.base_url not in json.dumps(report)

@pytest.mark.parametrize('status,code',[(401,'authentication'),(403,'permission'),(404,'not_found'),(400,'request_rejected'),(422,'request_rejected'),(429,'rate_limit'),(500,'provider_error')])
def test_errors_do_not_expose_provider_bodies(status,code):
    e=Exception('secret token and private prompt');e.status_code=status
    actual,detail=safe_failure(e)
    assert actual==code and 'secret' not in detail and 'private' not in detail

def test_tool_probe_validates_without_execution(monkeypatch):
    captured=[]
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        @property
        def chat(self):return NS(completions=NS(create=self.create))
        def create(self,**kwargs):
            captured.append(kwargs)
            return NS(choices=[NS(finish_reason='tool_calls',message=NS(tool_calls=[NS(function=NS(name='luma_probe',arguments='{"value":"OK"}'))]))])
    monkeypatch.setattr(LANModel,'_client',lambda self:Client())
    assert run_probe(Settings(),Preferences(),'tools')['passed']
    assert captured[0]['tools'][0]['function']['name']=='luma_probe'
    assert 'run_command' not in json.dumps(captured)

def test_failed_stream_and_default_reasoning_not_marked_supported(monkeypatch):
    class Stream:
        def __enter__(self):return iter([NS(choices=[NS(delta=NS(content='partial'),finish_reason='length')])])
        def __exit__(self,*args):pass
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        chat=NS(completions=NS(create=lambda **kw:Stream()))
    monkeypatch.setattr(LANModel,'_client',lambda self:Client())
    assert not run_probe(Settings(),Preferences(),'streaming')['passed']
    assert run_probe(Settings(),Preferences(),'reasoning')['code']=='not_configured'
