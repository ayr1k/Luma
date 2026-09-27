import base64, io, json, zipfile
import pytest
from PIL import Image
from fastapi.testclient import TestClient
from local_agent.attachments import prepare_attachments, message_parts
from local_agent.schemas import AttachmentInput
from local_agent.config import Settings
from local_agent.service import create_app
from local_agent.core import AgentCore
from local_agent.storage import empty_session, Store
from local_agent.preferences import Preferences
from test_core import ScriptedModel

def attachment(name,raw):return AttachmentInput(name=name,data=base64.b64encode(raw).decode())
def png():
    out=io.BytesIO();Image.new('RGB',(30,20),'red').save(out,format='PNG');return out.getvalue()

def test_image_normalized_for_vision_and_thumbnail():
    a=prepare_attachments([attachment('image.png',png())])[0]
    assert a['kind']=='image' and a['content'].startswith('data:image/jpeg;base64,')
    parts=message_parts('描述图片',[a])
    assert parts[0]['text']=='描述图片' and parts[-1]['type']=='image_url'
    Image.open(io.BytesIO(base64.b64decode(a['preview'].split(',')[1]))).verify()

def test_text_files_and_docx_extract_without_image_parts():
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>文档内容</w:t></w:r></w:p></w:body></w:document>')
    prepared=prepare_attachments([attachment('notes.txt','你好'.encode()),attachment('a.docx',out.getvalue())])
    parts=message_parts('',prepared)
    assert isinstance(parts,str) and '你好' in parts and '文档内容' in parts

@pytest.mark.parametrize('name,raw',[('bad.png',b'not image'),('bad.exe',b'MZ'),('null.txt',b'a\0b'),('bad.txt',b'\xff'),('long.txt',b'a'*60001)], ids=['bad-image','unsupported','binary','encoding','too-long'])
def test_invalid_attachments_rejected(name,raw):
    with pytest.raises(ValueError):prepare_attachments([attachment(name,raw)])

def test_attachment_limits():
    with pytest.raises(ValueError):prepare_attachments([attachment('a.txt',b'x')]*5)
    with pytest.raises(ValueError):prepare_attachments([attachment('a.txt',b'a'*(10*1024*1024+1))])

def test_pdf_text_and_scan_rejection():
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
    writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
    blank=io.BytesIO();writer.write(blank)
    with pytest.raises(ValueError,match='扫描'):prepare_attachments([attachment('scan.pdf',blank.getvalue())])
    font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):font})})
    stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 10 200 Td (PDF attachment test) Tj ET')
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=io.BytesIO();writer.write(out)
    assert 'PDF attachment test' in prepare_attachments([attachment('text.pdf',out.getvalue())])[0]['content']

def test_multimodal_history_survives_save_and_no_duplicate_image_payload(tmp_path):
    store=Store(tmp_path/'data');model=ScriptedModel({'role':'assistant','content':'red'})
    engine=AgentCore(empty_session(tmp_path),model,store.save,options=Preferences(mode='chat'))
    engine.submit('',prepare_attachments([attachment('red.png',png())]))
    state=store.load(tmp_path)
    assert state['agent_messages'][1]['content'][-1]['type']=='image_url'
    assert 'content' not in state['visible_messages'][0]['attachments'][0]
    assert state['visible_messages'][0]['attachments'][0]['name']=='red.png'
    assert state['status']=='completed'

def test_invalid_upload_rejected_before_task_and_file_only_accepted(tmp_path):
    model=ScriptedModel({'role':'assistant','content':'file read'})
    with TestClient(create_app(Settings(data_dir=tmp_path/'data',local_token='t'*40),model),base_url='http://localhost',headers={'Authorization':'Bearer '+'t'*40}) as c:
        p=c.post('/v1/projects',json={'path':str(tmp_path)}).json()['id']
        assert c.post(f'/v1/projects/{p}/tasks',json={'attachments':[attachment('bad.exe',b'bad').model_dump()]}).status_code==409
        assert not model.histories
        c.put('/v1/preferences',json={'mode':'chat'})
        response=c.post(f'/v1/projects/{p}/messages',json={'attachments':[attachment('a.txt',b'hello').model_dump()]})
        assert response.status_code==200 and response.json()['status']=='completed'
        assert 'hello' in model.histories[0][-1]['content']
        assert c.post(f'/v1/projects/{p}/tasks',json={}).status_code==409

