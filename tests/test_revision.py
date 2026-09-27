import copy
import pytest
from local_agent.core import AgentCore
from local_agent.storage import empty_session
from local_agent.preferences import Preferences
from test_core import ScriptedModel


def core(tmp_path):
    return AgentCore(empty_session(tmp_path), ScriptedModel(*[{'role':'assistant','content':'answer'} for _ in range(5)]), lambda s:None, options=Preferences(mode='chat'))


def test_revision_truncates_history_and_preserves_audit(tmp_path):
    e=core(tmp_path)
    e.submit('first');e.submit('second')
    e.state['agent_changes']={'a':{'after_hash':'test'}}
    e.state['tool_logs']=[{'name':'old'}]
    rev=e.prepare_revision(0,'changed')
    e.revise('changed',rev)
    assert [m['content'] for m in e.state['visible_messages']]==['changed','answer']
    assert 'second' not in str(e.model.histories[-1])
    assert e.state['agent_changes']['a']['after_hash']=='test'
    assert e.state['tool_logs']==[{'name':'old'}]
    assert e.state['visible_messages'][1]['duration_seconds']>=0
    assert e.state['visible_messages'][0]['created_at']


@pytest.mark.parametrize('kind',['image','text'])
def test_revision_retains_attachments_and_supports_old_sessions(tmp_path,kind):
    e=core(tmp_path)
    attachment={'name':'a','kind':kind,'size':1,'content':'data:image/jpeg;base64,eA==' if kind=='image' else 'file contents'}
    e.submit('old',[attachment])
    e.state['visible_messages'][0].pop('agent_index')
    rev=e.prepare_revision(0,'new')
    e.revise('new',rev)
    user=e.model.histories[-1][-1]
    assert 'new' in str(user) and attachment['content'] in str(user)
    assert e.state['visible_messages'][0]['attachments'][0]['name']=='a'


def test_invalid_revision_does_not_mutate(tmp_path):
    e=core(tmp_path);e.submit('old');before=copy.deepcopy(e.state)
    for index,content in [(1,'x'),(99,'x'),(0,'')]:
        with pytest.raises(ValueError):e.prepare_revision(index,content)
        assert e.state==before
    e.state['pending_command']={'approval_id':'old'}
    with pytest.raises(ValueError):e.prepare_revision(0,'new')
