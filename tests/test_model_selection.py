import json
import threading
from dataclasses import replace
import httpx
from openai import OpenAI
from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.model import LANModel
from local_agent.service import create_app
from local_agent.storage import Store


def setup(tmp_path, monkeypatch):
    state = {'models': ['coder', 'gemma', 'coder'], 'status': 200, 'requests': []}
    def transport(request):
        assert request.headers['Authorization'] == 'Bearer test-key'
        state['requests'].append(request)
        if request.url.path.endswith('/models'):
            return httpx.Response(state['status'], json={'data': [{'id': x, 'object': 'model'} for x in state['models']], 'error': {'message': 'PRIVATE SERVER ERROR'}})
        return httpx.Response(200, json={'id': 'chat-test', 'object': 'chat.completion', 'created': 1, 'model': 'gemma', 'choices': [{'index': 0, 'finish_reason': 'stop', 'message': {'role': 'assistant', 'content': 'done'}}]})
    monkeypatch.setattr(LANModel, '_client', lambda self: OpenAI(base_url=self.settings.base_url, api_key=self.settings.api_key, max_retries=0, http_client=httpx.Client(transport=httpx.MockTransport(transport))))
    settings = Settings(data_dir=tmp_path/'data', local_token='t'*40, api_key='test-key', model='coder')
    model = LANModel(settings)
    client = TestClient(create_app(settings, model), base_url='http://localhost', headers={'Authorization': 'Bearer '+settings.local_token})
    return client, model, settings, state


def test_discovery_selection_inference_and_restart(tmp_path, monkeypatch):
    c, model, settings, state = setup(tmp_path, monkeypatch)
    with c:
        assert c.get('/v1/models', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert c.get('/v1/models').json() == {'models': ['coder', 'gemma'], 'selected': 'coder', 'available': True}
        assert c.put('/v1/models/selection', json={'model': 'gemma'}).json()['model'] == 'gemma'
        model.complete([{'role': 'user', 'content': 'hello'}])
        assert json.loads(state['requests'][-1].content)['model'] == 'gemma'
        saved = (settings.data_dir/'model-selection.json').read_text()
        assert 'test-key' not in saved
        monkeypatch.setenv('AGENT_DATA_DIR', str(settings.data_dir))
        monkeypatch.setenv('LITELLM_BASE_URL', settings.base_url)
        assert Settings.load().model == 'gemma'
        monkeypatch.setenv('LITELLM_BASE_URL', 'http://192.168.1.99:4000/v1')
        assert Settings.load().model != 'gemma'


def test_empty_removed_and_provider_errors(tmp_path, monkeypatch):
    c, model, settings, state = setup(tmp_path, monkeypatch)
    with c:
        state['models'] = []
        assert c.get('/v1/models').json()['models'] == []
        assert c.put('/v1/models/selection', json={'model': 'gemma'}).status_code == 409
        assert model.settings.model == 'coder'
        state['status'] = 401
        response = c.get('/v1/models')
        assert response.status_code == 502
        assert '密钥' in response.json()['detail']
        assert 'PRIVATE SERVER ERROR' not in response.text and 'test-key' not in response.text


def test_model_optional_in_connection_and_session_only(tmp_path, monkeypatch):
    c, model, settings, state = setup(tmp_path, monkeypatch)
    with c:
        response = c.put('/v1/configuration', json={'base_url': settings.base_url, 'api_key': 'test-key', 'remember_key': False})
        assert response.status_code == 200
        assert c.get('/v1/models').status_code == 200
        assert c.put('/v1/models/selection', json={'model': 'gemma'}).status_code == 200
        assert not (settings.data_dir/'model-selection.json').exists()
        assert not (settings.data_dir/'client-config.json').exists()


def test_pending_approval_blocks_switch(tmp_path, monkeypatch):
    c, model, settings, state = setup(tmp_path, monkeypatch)
    workspace = tmp_path/'project'; workspace.mkdir()
    store = Store(settings.data_dir)
    store.add_project(str(workspace))
    session = store.load(workspace)
    session['pending_command'] = {'approval_id': 'pending'}
    store.save(session)
    with c:
        assert c.put('/v1/models/selection', json={'model': 'gemma'}).status_code == 409
        assert model.settings.model == 'coder'


def test_running_task_blocks_switch(tmp_path, monkeypatch):
    c, model, settings, state = setup(tmp_path, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    def complete(self, history, on_text, cancel_event, on_reasoning=None):
        entered.set(); assert release.wait(5)
        return {'role': 'assistant', 'content': 'done'}
    monkeypatch.setattr(LANModel, 'stream_complete', complete)
    workspace = tmp_path/'project'; workspace.mkdir()
    with c:
        p = c.post('/v1/projects', json={'path': str(workspace)}).json()['id']
        try:
            assert c.post(f'/v1/projects/{p}/tasks', json={'content': 'hello'}).status_code == 202
            assert entered.wait(2)
            assert c.put('/v1/models/selection', json={'model': 'gemma'}).status_code == 409
            assert model.settings.model == 'coder'
        finally:
            release.set()
