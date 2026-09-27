import pytest
from local_agent.code_preview import code_preview

@pytest.mark.parametrize('path,text',[('x.py','def add(a, b):\n    # comment\n    return a + 123\n'),('x.js','const text = "hello";'),('x.json','{"value":123}'),('x.html','<script>alert("x")</script>'),('x.unknownextension','<img src=x onerror=alert(1)>\n'),('x.py',''),('x.py','x=1\r\ny=2\r\n')])
def test_preserves_exact_source(path,text):
    preview=code_preview(path,text)
    assert ''.join(value for kind,value in preview['tokens'])==text
    assert all(kind in {'plain','keyword','string','number','comment','function','operator'} for kind,value in preview['tokens'])

def test_python_categories():
    result=code_preview('x.py','def add():\n    # test\n    return "text", 123')
    assert {'keyword','function','comment','string','number'} <= {k for k,v in result['tokens']}

def test_large_file_plain_fallback():
    assert code_preview('x.py','x'*100001)['highlight_limited']
