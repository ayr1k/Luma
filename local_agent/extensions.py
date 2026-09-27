"""Local extension packages and explicit, file-backed skills. No package code runs on import."""
import base64, hashlib, io, json, os, re, shutil, stat, tempfile, time, uuid, zipfile
from pathlib import Path, PurePosixPath
from jsonschema import Draft202012Validator, ValidationError
from .storage import atomic_json

from .contributions import validate_contribution, configuration, schema

VERSION = (0, 7, 2)
MAX_INSTALLED = 100
MAX_ENABLED_CODE = 20
MAX_SELECTED_PLUGINS = 12
ID = re.compile(r'^[a-z][a-z0-9-]{0,39}$')
MAX_PACKAGE = 25 * 1024 * 1024


def identifier(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError('标识只能使用小写字母、数字和短横线，以字母开头，最多 40 字符')
    return value


def relative(value):
    if not isinstance(value, str) or not value or '\\' in value or ':' in value:
        raise ValueError('扩展包含无效路径')
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in {'..', '.'} for x in value.split('/')):
        raise ValueError('扩展路径不能越界')
    if any(x.endswith((' ', '.')) or x.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]} for x in p.parts):
        raise ValueError('扩展包含 Windows 保留路径')
    return p


def bounded(root, path):
    p = root.joinpath(*relative(path).parts)
    root = root.resolve()
    if not p.resolve().is_relative_to(root):
        raise ValueError('扩展文件不能链接到目录之外')
    for ancestor in [p, *p.parents]:
        if ancestor == root:
            break
        if ancestor.is_symlink() or (hasattr(ancestor,'is_junction') and ancestor.is_junction()):
            raise ValueError('扩展不支持符号链接或目录联接')
    return p


def skill_metadata(content, fallback):
    content = content.replace('\r\n', '\n')
    if len(content) > 24000 or not content.strip():
        raise ValueError('SKILL.md 不能为空，最多 24000 字符')
    fields = {'name': fallback, 'description': ''}
    if content.startswith('---\n'):
        header, separator, _ = content[4:].partition('\n---')
        if not separator:
            raise ValueError('Skill front matter 缺少结束标记')
        for line in header.splitlines():
            key, sep, value = line.partition(':')
            if sep and key in {'name','description','author','version','min_luma','max_luma','tested_luma'}:
                fields[key] = value.strip().strip('"\'')[:300]
    for key in ('min_luma','max_luma'):
        if key not in fields:continue
        value=fields[key]
        if not re.fullmatch(r'\d+\.\d+\.\d+',value):raise ValueError('SKILL.md.'+key+'：版本必须为 x.y.z')
        version=tuple(map(int,value.split('.')))
        if key=='min_luma' and VERSION<version or key=='max_luma' and VERSION>version:raise ValueError('Skill 不兼容当前 Luma：'+value)
    return fields


