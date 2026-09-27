"""Single-process, loopback-only client API. Never expose this port on the LAN."""
import secrets
import copy
import threading
from contextlib import contextmanager, asynccontextmanager
import asyncio
from fastapi import FastAPI, Depends, HTTPException, Request, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.exceptions import RequestValidationError
from .config import Settings
from .core import AgentCore
from .model import LANModel
from .storage import Store, empty_session
from .schemas import ProjectCreate, Project, MessageCreate, MessageRevision, Approval, Session, ConnectionRequest, Configuration, TaskState, ModelSelection
from .lease import DataLease
from .tasks import Tasks
from .preferences import Preferences, load_preferences, save_preferences
from .files import agent_diff_for_file, get_git_diff, get_git_status, list_workspace_files, read_file_preview
from pathlib import Path

def create_app(settings=None, model=None, on_task_done=None):
    settings = settings or Settings.load()
    if len(settings.local_token) < 32 or settings.local_token.startswith('replace-'):
        raise ValueError('AGENT_LOCAL_TOKEN must contain at least 32 characters; generate with secrets.token_urlsafe(32)')
    preferences = load_preferences(settings.data_dir)
    remember_selection = True
    store = Store(settings.data_dir)
    from .extensions import Extensions
    extensions = Extensions(settings.data_dir)
    model = model or LANModel(settings)
    @asynccontextmanager
    async def lifespan(app):
        with DataLease(settings.data_dir):
            import sys
            if getattr(sys, 'frozen', False):
                extensions.sync_bundled(Path(sys.executable).parent / 'Bundled-Plugins')
                from .bundled_skills import sync_skills
                sync_skills(extensions,Path(sys.executable).parent / 'Preset-Skills')
            try:
                yield
            finally:
                await asyncio.to_thread(tasks.shutdown)

    app = FastAPI(title='Local Agent Client API', version='0.7.2', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    bearer = HTTPBearer(auto_error=False)
    lock = threading.Lock()

    def auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not secrets.compare_digest(credentials.credentials, settings.local_token):
            raise HTTPException(401, 'Invalid local client token')

    @app.middleware('http')
    async def local_only(request: Request, call_next):
        from starlette.responses import JSONResponse
        # Host check blocks DNS rebinding. No browser-origin clients in this phase.
        if request.url.hostname not in {'127.0.0.1', 'localhost', '::1'} or request.headers.get('origin'):
            return JSONResponse({'detail': 'Local native clients only'}, status_code=403)
        return await call_next(request)

    @contextmanager
    def exclusive():
        if not lock.acquire(blocking=False):
            raise HTTPException(409, 'Another operation is running; retry after it completes')
        try:
            yield
        finally:
            lock.release()

    def core(project_id):
        project = store.project(project_id)
        if project is None:
            raise HTTPException(404, 'Unknown project')
        if not Path(project['path']).is_dir():
            raise HTTPException(409, 'Project directory is unavailable')
        state = store.load_project(project)
        original=copy.deepcopy(state)
        if state['status'] == 'running':
            state['status'] = 'interrupted'
        options = Preferences.model_validate(state.get('execution_options', preferences.model_dump())) if state.get('pending_command') else preferences
        execution_model = LANModel(settings, options) if isinstance(model, LANModel) else model
        engine = AgentCore(state, execution_model, store.save, options=options, extensions=extensions)
        if state.get('pending_command'):
            state['status'] = 'waiting_approval'
        if state!=original:engine.persist()
        return engine

    def no_sibling_pending(project_id):
        current=store.project(project_id)
        if current is None:raise HTTPException(404,'Unknown project')
        for p in store.projects():
            if p['id']!=project_id and p['group_id']==current['group_id'] and store.load_project(p).get('pending_command'):
                raise HTTPException(409,'同一项目的其他任务正在等待审批，请先处理')

    tasks = Tasks(lock, core, store, on_task_done)
    app.state.tasks = tasks

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        from starlette.responses import JSONResponse
        return JSONResponse({'detail': str(exc)}, status_code=409)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        from starlette.responses import JSONResponse
        return JSONResponse({'detail': [{'loc': list(e['loc']), 'type': e['type']} for e in exc.errors()]}, status_code=422)

    @app.get('/health')
    def health():
        return {'ok': True, 'service': 'local-agent-client', 'version': '0.7.2'}

    @app.get('/')
    def index():
        return {'service': 'Local Agent API', 'health': '/health',
                'desktop': 'Run: python -m local_agent desktop'}

    @app.get('/v1/projects/{project_id}/files', dependencies=[Depends(auth)])
    def files(project_id: str):
        with exclusive():
            return list_workspace_files(core(project_id).workspace)

    @app.get('/v1/projects/{project_id}/file', dependencies=[Depends(auth)])
    def file(project_id: str, path: str):
        with exclusive():
            content, error = read_file_preview(core(project_id).workspace, path)
            from .code_preview import code_preview
            return {'content': content, 'error': error, **(code_preview(path, content) if not error else {})}

    @app.get('/openapi.json', dependencies=[Depends(auth)])
    def schema():
        return app.openapi()

    def no_pending():
        if any(store.load_project(p).get('pending_command') for p in store.projects()):
            raise HTTPException(409, '请先处理待审批任务，再更改执行设置')

    from .schemas import ExtensionAction
    @app.get('/v1/extensions', dependencies=[Depends(auth)])
    def get_extensions():
        with exclusive():
            return extensions.list()

    @app.post('/v1/extensions', dependencies=[Depends(auth)])
    def extension_action(body: ExtensionAction):
        with exclusive():
            no_pending()
            if body.action == 'details':return extensions.details(body.id)
            if body.action == 'diagnose':return extensions.diagnose()
            if body.action == 'validate':return extensions.validate_package(body.data,body.directory)
            if body.action == 'export-config':return extensions.export_config()
            if body.action in {'preview-config','import-config'}:return extensions.import_config(body.config,apply=body.action=='import-config')
            if body.action == 'configure':return extensions.configure(body.id,body.config)
            if body.action == 'reset-appearance':extensions.reset_appearance();return {'ok':True}
            if body.action == 'inspect':return extensions.inspect(body.data,body.directory)
            if body.action == 'install':return extensions.install(body.data,body.directory,body.digest)
            if body.action == 'toggle':extensions.toggle(body.id,body.enabled,body.trusted)
            elif body.action == 'uninstall':return extensions.uninstall(body.id)
            elif body.action == 'read-skill':return extensions.read_skill(body.id)
            elif body.action == 'save-skill':return extensions.save_skill(body.id,body.content)
            elif body.action == 'delete-skill':extensions.delete_skill(body.id)
            return {'ok':True}

    @app.get('/v1/preferences', dependencies=[Depends(auth)])
    def get_preferences():
        return preferences.model_dump()

    @app.put('/v1/preferences', dependencies=[Depends(auth)])
    def put_preferences(body: Preferences):
        nonlocal preferences
        with exclusive():
            no_pending()
            save_preferences(settings.data_dir, body)
            preferences = body
            if isinstance(model, LANModel):
                model.options = body
            return get_preferences()

    @app.post('/v1/chat', response_model=Project, dependencies=[Depends(auth)])
    def new_chat():
        with exclusive():
            no_pending()
            folder = settings.data_dir / 'chats' / ('chat-' + secrets.token_hex(4))
            folder.mkdir(parents=True)
            project = store.add_project(str(folder))
            rows = store.projects()
            for row in rows:
                if row['id'] == project['id']:
                    row['name'] = '新对话'
                    project = row
            store.save_projects(rows)
            return project

    @app.get('/v1/configuration', dependencies=[Depends(auth)])
    def configuration():
        return {'base_url': settings.base_url, 'model': settings.model, 'key_configured': bool(settings.api_key)}

    @app.put('/v1/configuration', dependencies=[Depends(auth)])
    def configure(body: Configuration):
        nonlocal settings, remember_selection
        from .client_config import update_config
        with exclusive():
            no_pending()
            settings = update_config(settings, body.base_url, body.model or settings.model, body.api_key, body.remember_key)
            remember_selection = body.remember_key
            if isinstance(model, LANModel):
                model.settings = settings
            return configuration()

    def provider_error(exc):
        status = getattr(exc, 'status_code', None)
        reason = ('密钥无效或已过期，请更新连接设置' if status == 401 else
                  '此密钥没有模型访问权限，请联系主机管理员' if status == 403 else
                  '模型列表接口不存在，请检查主机地址及 /v1 路径' if status == 404 else
                  '请求过于频繁或配额不足，请稍后重试' if status == 429 else
                  '无法获取模型列表，请检查主机连接、密钥或稍后刷新')
        return HTTPException(502, reason)

    @app.get('/v1/models', dependencies=[Depends(auth)])
    def models():
        with exclusive():
            try:
                available = model.list_models()
            except Exception as exc:
                raise provider_error(exc) from None
            return {'models': available, 'selected': settings.model,
                    'available': settings.model in available}

    @app.put('/v1/models/selection', dependencies=[Depends(auth)])
    def select_model(body: ModelSelection):
        nonlocal settings
        from dataclasses import replace
        from .storage import atomic_json
        with exclusive():
            for project in store.projects():
                if store.load_project(project).get('pending_command'):
                    raise HTTPException(409, '请先完成等待审批的任务，再切换模型')
            try:
                available = model.list_models()
            except Exception as exc:
                raise provider_error(exc) from None
            if body.model not in available:
                raise HTTPException(409, '该模型已不可用，请刷新模型列表')
            if remember_selection:
                atomic_json(settings.data_dir / 'model-selection.json',
                            {'base_url': settings.base_url, 'model': body.model})
            settings = replace(settings, model=body.model)
            if isinstance(model, LANModel):
                model.settings = settings
            return configuration()

    @app.post('/v1/connection/test', dependencies=[Depends(auth)])
    def connection(body: ConnectionRequest):
        try:
            return model.check(body.inference)
        except Exception as exc:
            status = getattr(exc, 'status_code', None)
            name = type(exc).__name__
            reason = ('密钥无效或已过期，请更新此客户端的 Virtual Key' if status == 401 else
                      '此密钥没有访问模型的权限，请联系主机管理员' if status == 403 else
                      '模型或接口不存在，请检查模型名称和 /v1 地址' if status == 404 else
                      '请求过于频繁或配额不足，请稍后重试' if status == 429 else
                      '主机响应超时，请检查模型是否正在加载或繁忙' if 'Timeout' in name else
                      '无法连接主机，请检查局域网地址、服务和防火墙' if 'Connection' in name else
                      '连接测试失败，请检查主机配置')
            return {'ok': False, 'error_type': type(exc).__name__,
                    'detail': reason}

    @app.get('/v1/projects', response_model=list[Project], dependencies=[Depends(auth)])
    def projects(q: str = Query(default='', max_length=200)):
        rows=store.projects()
        for row in rows:
            snapshot=store.load_project(row)
            row['status']='running' if tasks.active(row['id']) else ('interrupted' if snapshot['status']=='running' else snapshot['status'])
            row['updated_at']=snapshot.get('updated_at',row.get('created_at'))
        if q.strip():
            query=q.strip().casefold();matches=[]
            for row in rows:
                if query in row['name'].casefold():matches.append(row);continue
                for message in store.load_project(row)['visible_messages']:
                    text=str(message.get('content',''));position=text.casefold().find(query)
                    if position>=0:
                        matches.append(dict(row,match_excerpt=text[max(0,position-30):position+100]));break
            rows=matches
        return sorted(rows,key=lambda p:not p.get('pinned',False))

    from .schemas import ProjectUpdate, ConversationCreate
    @app.put('/v1/projects/{project_id}/metadata',response_model=Project,dependencies=[Depends(auth)])
    def update_project(project_id: str, body: ProjectUpdate):
        with exclusive():
            rows=store.projects();row=next((p for p in rows if p['id']==project_id),None)
            if row is None:raise HTTPException(404,'Unknown project')
            if body.archived and store.load_project(row).get('pending_command'):
                raise HTTPException(409,'请先处理待审批操作，再归档对话')
            if body.name is not None:
                if not body.name.strip():raise ValueError('对话名称不能为空')
                row['name']=body.name.strip();row['name_custom']=True
            if body.default_skills is not None:
                extensions.selected(body.default_skills);row['default_skills']=body.default_skills
            if body.default_plugins is not None:
                extensions.selected_plugins(body.default_plugins);row['default_plugins']=body.default_plugins
            for other in rows:
                if other['group_id']==row['group_id']:
                    for field in ('default_skills','default_plugins'):
                        if getattr(body,field) is not None:other[field]=list(row[field])
            for key in ('pinned','archived'):
                value=getattr(body,key)
                if value is not None:row[key]=value
            store.save_projects(rows)
            return row

    @app.post('/v1/projects/{project_id}/conversations', response_model=Project, dependencies=[Depends(auth)])
    def new_conversation(project_id: str, body: ConversationCreate):
        with exclusive():
            return store.add_conversation(project_id,body.name)

    @app.post('/v1/projects', response_model=Project, dependencies=[Depends(auth)])
    def add_project(body: ProjectCreate):
        with exclusive():
            return store.add_project(body.path)

    @app.delete('/v1/projects/{project_id}', dependencies=[Depends(auth)])
    def remove_project(project_id: str):
        with exclusive():
            project = store.project(project_id)
            if not project:
                raise HTTPException(404, 'Unknown project')
            # Clear history before removing the index; re-adding a folder must
            # never resurrect a deleted conversation. Project files stay intact.
            store.save(store.empty_project(project))
            store.save_projects([p for p in store.projects() if p['id'] != project_id])
            tasks.forget(project_id)
            return {'removed': project_id, 'files_deleted': False}

    @app.get('/v1/projects/{project_id}/session', response_model=Session, dependencies=[Depends(auth)])
    def session(project_id: str):
        if tasks.active(project_id):
            project = store.project(project_id)
            if project is None:
                raise HTTPException(404, 'Unknown project')
            return store.load_project(project)
        with exclusive():
            return core(project_id).state

    @app.post('/v1/projects/{project_id}/tasks', response_model=TaskState, status_code=202, dependencies=[Depends(auth)])
    def start_task(project_id: str, body: MessageCreate):
        return tasks.start(project_id, 'send', body)

    @app.post('/v1/projects/{project_id}/revision-tasks', response_model=TaskState, status_code=202, dependencies=[Depends(auth)])
    def revise_message(project_id: str, body: MessageRevision):
        return tasks.start(project_id, 'revise', body)

    @app.post('/v1/projects/{project_id}/continue', response_model=TaskState, status_code=202, dependencies=[Depends(auth)])
    def continue_task(project_id: str):
        return tasks.start(project_id, 'continue', None)

    @app.post('/v1/projects/{project_id}/stop-paused', response_model=TaskState, status_code=202, dependencies=[Depends(auth)])
    def stop_paused(project_id: str):
        return tasks.start(project_id, 'stop-paused', None)

    @app.post('/v1/projects/{project_id}/approval-tasks', response_model=TaskState, status_code=202, dependencies=[Depends(auth)])
    def start_approval(project_id: str, body: Approval):
        return tasks.start(project_id, 'approve', body)

    @app.get('/v1/tasks/{task_id}', response_model=TaskState, dependencies=[Depends(auth)])
    def task(task_id: str):
        try:
            return tasks.get(task_id)
        except KeyError:
            raise HTTPException(404, 'Task handle expired; reload the project session')

    @app.post('/v1/tasks/{task_id}/cancel', response_model=TaskState, dependencies=[Depends(auth)])
    def cancel_task(task_id: str):
        try:
            return tasks.cancel(task_id)
        except KeyError:
            raise HTTPException(404, 'Task handle expired; reload the project session')

    @app.post('/v1/projects/{project_id}/session/reset', response_model=Session, dependencies=[Depends(auth)])
    def reset(project_id: str):
        with exclusive():
            engine = core(project_id)
            state = store.empty_project(store.project(project_id))
            store.save(state)
            return state

    @app.post('/v1/projects/{project_id}/messages', response_model=Session, dependencies=[Depends(auth)])
    def message(project_id: str, body: MessageCreate):
        with exclusive():
            from .attachments import prepare_attachments
            no_sibling_pending(project_id)
            return core(project_id).submit(body.content, prepare_attachments(body.attachments), skills=extensions.selected(body.skills),plugins=extensions.selected_plugins(body.plugins))

    @app.post('/v1/projects/{project_id}/approvals', response_model=Session, dependencies=[Depends(auth)])
    def approval(project_id: str, body: Approval):
        with exclusive():
            return core(project_id).approve(body.approval_id, body.allow)

    @app.get('/v1/projects/{project_id}/changes', dependencies=[Depends(auth)])
    def changes(project_id: str):
        with exclusive():
            engine = core(project_id)
            return {'agent_changes': engine.state['agent_changes'],
                    'diffs': {k: agent_diff_for_file(engine.workspace, k, v) for k, v in engine.state['agent_changes'].items()},
                    'git_status': get_git_status(engine.workspace), 'git_diff': get_git_diff(engine.workspace)}

    @app.post('/v1/projects/{project_id}/changes/revert', dependencies=[Depends(auth)])
    def revert(project_id: str):
        with exclusive():
            no_sibling_pending(project_id)
            return core(project_id).revert()

    @app.post('/v1/projects/{project_id}/changes/keep', dependencies=[Depends(auth)])
    def keep(project_id: str):
        with exclusive():
            engine = core(project_id)
            if engine.state.get('pending_command') or engine.state['tool_queue']:
                raise ValueError('Finish pending work before accepting changes')
            engine.state['agent_changes'] = {}
            engine.persist()
            return {'ok': True}

    return app
