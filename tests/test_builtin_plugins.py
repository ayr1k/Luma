import copy,json,shutil,threading,zipfile
from pathlib import Path
import pytest
from PIL import Image
from pypdf import PdfWriter
from local_agent.builtin_tools import dispatch
from local_agent.extensions import Extensions

PACKAGES=Path(__file__).resolve().parents[1]/'preset_plugins'

def run(root,plugin,tool,**args):
    data=root.parent/'plugin-data'/plugin
    result=dispatch('luma-'+plugin,dict(workspace=str(root),data_directory=str(data),tool=tool,input=args))['text']
    return result if result.startswith('ERROR:') else json.loads(result)

def workspace(tmp_path):
    root=tmp_path/'project';root.mkdir();return root

def test_overview_ignores_dependencies_and_reports_limits(tmp_path):
    root=workspace(tmp_path);(root/'pyproject.toml').write_text('[project]');(root/'main.py').write_text('pass')
    (root/'node_modules').mkdir();(root/'node_modules/hidden.js').write_text('hidden')
    (root/'nested').mkdir();(root/'nested/file.txt').write_text('test')
    result=run(root,'project-overview','overview',depth=0)
    assert result['files']==2 and result['limited'] and result['skipped']==1
    assert result['configuration_files']==['pyproject.toml']

@pytest.mark.parametrize('plugin,tool,args',[
 ('project-overview','overview',{'directory':'..'}),
 ('document-reader','read-document',{'path':'../secret.txt'}),
 ('image-tools','inspect',{'path':'../secret.png'}),
 ('file-organizer','scan',{'directory':'../'})])
def test_builtins_reject_workspace_escape(tmp_path,plugin,tool,args):
    root=workspace(tmp_path)
    assert run(root,plugin,tool,**args).startswith('ERROR:')

def test_document_pagination_and_keyword_scope(tmp_path):
    root=workspace(tmp_path);(root/'note.md').write_text('first\nsecond\nthird\n',encoding='utf-8')
    result=run(root,'document-reader','read-document',path='note.md',start=2,count=1,query='second')
    assert result['total']==3 and result['items']==[{'number':2,'text':'second'}]
    assert run(root,'document-reader','read-document',path='note.md',start=1,count=1,query='third')['items']==[]

def test_pdf_docx_and_encrypted_document(tmp_path):
    root=workspace(tmp_path);writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.add_blank_page(width=100,height=100)
    with (root/'test.pdf').open('wb') as f:writer.write(f)
    result=run(root,'document-reader','read-document',path='test.pdf',start=2,count=1)
    assert result['unit']=='页' and result['items'][0]['number']==2
    writer.encrypt('secret')
    with (root/'encrypted.pdf').open('wb') as f:writer.write(f)
    assert run(root,'document-reader','read-document',path='encrypted.pdf').startswith('ERROR:')
    with zipfile.ZipFile(root/'test.docx','w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Hello</w:t></w:r></w:p><w:p><w:r><w:t>World</w:t></w:r></w:p></w:body></w:document>')
    result=run(root,'document-reader','read-document',path='test.docx',start=2,count=1)
    assert result['unit']=='段' and result['items'][0]['text']=='World'

def test_image_transform_preserves_source_and_never_overwrites(tmp_path):
    root=workspace(tmp_path);source=root/'source.png';Image.new('RGBA',(100,50),(255,0,0,100)).save(source);before=source.read_bytes()
    result=run(root,'image-tools','transform',path='source.png',output='out/photo.jpg',max_width=40,max_height=40)
    assert result['width']==40 and result['height']==20 and source.read_bytes()==before
    with Image.open(root/'out/photo.jpg') as image:assert image.mode=='RGB' and not image.getexif()
    saved=(root/'out/photo.jpg').read_bytes()
    assert run(root,'image-tools','transform',path='source.png',output='out/photo.jpg').startswith('ERROR:')
    assert (root/'out/photo.jpg').read_bytes()==saved
    assert run(root,'image-tools','transform',path='source.png',output='../outside.png').startswith('ERROR:')

def test_image_animation_rejected_and_webp_available(tmp_path):
    root=workspace(tmp_path);a=Image.new('RGB',(20,20),'red');b=Image.new('RGB',(20,20),'blue')
    a.save(root/'animated.gif',save_all=True,append_images=[b],duration=100,loop=0)
    assert run(root,'image-tools','inspect',path='animated.gif')['frames']==2
    assert run(root,'image-tools','transform',path='animated.gif',output='bad.png').startswith('ERROR:')
    a.save(root/'static.png');assert run(root,'image-tools','transform',path='static.png',output='result.webp')['width']==20

