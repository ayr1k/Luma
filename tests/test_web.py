from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_existing_web_uses_core_without_model_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_DATA_DIR', str(tmp_path / 'data'))
    app = AppTest.from_file(str(Path(__file__).resolve().parents[1] / 'web.py'))
    app.session_state['workspace'] = str(tmp_path)
    app.run(timeout=20)
    assert not app.exception
    assert app.session_state['agent_changes'] == {}
    assert app.session_state['status'] == 'idle'
