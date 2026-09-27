import threading
from local_agent.storage import Store, empty_session

def test_polling_during_atomic_session_updates(tmp_path):
    store=Store(tmp_path/'data')
    state=empty_session(tmp_path)
    store.save(state)
    errors=[]
    done=threading.Event()
    def writer():
        try:
            for step in range(80):
                state['steps']=step
                store.save(state)
        except Exception as exc:
            errors.append(exc)
        finally:
            done.set()
    thread=threading.Thread(target=writer)
    thread.start()
    try:
        while not done.is_set():
            snapshot=store.load(tmp_path)
            assert snapshot['steps'] in range(80)
    finally:
        thread.join(5)
    assert not errors
    assert store.load(tmp_path)['steps']==79