def test_organizer_plan_then_apply_pins_content_and_cannot_replay(tmp_path):
    root=workspace(tmp_path);(root/'a.txt').write_text('content');moves=[{'source':'a.txt','target':'sorted/a.txt'}]
    timestamp=(root/'a.txt').stat().st_mtime_ns
    plan=run(root,'file-organizer','plan-moves',moves=moves)
    assert (root/'a.txt').exists() and not (root/'sorted/a.txt').exists()
    assert run(root,'file-organizer','apply-moves',plan_id=plan['plan_id'],moves=[{'source':'a.txt','target':'other.txt'}]).startswith('ERROR:')
    result=run(root,'file-organizer','apply-moves',plan_id=plan['plan_id'],moves=plan['moves'])
    assert (root/'sorted/a.txt').stat().st_mtime_ns==timestamp
    assert result['status']=='completed' and not (root/'a.txt').exists() and (root/'sorted/a.txt').read_text()=='content'
    assert run(root,'file-organizer','apply-moves',plan_id=plan['plan_id'],moves=plan['moves']).startswith('ERROR:')
    assert json.loads(Path(result['record']).read_text(encoding='utf-8'))['status']=='completed'

@pytest.mark.parametrize('change',['source','target'])
def test_organizer_detects_changes_before_any_move(tmp_path,change):
    root=workspace(tmp_path);(root/'a.txt').write_text('first');(root/'b.txt').write_text('second')
    moves=[{'source':'a.txt','target':'new-a.txt'},{'source':'b.txt','target':'new-b.txt'}]
    plan=run(root,'file-organizer','plan-moves',moves=moves)
    (root/('b.txt' if change=='source' else 'new-b.txt')).write_text('changed')
    assert run(root,'file-organizer','apply-moves',plan_id=plan['plan_id'],moves=moves).startswith('ERROR:')
    assert (root/'a.txt').exists() and not (root/'new-a.txt').exists()

def test_organizer_collision_duplicates_and_directory_rejection(tmp_path):
    root=workspace(tmp_path);(root/'a').write_text('same');(root/'b').write_text('same');(root/'dir').mkdir()
    assert run(root,'file-organizer','scan')['duplicate_groups']==[['a','b']]
    for moves in [[{'source':'a','target':'same'},{'source':'b','target':'same'}],[{'source':'dir','target':'moved'}],[{'source':'a','target':'z'},{'source':'b','target':'z/nested'}]]:
        assert run(root,'file-organizer','plan-moves',moves=moves).startswith('ERROR:')
    assert (root/'a').exists() and (root/'b').exists()

def test_bundle_import_update_removal_and_local_replacement(tmp_path):
    bundles=tmp_path/'bundles';shutil.copytree(PACKAGES,bundles);e=Extensions(tmp_path/'data');e.sync_bundled(bundles)
    assert len(e.list()['plugins'])==11 and all(not p['enabled'] and p['origin']=='bundled' for p in e.list()['plugins'])
    key='luma-project-overview';e.toggle(key,True,True);e.sync_bundled(bundles)
    assert e.state()['plugins'][key]['enabled']
    p=bundles/key/'plugin.json';m=json.loads(p.read_text(encoding='utf-8'));m['version']='1.0.1';p.write_text(json.dumps(m),encoding='utf-8')
    e.sync_bundled(bundles);assert not e.state()['plugins'][key]['enabled'] and e.state()['plugins'][key]['manifest']['version']=='1.0.1'
    e.uninstall(key);e.sync_bundled(bundles);assert key not in e.state()['plugins']
    key='luma-image-tools';preview=e.inspect(directory=str(bundles/key));e.install(directory=str(bundles/key),expected_digest=preview['digest'])
    e.toggle(key,True,True);e.sync_bundled(bundles);assert e.state()['plugins'][key]['origin']=='local' and e.state()['plugins'][key]['enabled']

def test_bundled_plugins_use_worker_protocol_and_persist_data(tmp_path):
    root=workspace(tmp_path);(root/'file.txt').write_text('hello');Image.new('RGB',(20,10)).save(root/'image.png')
    e=Extensions(tmp_path/'data');e.sync_bundled(PACKAGES)
    for key,tool,args,field in [
        ('luma-project-overview','overview',{},'files'),
        ('luma-document-reader','read-document',{'path':'file.txt'},'items'),
        ('luma-image-tools','transform',{'path':'image.png','output':'copy.webp'},'output'),
        ('luma-file-organizer','scan',{},'duplicate_groups')]:
        e.toggle(key,True,True);request=e.prepare_tool(key,tool,args)
        result=e.execute(request,root,threading.Event());assert field in json.loads(result)
    with pytest.raises(ValueError):e.prepare_tool('luma-image-tools','transform',{'path':'image.png','output':'oops.png','max_width':-1})

@pytest.mark.parametrize('category',['appearance','software'])
def test_future_categories_cannot_execute_code(tmp_path,category):
    folder=tmp_path/'plugin';shutil.copytree(PACKAGES/'luma-image-tools',folder)
    p=folder/'plugin.json';m=json.loads(p.read_text(encoding='utf-8'));m['category']=category;p.write_text(json.dumps(m),encoding='utf-8')
    with pytest.raises(ValueError,match='contribution'):Extensions(tmp_path/'data').inspect(directory=str(folder))
