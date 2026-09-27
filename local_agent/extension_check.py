"""Static extension inspection. Never imports or executes package code."""
import ast,json
from jsonschema import Draft202012Validator
from .contributions import validate_contribution

def check_files(manager,files):
    issues=[];warnings=[]
    def issue(path,message):issues.append({'path':path,'message':str(message)[:1200]})
    try:m=json.loads(files['plugin.json'].decode('utf-8-sig'))
    except json.JSONDecodeError as exc:
        issue(f'plugin.json:{exc.lineno}:{exc.colno}',exc.msg);return {'ok':False,'issues':issues,'warnings':warnings}
    except (KeyError,UnicodeError) as exc:
        issue('plugin.json',exc);return {'ok':False,'issues':issues,'warnings':warnings}
    if not isinstance(m,dict):
        issue('plugin.json','根节点必须为对象');return {'ok':False,'issues':issues,'warnings':warnings}
    from .extensions import identifier,relative
    for key in ('name','description','version'):
        if not isinstance(m.get(key),str) or not m.get(key):issue('plugin.json.'+key,'缺少非空文本')
    try:identifier(m.get('id'))
    except ValueError as exc:issue('plugin.json.id',exc)
    if m.get('api_version')!=1:issue('plugin.json.api_version','当前只支持 API 1')
    if m.get('tools'):
        entry=m.get('entrypoint')
        try:
            relative(entry)
            if entry not in files:issue('plugin.json.entrypoint','入口文件不存在：'+entry)
        except ValueError as exc:issue('plugin.json.entrypoint',exc)
    for key in ('author','changelog'):
        if key in m and (not isinstance(m[key],str) or len(m[key])>8000):issue('plugin.json.'+key,'必须为文本，最多 8000 字符')
        elif not m.get(key):warnings.append({'path':'plugin.json.'+key,'message':'建议补充详情页信息'})
    examples=m.get('examples',[])
    if not isinstance(examples,list) or len(examples)>20 or any(not isinstance(x,str) or len(x)>2000 for x in examples):issue('plugin.json.examples','必须为最多 20 条文本，每条最多 2000 字符')
    tools=m.get('tools',[])
    if isinstance(tools,list):
        for i,t in enumerate(tools):
            path=f'plugin.json.tools[{i}]'
            if not isinstance(t,dict):issue(path,'必须为对象');continue
            for field in ('name','description'):
                if not isinstance(t.get(field),str) or not t.get(field):issue(path+'.'+field,'缺少非空文本')
            try:Draft202012Validator.check_schema(t.get('input_schema',{}))
            except Exception as exc:issue(path+'.input_schema.'+'.'.join(map(str,getattr(exc,'path',[]))),getattr(exc,'message',str(exc)))
            if not isinstance(t.get('input_schema',{}),dict) or t.get('input_schema',{}).get('type')!='object':issue(path+'.input_schema.type','必须为 object')
    if m.get('contribution'):
        try:validate_contribution(m)
        except ValueError as exc:
            if hasattr(exc,'errors'):
                for e in exc.errors():issue('plugin.json.contribution.defaults.'+'.'.join(map(str,e['loc'])),e['msg'])
            else:issue('plugin.json.contribution',exc)
    if isinstance(m.get('skills',[]),list):
        for i,name in enumerate(m.get('skills',[])):
            path=f'skills/{name}/SKILL.md'
            if path not in files:issue('plugin.json.skills['+str(i)+']','缺少 '+path)
    for path,content in files.items():
        if path.endswith('.py'):
            try:ast.parse(content,filename=path)
            except SyntaxError as exc:issue(f'{path}:{exc.lineno}:{exc.offset}',exc.msg)
            except Exception as exc:issue(path,exc)
    try:manager.manifest(files)
    except (ValueError,AttributeError) as exc:issue('plugin.json',exc)
    return {'ok':not issues,'issues':issues,'warnings':warnings,'file_count':len(files),'digest':manager.digest(files)}
