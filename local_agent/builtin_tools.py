"""Bounded local operations used by Luma's four optional bundled plugins."""
import hashlib, io, json, os, shutil, uuid, warnings, zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree
from PIL import Image, ImageOps
from pypdf import PdfReader
from .extensions import bounded
from .storage import atomic_json

IGNORE={'.git','.venv','venv','node_modules','__pycache__','.cache','dist','build'}
MAX_FILE=50*1024*1024

def path_in(root,value,root_ok=False):
    if not isinstance(value,str) or len(value)>1000:raise ValueError('文件路径无效')
    if root_ok and value in {'.',''}:return root.resolve()
    return bounded(root,value.replace('\\','/'))

def file_in(root,value):
    p=path_in(root,value)
    if not p.is_file():raise ValueError('文件不存在：'+value)
    if p.stat().st_size>MAX_FILE:raise ValueError('单文件不能超过 50 MB')
    return p

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def walk(root,directory='.',depth=4):
    start=path_in(root,directory,True)
    if not start.is_dir():raise ValueError('请选择项目内的目录')
    pending=[(start,0)];files=[];tree=[];seen=0;skipped=0;limited=False
    while pending and seen<5000:
        folder,level=pending.pop()
        with os.scandir(folder) as entries:
            for entry in entries:
                seen+=1
                if seen>5000:limited=True;break
                p=Path(entry.path)
                if entry.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()):skipped+=1;continue
                if entry.name in IGNORE:skipped+=1;continue
                try:
                    p=path_in(root,p.relative_to(root).as_posix())
                    is_dir=p.is_dir();rel=p.relative_to(root).as_posix()
                    if len(tree)<300:tree.append(rel+('/' if is_dir else ''))
                    if is_dir:
                        if level<depth:pending.append((p,level+1))
                        else:limited=True
                    elif p.is_file():files.append(p)
                except OSError:skipped+=1
    return files,dict(tree=sorted(tree),visited=min(seen,5000),skipped=skipped,limited=limited or bool(pending) or len(files)>300,max_depth=depth)

def project_overview(root,args):
    files,info=walk(root,args.get('directory','.'),args.get('depth',4))
    kinds=Counter(p.suffix.lower() or '(无扩展名)' for p in files)
    known={'pyproject.toml','requirements.txt','package.json','Cargo.toml','go.mod','pom.xml','CMakeLists.txt'}
    return dict(**info,files=len(files),file_types=dict(kinds.most_common(40)),configuration_files=[p.relative_to(root).as_posix() for p in files if p.name in known][:50],scope='仅统计展示的扫描范围；忽略依赖、缓存、链接和构建目录。')

def read_document(root,args):
    p=file_in(root,args['path']);ext=p.suffix.lower();start=args.get('start',1);count=args.get('count',20)
    if ext=='.pdf':
        reader=PdfReader(p)
        if reader.is_encrypted:raise ValueError('暂不读取加密 PDF')
        total=len(reader.pages);unit='页';count=min(count,10)
        values=[(i+1,reader.pages[i].extract_text() or '') for i in range(start-1,min(start-1+count,total))]
    elif ext=='.docx':
        with zipfile.ZipFile(p) as z:
            if len(z.infolist())>3000:raise ValueError('DOCX 包内容过多')
            info=z.getinfo('word/document.xml')
            if info.file_size>10*1024*1024:raise ValueError('DOCX 正文过大')
            raw=z.read(info)
            if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise ValueError('不支持含实体定义的文档')
            doc=ElementTree.fromstring(raw)
        ns='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        paragraphs=[''.join(n.text or '' for n in para.iter(ns+'t')) for para in doc.iter(ns+'p')]
        total=len(paragraphs);unit='段';values=list(enumerate(paragraphs[start-1:start-1+count],start))
    elif ext in {'.txt','.md','.csv','.json','.log','.yaml','.yml','.toml','.rst'}:
        if p.stat().st_size>5*1024*1024:raise ValueError('文本文件上限 5 MB')
        lines=p.read_text(encoding='utf-8-sig').splitlines();total=len(lines);unit='行';values=list(enumerate(lines[start-1:start-1+count],start))
    else:raise ValueError('支持 PDF、DOCX 和 UTF-8 文本；扫描 PDF 不含 OCR')
    remaining=20000;output=[];query=args.get('query','').casefold();truncated=False
    for number,text in values:
        if query and query not in text.casefold():continue
        if len(text)>remaining:truncated=True
        output.append({'number':number,'text':text[:remaining]});remaining-=min(len(text),remaining)
        if remaining<=0:break
    return dict(path=args['path'],unit=unit,total=total,start=start,count=len(values),items=output,truncated=truncated,query_scope='关键词仅筛选本次读取范围',note='PDF 只提取文本层；复杂排版及 DOCX 图片未提取。')

