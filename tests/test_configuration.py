import json
from dataclasses import replace
import pytest
from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.client_config import crypt, read_config, update_config
from local_agent.service import create_app

def test_dpapi_current_user_integration():
    try:
        encrypted = crypt(b'test')
    except OSError as exc:
        if exc.errno in {2, 5, 1312}:
            pytest.skip(f'Windows sandbox user profile unavailable: {exc.errno}')
        raise
    assert crypt(encrypted, decrypt=True) == b'test'

@pytest.fixture
def credential_store(monkeypatch):
    # Test persistence and API masking separately from the Windows user profile.
    monkeypatch.setattr('local_agent.client_config.crypt',lambda value,decrypt=False: value[::-1])

def test_dpapi_roundtrip_and_masked_endpoint(tmp_path,credential_store):
    key = 'sk-test-key-not-real'
    settings = Settings(data_dir=tmp_path, local_token='x'*40)
    with TestClient(create_app(settings), base_url='http://localhost') as c:
        c.headers['Authorization'] = 'Bearer ' + settings.local_token
        r=c.put('/v1/configuration',json={'base_url':'http://192.168.1.77:4000','model':'local-agent-coder','api_key':key})
        assert r.status_code == 200
        assert r.json()['key_configured']
        assert key not in r.text
        assert key not in (tmp_path/'client-config.json').read_text()
        assert read_config(tmp_path)['api_key'] == key
        assert c.put('/v1/configuration',json={'base_url':'http://192.168.1.77:4000/v1','model':'other','api_key':None}).status_code == 200
        assert read_config(tmp_path)['api_key'] == key

@pytest.mark.parametrize('url',['https://public.example/v1','http://8.8.8.8/v1','http://user:password@192.168.1.77/v1','http://192.168.1.77/v1?key=secret','http://0.0.0.0/v1'])
def test_configuration_rejects_non_lan_or_credential_urls(tmp_path,url):
    with pytest.raises(ValueError):
        update_config(Settings(data_dir=tmp_path),url,'model','key')
    assert not (tmp_path/'client-config.json').exists()

def test_saved_config_loads_and_frozen_does_not_load_developer_env(tmp_path,monkeypatch,credential_store):
    import sys
    monkeypatch.setattr(sys,'frozen',True,raising=False)
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    for name in ['LITELLM_API_KEY','LITELLM_BASE_URL','AGENT_DATA_DIR','AGENT_MODEL']:
        monkeypatch.delenv(name,raising=False)
    settings=Settings.load()
    assert settings.api_key == ''
    assert settings.data_dir == tmp_path/'LocalAgent'
    update_config(settings,'http://192.168.1.77:4000/v1','saved-model','saved-key')
    assert Settings.load().api_key == 'saved-key'
    assert Settings.load().model == 'saved-model'

def test_session_only_settings_do_not_persist_key(tmp_path):
    new = update_config(Settings(data_dir=tmp_path),'http://192.168.1.77:4000/v1','model','secret',False)
    assert new.api_key == 'secret'
    assert not (tmp_path/'client-config.json').exists()