class Extensions:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.base = self.root / 'extensions'
        self.packages = self.base / 'packages'
        self.skills = self.root / 'skills'
        for p in (self.packages, self.skills, self.base/'trash', self.base/'data'):
            p.mkdir(parents=True, exist_ok=True)
        self.bundle_errors = []
        self.registry = self.base / 'registry.json'

    def sync_bundled(self, directory):
        """Import installer-selected bundles once; preserve removals and local replacements."""
        directory=Path(directory)
        if not directory.is_dir():return
        receipts=self.base/'bundled-receipts.json'
        try:
            seen=json.loads(receipts.read_text(encoding='utf-8')) if receipts.exists() else {}
            if not isinstance(seen,dict):raise ValueError('invalid receipt')
        except (ValueError,OSError):
            self.bundle_errors.append({'id':'bundled','error':'预置插件记录无法读取，未自动导入'})
            return
        for folder in sorted(directory.iterdir()):
            if not folder.is_dir():continue
            try:
                preview=self.inspect(directory=str(folder));key=preview['manifest']['id'];digest=preview['digest']
                current=self.state()['plugins'].get(key);last=seen.get(key)
                # Missing after a recorded import means the user uninstalled it.
                if last and current is None:continue
                if current and current.get('origin')!='bundled':continue
                if current:self.verified_files(key,current)
                if current and current['digest']==digest:
                    seen[key]=digest;atomic_json(receipts,seen);continue
                if current and last and current['digest']!=last:continue
                self.install(directory=str(folder),expected_digest=digest,origin='bundled')
                seen[key]=digest;atomic_json(receipts,seen)
            except (ValueError,OSError) as exc:
                self.bundle_errors.append({'id':folder.name,'error':str(exc)[:300]})

    def state(self):
        if not self.registry.exists():
            return {'plugins': {}, 'disabled_skills': []}
        try:
            value = json.loads(self.registry.read_text(encoding='utf-8'))
            if not isinstance(value.get('plugins'),dict) or not isinstance(value.get('disabled_skills'),list):raise ValueError()
            return value
        except (ValueError, TypeError, OSError) as exc:
            raise ValueError('扩展注册表损坏，请恢复 registry.json 备份；未加载任何插件') from exc

    def manifest(self, files):
        try:
            raw = files['plugin.json']
            if len(raw)>32000:raise ValueError('清单过大')
            m = json.loads(raw.decode('utf-8-sig'))
            identifier(m['id'])
            for field in ('author','changelog'):
                if field in m and (not isinstance(m[field],str) or len(m[field])>8000):raise ValueError('plugin.json.'+field+'：必须为文本，最多 8000 字符')
            examples=m.get('examples',[])
            if not isinstance(examples,list) or len(examples)>20 or any(not isinstance(x,str) or len(x)>2000 for x in examples):raise ValueError('plugin.json.examples：最多 20 条文本，每条最多 2000 字符')
            if m.get('category','tools') not in {'tools','appearance','software'}:raise ValueError('未知插件分类')
            if m.get('category','tools') != 'tools':validate_contribution(m)
            elif m.get('contribution'):raise ValueError('工具插件不能声明界面贡献')
            if m.get('api_version') != 1:raise ValueError('插件 API 版本不兼容')
            for key in ('version','name','description'):
                if not isinstance(m.get(key),str) or len(m[key])>500:raise ValueError('清单缺少名称、版本或说明')
            for key, default in [('min_luma','0.6.0'),('max_luma','0.7.99')]:
                value = m.get(key,default)
                if not re.fullmatch(r'\d+\.\d+\.\d+',value):raise ValueError('版本必须为 x.y.z')
                version = tuple(map(int,value.split('.')))
                if key=='min_luma' and VERSION<version or key=='max_luma' and VERSION>version:raise ValueError('此插件不兼容当前 Luma 版本')
            if not re.fullmatch(r'\d+\.\d+\.\d+',m['version']):raise ValueError('插件版本必须为 x.y.z')
            tools=m.get('tools',[]);skills=m.get('skills',[])
            if not isinstance(tools,list) or len(tools)>20 or not isinstance(skills,list) or len(skills)>20:raise ValueError('最多 20 个工具和 20 个 Skill')
            names=set()
            for tool in tools:
                identifier(tool['name'])
                if tool.get('effect','write') not in {'read','write'}:raise ValueError('工具 effect 必须为 read 或 write')
                if tool['name'] in names:raise ValueError('工具名称重复')
                names.add(tool['name'])
                if not isinstance(tool.get('description'),str) or len(tool['description'])>1000:raise ValueError('工具缺少描述')
                schema=tool.get('input_schema',{})
                if schema.get('type')!='object' or len(json.dumps(schema))>12000 or '"$ref"' in json.dumps(schema):raise ValueError('工具参数必须为 object schema，不支持 $ref')
                Draft202012Validator.check_schema(schema)
            if tools:
                if m.get('runtime')!='python' or m.get('permissions')!=['local-code']:raise ValueError('代码插件须声明 python runtime 与 local-code 权限')
                entry=str(relative(m['entrypoint']))
                if not entry.endswith('.py') or entry not in files:raise ValueError('缺少 Python 入口文件')
            elif m.get('permissions',[]) or m.get('entrypoint'):
                raise ValueError('无工具插件不能声明代码入口或权限')
            seen=set()
            for name in skills:
                identifier(name)
                if name in seen:raise ValueError('Skill 名称重复')
                seen.add(name)
                skill_metadata(files[f'skills/{name}/SKILL.md'].decode('utf-8-sig'),name)
            if not tools and not skills and not m.get('contribution'):raise ValueError('插件至少提供一个工具或 Skill')
            return m
        except (KeyError,TypeError,UnicodeError,json.JSONDecodeError) as exc:
            raise ValueError('插件清单或 Skill 文件无效') from exc
        except Exception as exc:
            if isinstance(exc,ValueError):raise
            raise ValueError('插件参数 schema 无效') from exc

    def package_files(self, data=None, directory=None):
        files={};seen=set();total=0
        def add(name,value):
            nonlocal total
            name=str(relative(name));fold=name.casefold()
            if fold in seen:raise ValueError('包内路径重复（不区分大小写）')
            if Path(name).name.casefold()=='.env':raise ValueError('插件包不能包含 .env 密钥文件')
            seen.add(fold);total+=len(value)
            if total>MAX_PACKAGE or len(value)>10*1024*1024 or len(files)>=500:raise ValueError('包过大：最多 500 个文件、总计 25 MB')
            files[name]=value
        if directory:
            root=Path(directory).resolve()
            if not root.is_dir():raise ValueError('开发目录不存在')
            for base,dirs,names in os.walk(root,followlinks=False):
                for name in dirs+names:
                    path=Path(base)/name
                    if path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction()):raise ValueError('不能导入链接')
                dirs[:]=[x for x in dirs if x not in {'.git','__pycache__','.venv','node_modules'}]
                for name in names:
                    path=Path(base)/name
                    if path.stat().st_size>10*1024*1024:raise ValueError('文件过大')
                    add(path.relative_to(root).as_posix(),path.read_bytes())
        else:
            try:
                raw=base64.b64decode(data or '',validate=True)
                if len(raw)>8*1024*1024:raise ValueError('ZIP 最大 8 MB')
                with zipfile.ZipFile(io.BytesIO(raw)) as z:
                    if len(z.infolist())>600:raise ValueError('包内文件过多')
                    for info in z.infolist():
                        relative(info.filename.rstrip('/'))
                        if stat.S_ISLNK(info.external_attr>>16):raise ValueError('ZIP 不能包含链接')
                        if info.is_dir():continue
                        if info.file_size>10*1024*1024 or total+info.file_size>MAX_PACKAGE:raise ValueError('解压内容过大')
                        add(info.filename,z.read(info))
            except (zipfile.BadZipFile,RuntimeError,UnicodeError) as exc:
                raise ValueError('ZIP 无效或已加密') from exc
        return files

    @staticmethod
    def digest(files):
        h=hashlib.sha256()
        for name,data in sorted(files.items()):
            h.update(name.encode());h.update(b'\0');h.update(hashlib.sha256(data).digest())
        return h.hexdigest()

    def inspect(self, data=None, directory=None):
        files=self.package_files(data,directory);m=self.manifest(files)
        return {'manifest':m,'digest':self.digest(files),'file_count':len(files),'requires_trust':bool(m.get('tools'))}

    def install(self, data=None, directory=None, expected_digest=None, origin="local"):
        files=self.package_files(data,directory);m=self.manifest(files);digest=self.digest(files)
        if expected_digest!=digest:raise ValueError('插件内容已变化，请重新预览确认')
        state=self.state();key=m['id'];target=self.packages/key
        if key not in state['plugins'] and len(state['plugins'])>=MAX_INSTALLED:raise ValueError('最多安装 100 个插件')
        if target.is_symlink() or (hasattr(target,'is_junction') and target.is_junction()):raise ValueError('安装目录不能为链接')
        stage=self.base/('stage-'+uuid.uuid4().hex);stage.mkdir()
        backup=None
        try:
            for name,content in files.items():
                p=bounded(stage,name);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(content)
            if target.exists():
                backup=self.base/'trash'/(key+'-'+uuid.uuid4().hex);target.rename(backup)
            stage.rename(target)
            previous=state['plugins'].get(key,{}).get('config',{})
            try: config=configuration(m,previous) if m.get('contribution') else {}
            except ValueError: config=configuration(m)
            state['plugins'][key]={'config':config,'enabled':False,'trusted':False,'digest':digest,'manifest':m,'origin':origin}
            try:atomic_json(self.registry,state)
            except Exception:
                target.rename(stage)
                if backup:backup.rename(target);backup=None
                raise
        except Exception:
            if backup and not target.exists():
                backup.rename(target)
            raise
        finally:
            if stage.exists():
                # Only remove our exact generated staging directory within managed base.
                if stage.resolve().parent!=self.base.resolve():raise ValueError('无效暂存目录')
                shutil.rmtree(stage)
        return {'id':key,'enabled':False,'updated':backup is not None}

    def toggle(self,key,enabled,trusted=False):
        state=self.state()
        if key.startswith('user:') or key.startswith('plugin:'):
            if key not in {x['id'] for x in self.list()['skills']}:raise ValueError('Skill 不存在')
            disabled=set(state['disabled_skills'])
            disabled.discard(key) if enabled else disabled.add(key)
            state['disabled_skills']=sorted(disabled)
        else:
            identifier(key);row=state['plugins'].get(key)
            if row is None:raise ValueError('插件不存在')
            if enabled:
                if sum(bool(p.get('enabled') and p['manifest'].get('tools')) for k,p in state['plugins'].items() if k!=key)>=MAX_ENABLED_CODE and row['manifest'].get('tools'):raise ValueError('最多同时启用 20 个代码插件')
                self.verified_files(key,row)
                if row['manifest'].get('tools') and not trusted:raise ValueError('启用代码插件需明确确认信任：它不是操作系统沙箱')
            if enabled and row['manifest'].get('contribution'):
                slot=row['manifest']['contribution']['slot']
                for other in state['plugins'].values():
                    if other['manifest'].get('contribution',{}).get('slot')==slot:other['enabled']=False
            row.update(enabled=enabled,trusted=bool(enabled and trusted))
        atomic_json(self.registry,state)

    def verified_files(self,key,row=None):
        identifier(key);row=row or self.state()['plugins'].get(key)
        if row is None:raise ValueError('插件不存在')
        root=bounded(self.packages,key)
        files=self.package_files(directory=str(root))
        if self.digest(files)!=row['digest']:raise ValueError('插件内容已修改，请重新导入并确认信任')
        self.manifest(files)
        return files

    def uninstall(self,key):
        identifier(key);state=self.state()
        if key not in state['plugins']:raise ValueError('插件不存在')
        target=bounded(self.packages,key);backup=self.base/'trash'/(key+'-'+uuid.uuid4().hex)
        if target.exists():target.rename(backup)
        old=state['plugins'].pop(key)
        try:atomic_json(self.registry,state)
        except Exception:
            if backup.exists():backup.rename(target)
            raise
        return {'retained_data':str(self.base/'data'/key)}

    def list(self):
        state=self.state();plugins=[];skills=[];errors=list(self.bundle_errors)
        for directory in sorted(self.skills.iterdir()):
            if not directory.is_dir():continue
            try:
                identifier(directory.name);p=bounded(self.skills,directory.name+'/SKILL.md')
                if p.stat().st_size>96000:raise ValueError('Skill 文件过大')
                content=p.read_text(encoding='utf-8-sig');key='user:'+directory.name
                skills.append(dict(id=key,**skill_metadata(content,directory.name),enabled=key not in state['disabled_skills'],editable=True))
            except (ValueError,OSError,UnicodeError) as exc:errors.append({'id':directory.name,'error':str(exc)[:300]})
        for key,row in state['plugins'].items():
            m=row['manifest'];error=None
            try:files=self.verified_files(key,row)
            except (ValueError,OSError) as exc:files={};error=str(exc)
            config={};config_schema=None
            if m.get('contribution'):
                try:config=configuration(m,row.get('config'));config_schema=schema(m)
                except ValueError as exc:error='配置无效：'+str(exc)[:500]
            active=row['enabled'] and error is None
            plugins.append(dict(contribution=m.get('contribution'),config=config,config_schema=config_schema,origin=row.get('origin','local'),category=m.get('category','tools'),id=key,name=m['name'],version=m['version'],description=m['description'],enabled=active,requires_trust=bool(m.get('tools')),tools=m.get('tools',[]),permissions=m.get('permissions',[]),error=error))
            for name in m.get('skills',[]):
                sid=f'plugin:{key}:{name}'
                try:meta=skill_metadata(files[f'skills/{name}/SKILL.md'].decode('utf-8-sig'),name)
                except (KeyError,ValueError,UnicodeError):continue
                skills.append(dict(id=sid,**meta,enabled=active and sid not in state['disabled_skills'],plugin_enabled=active,plugin_name=m['name'],editable=False))
        return dict(plugins=plugins,skills=skills,errors=errors,skills_directory=str(self.skills),limits=dict(installed=MAX_INSTALLED,enabled_code=MAX_ENABLED_CODE,selected_plugins=MAX_SELECTED_PLUGINS))

    def skill_root(self,key):
        parts=key.split(':')
        if len(parts)==2 and parts[0]=='user':
            return bounded(self.skills,identifier(parts[1]))
        if len(parts)==3 and parts[0]=='plugin':
            plugin,name=identifier(parts[1]),identifier(parts[2]);row=self.state()['plugins'].get(plugin)
            if not row or name not in row['manifest'].get('skills',[]):raise ValueError('Skill 不存在')
            self.verified_files(plugin,row)
            return bounded(self.packages,plugin+'/skills/'+name)
        raise ValueError('Skill ID 无效')

    def read_skill(self,key):
        path=bounded(self.skill_root(key),'SKILL.md')
        if path.stat().st_size>96000:raise ValueError('Skill 文件过大')
        content=path.read_text(encoding='utf-8-sig');skill_metadata(content,key)
        return {'id':key,'content':content,'editable':key.startswith('user:')}

    def save_skill(self,name,content):
        identifier(name);skill_metadata(content,name)
        path=bounded(self.skills,name+'/SKILL.md');path.parent.mkdir(parents=True,exist_ok=True)
        temp=path.with_name('SKILL.md.'+uuid.uuid4().hex+'.tmp')
        temp.write_text(content,encoding='utf-8');os.replace(temp,path)
        return {'id':'user:'+name}

    def delete_skill(self,key):
        if not key.startswith('user:'):raise ValueError('插件 Skill 请通过卸载插件移除')
        source=self.skill_root(key)
        source.rename(self.base/'trash'/('skill-'+source.name+'-'+uuid.uuid4().hex))

    def selected(self,keys):
        if len(keys)>8 or len(set(keys))!=len(keys):raise ValueError('最多选择 8 个不同 Skill')
        available={row['id']:row for row in self.list()['skills'] if row['enabled']}
        result=[];total=0
        for key in keys:
            if key not in available:raise ValueError('Skill 已禁用、移除或不可用：'+key)
            content=self.read_skill(key)['content'];total+=len(content)
            if total>48000:raise ValueError('所选 Skill 内容合计超过 48000 字符')
            result.append({'id':key,'name':available[key]['name'],'content':content})
        return result

    def reference(self,active,key,path):
        if key not in {s['id'] for s in active}:raise ValueError('只能读取本轮已选择 Skill 的参考资料')
        self.selected([key])
        rel=relative(path)
        if rel.parts[0] not in {'references','templates'}:raise ValueError('只允许 references/ 或 templates/ 内的 UTF-8 文本')
        p=bounded(self.skill_root(key),path)
        if p.stat().st_size>64000:raise ValueError('参考文件最大 64 KB')
        try:return p.read_text(encoding='utf-8')
        except UnicodeError as exc:raise ValueError('参考资料须为 UTF-8 文本') from exc

    def configure(self,key,values):
        identifier(key);state=self.state();row=state['plugins'].get(key)
        if not row:raise ValueError('插件不存在')
        self.verified_files(key,row)
        row['config']=configuration(row['manifest'],values)
        atomic_json(self.registry,state)
        return row['config']

    def reset_appearance(self):
        state=self.state()
        for row in state['plugins'].values():
            if row['manifest'].get('category')=='appearance':row['enabled']=False
        atomic_json(self.registry,state)

    def selected_plugins(self,keys):
        if len(keys)>MAX_SELECTED_PLUGINS or len(set(keys))!=len(keys):raise ValueError('最多选择 12 个不同工具插件')
        available={p['id']:p for p in self.list()['plugins'] if p['enabled'] and p['tools']}
        for key in keys:
            if key not in available:raise ValueError('工具插件已禁用、移除或不可用：'+key)
        return list(keys)

    def catalog(self,keys=None):
        rows=[]
        for p in self.list()['plugins']:
            if p['enabled'] and (keys is None or p['id'] in keys):
                for t in p['tools']:rows.append({'plugin':p['id'],**t})
        return rows

    def prepare_tool(self,plugin,tool,args):
        identifier(plugin);identifier(tool);state=self.state();row=state['plugins'].get(plugin)
        if not row or not row['enabled'] or not row['trusted']:raise ValueError('代码插件尚未启用并信任')
        self.verified_files(plugin,row)
        spec=next((t for t in row['manifest'].get('tools',[]) if t['name']==tool),None)
        if not spec:raise ValueError('插件工具不存在')
        try:Draft202012Validator(spec['input_schema']).validate(args)
        except ValidationError as exc:raise ValueError('插件参数不符合声明的 schema') from exc
        if len(json.dumps(args))>100000:raise ValueError('插件参数过大')
        return dict(plugin=plugin,tool=tool,input=args,digest=row['digest'],entrypoint=row['manifest']['entrypoint'])

    def execute(self,request,workspace,cancel_event):
        from .plugin_worker import run_plugin
        now=self.prepare_tool(request['plugin'],request['tool'],request['input'])
        if now!=request:raise ValueError('审批之后插件内容变化，请重新发起调用')
        data=self.base/'data'/request['plugin'];data.mkdir(parents=True,exist_ok=True)
        return run_plugin(bounded(self.packages,request['plugin']+'/'+request['entrypoint']),request,workspace,data,cancel_event)

    def details(self,key):
        identifier(key);row=self.state()['plugins'].get(key)
        if not row:raise ValueError('插件不存在')
        m=row['manifest']
        return dict(id=key,name=m['name'],version=m['version'],author=m.get('author','作者未提供'),
            description=m['description'],examples=m.get('examples',[]),changelog=m.get('changelog','作者未提供更新说明'),
            tools=m.get('tools',[]),skills=m.get('skills',[]),contribution=m.get('contribution'),
            tested_luma=m.get('tested_luma','未声明'),compatibility={'min':m.get('min_luma','0.6.0'),'max':m.get('max_luma','0.7.99')},permissions=m.get('permissions',[]))

    def diagnose(self):
        listing=self.list();rows=[]
        for p in listing['plugins']:
            if p['error']:status='不可用';reason=p['error'];fix='修正包后重新导入，并重新确认启用。'
            elif not p['enabled']:status='未启用';reason='尚未启用，或同类外观/软件功能插件已替换它。';fix='在扩展中心启用；代码插件需要确认信任。'
            elif p['tools']:status='可用';reason='需在 Work 模式使用 $ 选择，每次调用仍需审批。';fix='检查本轮标签和运行模式。'
            else:status='可用';reason='已启用。';fix='软件功能的系统状态见下方桌面诊断。'
            rows.append(dict(id=p['id'],name=p['name'],status=status,reason=reason,suggestion=fix))
        for s in listing['skills']:
            rows.append(dict(id=s['id'],name=s['name'],status='可用' if s['enabled'] else '未启用',reason='已启用，可用 / 选择。' if s['enabled'] else 'Skill 或所属插件未启用。',suggestion='在 Skills 列表检查启用状态。'))
        return {'items':rows,'errors':listing['errors']}

    def export_config(self):
        # Only declared host settings, never credentials, executable files or trust flags.
        rows=[]
        for p in self.list()['plugins']:
            if p['contribution'] and not p['error']:
                rows.append({'id':p['id'],'slot':p['contribution']['slot'],'version':p['version'],'config':p['config']})
        return {'format':'luma-extension-settings','version':1,'plugins':rows}

    def import_config(self,document,apply=False):
        if not isinstance(document,dict) or set(document)!={'format','version','plugins'} or document.get('format')!='luma-extension-settings' or type(document.get('version')) is not int or document['version']!=1:
            raise ValueError('配置文件格式或版本无效')
        entries=document['plugins']
        if not isinstance(entries,list) or len(entries)>MAX_INSTALLED or len(json.dumps(document))>1000000:raise ValueError('配置文件过大或 plugins 格式无效')
        state=self.state();changes=[];skipped=[];seen=set()
        for i,item in enumerate(entries):
            prefix=f'plugins[{i}]'
            if not isinstance(item,dict) or set(item)!={'id','slot','version','config'}:raise ValueError(prefix+'：字段无效')
            key=identifier(item['id'])
            if key in seen:raise ValueError(prefix+'.id：重复')
            seen.add(key);row=state['plugins'].get(key)
            if not row:skipped.append({'id':key,'reason':'未安装，跳过'});continue
            self.verified_files(key,row);m=row['manifest']
            if not m.get('contribution') or item['slot']!=m['contribution']['slot']:raise ValueError(prefix+'.slot：贡献类型不匹配')
            if not isinstance(item['config'],dict):raise ValueError(prefix+'.config：必须为对象')
            try:values=configuration(m,item['config'])
            except ValueError as exc:raise ValueError(prefix+'.config：'+str(exc)) from exc
            changes.append({'id':key,'name':m['name'],'config':values,'version_changed':item['version']!=m['version']})
        if apply:
            for change in changes:state['plugins'][change['id']]['config']=change['config']
            atomic_json(self.registry,state)
        return {'changes':changes,'skipped':skipped,'applied':apply}

    def validate_package(self,data=None,directory=None):
        from .extension_check import check_files
        try:files=self.package_files(data,directory)
        except (ValueError,OSError) as exc:return {'ok':False,'issues':[{'path':'package','message':str(exc)}],'warnings':[]}
        return check_files(self,files)
