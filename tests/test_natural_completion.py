from test_planning_resume import make,text
from test_core import message,call

def test_write_then_natural_summary_ends_without_extra_request(tmp_path):
    e=make(tmp_path,text('I will create a file.'),message(call('write_file',path='calculator.py',content='print(1+1)')),text('文件已创建，你可以运行它。'))
    e.submit('create calculator')
    assert e.state['status']=='completed'
    assert len(e.model.histories)==3
    assert (tmp_path/'calculator.py').read_text()=='print(1+1)'
    assert e.state['agent_messages'][-1]['content']=='文件已创建，你可以运行它。'

def test_old_success_does_not_complete_new_unexecuted_turn(tmp_path):
    e=make(tmp_path,message(call('write_file',path='x',content='x')),text('Done'),*[text('I will do it.') for _ in range(6)])
    e.submit('first');assert e.state['status']=='completed'
    e.submit('second');assert e.state['status']=='paused'

def test_failed_tool_not_treated_as_success(tmp_path):
    e=make(tmp_path,message(call('read_file',path='missing.txt')),*[text('Done') for _ in range(6)])
    e.submit('read missing file');assert e.state['status']=='paused'

def test_question_after_tools_still_waits(tmp_path):
    e=make(tmp_path,message(call('write_file',path='x',content='x')),text('[NEED_INPUT] 请确认是否继续？'))
    e.submit('test');assert e.state['pause_reason']=='input'

def test_explicit_finish_and_followup_tools_preserved(tmp_path):
    e=make(tmp_path,message(call('write_file',path='x',content='x')),message(call('read_file',path='x')),message(call('finish',summary='Verified')))
    e.submit('test');assert e.state['status']=='completed'
    assert [l['name'] for l in e.state['tool_logs']]==['write_file','read_file','finish']