def image_tool(root,tool,args):
    p=file_in(root,args['path'])
    with warnings.catch_warnings():
        warnings.simplefilter('error',Image.DecompressionBombWarning)
        with Image.open(p) as image:
            if image.width*image.height>40_000_000:raise ValueError('图片上限 4000 万像素')
            if tool=='inspect':return dict(path=args['path'],width=image.width,height=image.height,format=image.format,mode=image.mode,frames=getattr(image,'n_frames',1))
            target=path_in(root,args['output']);suffix=target.suffix.lower()
            formats={'.jpg':'JPEG','.jpeg':'JPEG','.png':'PNG','.webp':'WEBP'}
            if suffix not in formats:raise ValueError('输出格式须为 JPG、PNG 或 WebP')
            if target.exists():raise ValueError('输出文件已存在，不会覆盖')
            if getattr(image,'n_frames',1)>1:raise ValueError('多帧或动画图片暂不转换，避免丢失帧')
            result=ImageOps.exif_transpose(image)
            result.thumbnail((args.get('max_width',2048),args.get('max_height',2048)),Image.Resampling.LANCZOS)
            if formats[suffix]=='JPEG':
                if 'A' in result.getbands() or 'transparency' in result.info:
                    rgba=result.convert('RGBA');rgb=Image.new('RGB',rgba.size,'white');rgb.paste(rgba,mask=rgba.getchannel('A'));result=rgb
                else:result=result.convert('RGB')
            elif result.mode not in {'RGB','RGBA','L','LA','P'}:result=result.convert('RGBA')
            # Output deliberately omits EXIF/GPS and other source metadata.
            result.info.clear();data=io.BytesIO();result.save(data,format=formats[suffix],quality=args.get('quality',85))
            if data.tell()>MAX_FILE:raise ValueError('输出文件过大')
            target.parent.mkdir(parents=True,exist_ok=True)
            path_in(root,args['output'])
            with target.open('xb') as f:f.write(data.getvalue())
            return dict(output=target.relative_to(root).as_posix(),width=result.width,height=result.height,bytes=data.tell(),metadata='未复制 EXIF/GPS，保留原文件')

def validated_moves(root,moves):
    if not isinstance(moves,list) or not 1<=len(moves)<=50:raise ValueError('每批需要 1—50 个文件')
    sources=set();targets=set();result=[];total=0
    for move in moves:
        source=file_in(root,move['source']);target=path_in(root,move['target'])
        sr=source.relative_to(root).as_posix();tr=target.relative_to(root).as_posix()
        if target.exists() or sr.casefold()==tr.casefold():raise ValueError('目标已存在或路径未改变：'+tr)
        if sr.casefold() in sources or tr.casefold() in targets:raise ValueError('重复的源文件或目标文件')
        sources.add(sr.casefold());targets.add(tr.casefold());total+=source.stat().st_size
        if total>200*1024*1024:raise ValueError('每批文件合计上限 200 MB')
        for parent in target.parents:
            if parent==root:break
            if parent.exists() and not parent.is_dir():raise ValueError('目标父目录不是文件夹')
        result.append(dict(source=sr,target=tr,sha256=digest(source)))
    if sources & targets:raise ValueError('不支持循环或链式重命名，请拆成独立批次')
    # One target cannot also be another target's parent.
    for a in targets:
        if any(b.startswith(a+'/') for b in targets):raise ValueError('目标文件和目录路径冲突')
    return result

