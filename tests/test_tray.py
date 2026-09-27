import threading
from local_agent.tray import TrayController

class Adapter:
    def __init__(self):self.events=[];self.closed=threading.Event()
    def hide(self):self.events.append('hide')
    def show(self):self.events.append('show')
    def notify(self,text):self.events.append(text)
    def stopping(self):self.events.append('stopping')
    def close(self):self.events.append('close');self.closed.set()

def make(shutdown=lambda:None):
    c=TrayController(None,shutdown);c.adapter=Adapter();c.ready=True;return c

def test_close_hides_and_restore():
    c=make();assert c.closing() is False;assert c.hidden
    c.show();assert not c.hidden;assert c.adapter.events==['hide','show']

def test_notifications_only_when_hidden_and_relevant():
    c=make();c.completed('completed');assert not c.adapter.events
    c.closing();c.completed('completed');c.completed('waiting_approval');c.completed('failed')
    assert len(c.adapter.events)==4
    c.completed('cancelled');assert len(c.adapter.events)==4
    c.show();c.completed('completed');assert c.adapter.events[-1]=='show'

def test_exit_waits_for_shutdown_and_is_idempotent():
    started=threading.Event();release=threading.Event()
    def shutdown():started.set();assert release.wait(3)
    c=make(shutdown);c.exit();assert started.wait(1);assert not c.adapter.closed.is_set()
    c.exit();c.completed('completed');assert c.adapter.events==['stopping']
    release.set();assert c.adapter.closed.wait(2);assert c.closing() is None

def test_not_ready_does_not_hide():
    c=make();c.ready=False;assert c.closing() is False;assert not c.hidden


def test_task_completion_callback_is_independent_of_ui(tmp_path):
    from local_agent.tasks import Tasks
    from local_agent.core import AgentCore
    from local_agent.storage import Store, empty_session
    from local_agent.preferences import Preferences
    from local_agent.schemas import MessageCreate
    from test_core import ScriptedModel
    store=Store(tmp_path/'data');project=tmp_path/'project';project.mkdir()
    state=empty_session(project)
    engine=AgentCore(state,ScriptedModel({'role':'assistant','content':'done'}),store.save,options=Preferences(mode='chat'))
    statuses=[];done=threading.Event()
    def completed(status):statuses.append(status);done.set()
    lock=threading.Lock();tasks=Tasks(lock,lambda _:engine,store,completed)
    tasks.start('project','send',MessageCreate(content='test'))
    assert done.wait(3)
    assert statuses==['completed']
    assert not lock.locked()
    tasks.shutdown()
