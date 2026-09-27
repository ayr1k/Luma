from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.service import create_app
from test_core import ScriptedModel, call, message

TOKEN = 'test-local-token-' + 'x' * 32

def client(tmp_path, model):
    return TestClient(create_app(Settings(data_dir=tmp_path / 'data', local_token=TOKEN), model), base_url='http://localhost')

def test_auth_origin_schema(tmp_path):
    with client(tmp_path, ScriptedModel()) as c:
        assert c.get('/health').status_code == 200
        assert c.get('/v1/projects').status_code == 401
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        assert c.get('/v1/projects').status_code == 200
        assert c.get('/v1/projects', headers={'Origin': 'http://evil.test'}).status_code == 403
        assert c.get('/health', headers={'Host': 'evil.test'}).status_code == 403
        schema = c.get('/openapi.json').json()
        assert 'Session' in schema['components']['schemas']

def test_api_edit_approve_finish_revert(tmp_path):
    model = ScriptedModel(message(call('write_file', path='demo.txt', content='hello'), call('run_command', command='echo demo')),
                          message(call('finish', summary='done')))
    with client(tmp_path, model) as c:
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        p = c.post('/v1/projects', json={'path': str(tmp_path)}).json()['id']
        base = '/v1/projects/' + p
        result = c.post(base + '/messages', json={'content': 'demo'}).json()
        assert result['status'] == 'waiting_approval'
        assert (tmp_path / 'demo.txt').read_text() == 'hello'
        assert c.post(base + '/messages', json={'content': 'race'}).status_code == 409
        approval = {'approval_id': result['pending_command']['approval_id'], 'allow': True}
        result = c.post(base + '/approvals', json=approval).json()
        assert result['status'] == 'completed'
        assert c.post(base + '/approvals', json=approval).status_code == 409
        assert 'demo.txt' in c.get(base + '/changes').json()['diffs']
        assert c.post(base + '/changes/revert').json()['reverted'] == ['demo.txt']
        assert not (tmp_path / 'demo.txt').exists()

def test_unknown_project_and_schema_validation(tmp_path):
    with client(tmp_path, ScriptedModel()) as c:
        c.headers['Authorization'] = 'Bearer ' + TOKEN
        assert c.get('/v1/projects/missing/session').status_code == 404
        assert c.post('/v1/projects', json={'path': str(tmp_path), 'unexpected': 1}).status_code == 422