def organize(root,data,tool,args):
    data.mkdir(parents=True,exist_ok=True)
    if tool=='scan':
        files,info=walk(root,args.get('directory','.'),args.get('depth',3));groups={};budget=0
        for p in files:
            size=p.stat().st_size
            if size>20*1024*1024 or budget+size>200*1024*1024:continue
            budget+=size;key=digest(p);groups.setdefault(key,[]).append(p.relative_to(root).as_posix())
        return dict(**info,duplicate_groups=[v for v in groups.values() if len(v)>1][:50],hashed_bytes=budget,note='重复检查仅覆盖单文件不超过 20 MB、累计不超过 200 MB 的扫描文件；不会删除文件。')
    if tool=='plan-moves':
        moves=validated_moves(root,args['moves']);key=uuid.uuid4().hex
        plan=dict(id=key,workspace=str(root),status='planned',moves=moves,completed=[])
        atomic_json(data/(key+'.json'),plan)
        return dict(plan_id=key,moves=[{k:m[k] for k in ('source','target')} for m in moves],next='向用户展示清单；调用 apply-moves 时提交 plan_id 和完整 moves，等待再次审批。')
    key=args['plan_id']
    if not isinstance(key,str) or len(key)!=32 or any(c not in '0123456789abcdef' for c in key):raise ValueError('整理计划 ID 无效')
    plan_path=data/(key+'.json');plan=json.loads(plan_path.read_text(encoding='utf-8'))
    if plan['workspace']!=str(root) or plan['status']!='planned':raise ValueError('计划不属于本项目或已经执行；不会重复执行')
    expected=[{k:m[k] for k in ('source','target')} for m in plan['moves']]
    if args['moves']!=expected:raise ValueError('审批清单与保存的计划不一致')
    if validated_moves(root,args['moves'])!=plan['moves']:raise ValueError('文件在制定计划后发生变化，请重新规划')
    plan['status']='applying';atomic_json(plan_path,plan)
    try:
        for move in plan['moves']:
            source=file_in(root,move['source']);target=path_in(root,move['target']);target.parent.mkdir(parents=True,exist_ok=True)
            path_in(root,move['target'])
            if digest(source)!=move['sha256']:raise ValueError('源文件已变化')
            # Exclusive creation prevents overwriting an existing destination. Keep source until verified.
            with source.open('rb') as f,target.open('xb') as g:shutil.copyfileobj(f,g)
            if digest(target)!=move['sha256'] or digest(source)!=move['sha256']:raise ValueError('复制后校验失败，源文件保留')
            shutil.copystat(source,target,follow_symlinks=False)
            source.unlink();plan['completed'].append(move);atomic_json(plan_path,plan)
        plan['status']='completed';atomic_json(plan_path,plan)
    except Exception:
        plan['status']='partial';atomic_json(plan_path,plan)
        raise ValueError('部分操作未完成；请检查源文件和目标文件，操作记录保留在插件数据目录。不要重复执行旧计划。')
    return dict(plan_id=key,status='completed',moved=len(plan['completed']),record=str(plan_path),note='未删除重复文件；本插件移动不纳入 Luma 自动撤销。')

def dispatch(plugin,request):
    root=Path(request['workspace']).resolve();args=request['input'];tool=request['tool']
    try:
        if plugin=='luma-project-overview' and tool=='overview':value=project_overview(root,args)
        elif plugin=='luma-document-reader' and tool=='read-document':value=read_document(root,args)
        elif plugin=='luma-image-tools' and tool in {'inspect','transform'}:value=image_tool(root,tool,args)
        elif plugin=='luma-file-organizer' and tool in {'scan','plan-moves','apply-moves'}:value=organize(root,Path(request['data_directory']),tool,args)
        else:raise ValueError('未知预置工具')
        text=json.dumps(value,ensure_ascii=False)
        if len(text)>60000:text=json.dumps({'truncated':True,'preview':text[:58000]},ensure_ascii=False)
        return {'text':text}
    except Exception as exc:
        return {'text':'ERROR: '+(str(exc)[:500] if isinstance(exc,(ValueError,OSError)) else type(exc).__name__)}
