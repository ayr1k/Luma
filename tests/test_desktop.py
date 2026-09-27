from local_agent.desktop import Bridge, LocalServer
from local_agent.config import Settings
from local_agent.storage import Store
from pathlib import Path

def test_bridge_authenticated_routes_and_file_sandbox(tmp_path):
    server = LocalServer(Settings(data_dir=tmp_path / 'data'))
    server.start()
    try:
        workspace = tmp_path / 'project'
        workspace.mkdir()
        (workspace / 'hello.txt').write_text('<script>not executable</script>', encoding='utf-8')
        bridge = Bridge(server.url, server.token, lambda: str(workspace))
        p = bridge.request('add')['data']
        assert bridge.request('projects')['data'][0]['id'] == p['id']
        assert bridge.request('files', p['id'])['data'] == ['hello.txt']
        assert bridge.request('file', p['id'], {'path': 'hello.txt'})['data']['content'].startswith('<script>')
        assert not bridge.request('file', p['id'], {'path': '../private.txt'})['ok']
        assert not bridge.request('session', '../../evil')['ok']
        assert not bridge.request('http://evil.test')['ok']
        assert not Bridge(server.url, 'wrong').request('projects')['ok']
        assert bridge.request('session', p['id'])['data']['status'] == 'idle'
    finally:
        server.stop()
    assert not server.thread.is_alive()

def test_ui_never_interprets_model_html():
    source = (Path(__file__).resolve().parents[1] / 'local_agent/ui/index.html').read_text(encoding='utf-8')
    assert 'innerHTML' not in source
    assert 'textContent' in source
    assert 'LITELLM_API_KEY' not in source
    assert 'AGENT_LOCAL_TOKEN' not in source
