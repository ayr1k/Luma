"""Packaged local HTML → narrow native bridge → authenticated loopback API."""
import json
import secrets
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path
import httpx
import uvicorn
from .config import Settings
from .service import create_app


class Bridge:
    def __init__(self, base_url, token, folder_picker=None):
        self._url = base_url
        self._token = token
        self._picker = folder_picker
        self._save_settings = None
        self._features = None
        self._refresh_features = None
        self._navigation_project = None
        self._busy = threading.Lock()
        self._active_task = None

    def request(self, action, project_id=None, payload=None):
        """No arbitrary URL, headers, credentials or Python execution exposed to HTML."""
        import re
        if action == 'export-settings-file':
            result=self.request('extension-action',payload={'action':'export-config'})
            if not result.get('ok'):return result
            if not self._save_settings:return {'ok':True,'data':{'document':result['data']}}
            path=self._save_settings()
            if not path:return {'ok':True,'data':{'cancelled':True}}
            from .storage import atomic_json
            atomic_json(Path(path),result['data'])
            return {'ok':True,'data':{'saved':True}}
        if action == 'check-extension-folder':
            selected=self._picker() if self._picker else None
            return self.request('extension-action',payload={'action':'validate','directory':selected}) if selected else {'ok':True,'data':None}
        if action == 'take-navigation':
            target=self._navigation_project;self._navigation_project=None
            return {'ok':True,'data':target}
        if action == 'native-status':
            return {'ok':True,'data':self._features.snapshot() if self._features else {'widget':'仅桌面版支持','hotkey':'仅桌面版支持'}}
        if action == 'open-skills-folder':
            import os
            result = self.request('extensions')
            if result.get('ok'):os.startfile(result['data']['skills_directory'])
            return result
        if action == 'inspect-extension-folder':
            selected = self._picker() if self._picker else None
            if not selected:return {'ok':True,'data':None}
            result = self.request('extension-action',payload={'action':'inspect','directory':selected})
            if result.get('ok'):result['data']['directory']=selected
            return result
        if action == 'open-source':
            from urllib.parse import urlparse
            import webbrowser
            url = (payload or {}).get('url', '')
            if not isinstance(url, str) or len(url) > 2000:
                return {'ok': False, 'error': '来源地址无效'}
            parsed = urlparse(url)
            if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
                return {'ok': False, 'error': '来源地址无效'}
            webbrowser.open(url)
            return {'ok': True, 'data': None}
        routes = {'extensions': ('GET','/v1/extensions'), 'extension-action': ('POST','/v1/extensions'), 'preferences': ('GET', '/v1/preferences'), 'save-preferences': ('PUT', '/v1/preferences'), 'new-chat': ('POST', '/v1/chat'), 'models': ('GET', '/v1/models'), 'select-model': ('PUT', '/v1/models/selection'), 'projects': ('GET', '/v1/projects'), 'connect': ('POST', '/v1/connection/test'),
                  'configuration': ('GET', '/v1/configuration'), 'configure': ('PUT', '/v1/configuration')}
        project_routes = {'new-conversation':('POST','conversations'), 'update-project': ('PUT','metadata'), 'continue': ('POST', 'continue'), 'stop-paused': ('POST', 'stop-paused'), 'session': ('GET', 'session'), 'send': ('POST', 'tasks'), 'revise': ('POST', 'revision-tasks'),
            'approve': ('POST', 'approval-tasks'), 'changes': ('GET', 'changes'),
            'keep': ('POST', 'changes/keep'), 'revert': ('POST', 'changes/revert'),
            'reset': ('POST', 'session/reset'), 'files': ('GET', 'files'), 'file': ('GET', 'file')}
        if action == 'delete-conversation':
            if not isinstance(project_id, str) or not re.fullmatch(r'[a-f0-9]{12}', project_id):
                return {'ok': False, 'error': '对话 ID 无效'}
            method, path, payload = 'DELETE', f'/v1/projects/{project_id}', None
        elif action in {'task', 'cancel'}:
            task_id = (payload or {}).get('task_id', '')
            if not isinstance(task_id, str) or not re.fullmatch(r'[a-f0-9]{32}', task_id):
                return {'ok': False, 'error': '任务 ID 无效'}
            method = 'GET' if action == 'task' else 'POST'
            path = f'/v1/tasks/{task_id}' + ('/cancel' if action == 'cancel' else '')
            payload = None
        elif action in project_routes:
            if not isinstance(project_id, str) or not re.fullmatch(r'[a-f0-9]{12}', project_id):
                return {'ok': False, 'error': '项目 ID 无效'}
            method, suffix = project_routes[action]
            path = f'/v1/projects/{project_id}/{suffix}'
        elif action in routes:
            method, path = routes[action]
        elif action == 'add':
            selected = self._picker() if self._picker else None
            if not selected:
                return {'ok': True, 'data': None}
            method, path, payload = 'POST', '/v1/projects', {'path': selected}
        else:
            return {'ok': False, 'error': '不支持此操作'}
        if not self._busy.acquire(blocking=False):
            return {'ok': False, 'error': '任务正在运行，请等待当前操作结束'}
        try:
            with httpx.Client(base_url=self._url, trust_env=False, timeout=httpx.Timeout(2100, connect=5)) as client:
                kwargs = {'headers': {'Authorization': 'Bearer ' + self._token}}
                if method == 'GET' and action == 'projects':
                    kwargs['params'] = {'q':(payload or {}).get('q','')}
                elif method == 'GET' and action == 'file':
                    kwargs['params'] = {'path': (payload or {}).get('path', '')}
                elif method in {'POST', 'PUT'}:
                    kwargs['json'] = payload or {}
                response = client.request(method, path, **kwargs)
                if response.is_error:
                    if response.status_code == 404 and action in {'task', 'cancel'}:
                        self._active_task = None
                    return {'ok': False, 'status': response.status_code, 'error': str(response.json().get('detail', '请求失败'))}
                data = response.json()
                if action == 'extension-action' and self._refresh_features:
                    self._refresh_features()
                if action in {'send', 'revise', 'approve', 'task', 'cancel', 'continue', 'stop-paused'}:
                    if data['running']:
                        self._active_task = data['id']
                    elif self._active_task == data['id']:
                        self._active_task = None
                if self._features and action in {'send','revise','approve','task','continue','cancel','stop-paused'}:
                    self._features.completed('running' if data.get('running') else data.get('session',{}).get('status','idle'))
                return {'ok': True, 'data': data}
        except Exception as exc:
            return {'ok': False, 'error': f'本机服务通信失败：{type(exc).__name__}'}
        finally:
            self._busy.release()


class LocalServer:
    def __init__(self, settings, on_task_done=None):
        # Desktop owns its ephemeral service; a token never enters page JS.
        self.token = secrets.token_urlsafe(32)
        self.socket = socket.socket()
        self.socket.bind(('127.0.0.1', 0))
        self.url = f'http://127.0.0.1:{self.socket.getsockname()[1]}'
        self.app = create_app(replace(settings, local_token=self.token), on_task_done=on_task_done)
        self.server = uvicorn.Server(uvicorn.Config(self.app,
            log_level='warning', access_log=False, log_config=None))
        self.thread = threading.Thread(target=self.server.run, kwargs={'sockets': [self.socket]}, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(100):
            if self.server.started:
                return
            if not self.thread.is_alive():
                break
            time.sleep(.05)
        raise RuntimeError('本机服务启动失败')

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)
        self.socket.close()


def main():
    import webview
    settings = Settings.load()
    try:
        with httpx.Client(trust_env=False, timeout=1) as probe:
            active = probe.get(f'http://127.0.0.1:{settings.port}/health')
            if active.is_success and active.json().get('service') == 'local-agent-client':
                raise RuntimeError('请先在旧 API 终端按 Ctrl+C 停止服务，然后重新打开桌面窗口。桌面窗口会自动启动自己的服务。')
    except (httpx.HTTPError, ValueError):
        pass
    # One desktop per data directory. OS releases this lock on crash.
    import msvcrt
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    lockfile = (settings.data_dir / '.desktop.lock').open('a+b')
    if lockfile.tell() == 0:
        lockfile.write(b'0')
        lockfile.flush()
    lockfile.seek(0)
    try:
        msvcrt.locking(lockfile.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lockfile.close()
        raise RuntimeError('Luma 已在运行。请在右下角系统托盘（包括折叠区域）双击 Luma 图标打开窗口。')
    from .tray import TrayController, WindowsTray
    controller = None
    server = LocalServer(settings)
    server.app.state.tasks.on_event=lambda event:controller.completed(event['status'],event['project_id']) if controller else None
    try:
        server.start()
        def pick():
            selected = window.create_file_dialog(webview.FileDialog.FOLDER)
            return selected[0] if selected else None
        bridge = Bridge(server.url, server.token, pick)
        def save_settings_file():
            selected=window.create_file_dialog(webview.FileDialog.SAVE,save_filename='Luma-extension-settings.json',file_types=('JSON (*.json)',))
            return selected[0] if isinstance(selected,(list,tuple)) and selected else selected
        bridge._save_settings=save_settings_file
        html = (Path(__file__).parent / 'ui' / 'index.html').read_text(encoding='utf-8')
        window = webview.create_window('Luma', html=html, js_api=bridge,
            width=1280, height=900, min_size=(850, 600), background_color='#181818', text_select=True)
        controller = TrayController(window, server.app.state.tasks.shutdown)
        controller.navigate=lambda project_id:setattr(bridge,'_navigation_project',project_id)
        def closing():
            if controller.ready or controller.exiting:
                return controller.closing()
            if bridge._busy.locked() or bridge._active_task:
                return False
        window.events.closing += closing
        startup_failed = threading.Event()
        def check_startup():
            if not window.events.loaded.wait(30):
                startup_failed.set()
                controller.exiting = True
                window.destroy()
                return
            from System import Action
            def install_tray():
                try:
                    controller.adapter = WindowsTray(controller, Path(__file__).parent / 'ui/luma.ico')
                    controller.ready = True
                    from .native_features import NativeFeatures
                    from .extensions import Extensions
                    features=NativeFeatures(controller,settings.data_dir)
                    controller.adapter.features=features
                    bridge._features=features
                    bridge._refresh_features=lambda:features.refresh(Extensions(settings.data_dir).list()['plugins'])
                    bridge._refresh_features()
                except Exception:
                    import logging
                    logging.exception('System tray initialization failed; window stays available')
            window.native.BeginInvoke(Action(install_tray))
        webview.start(check_startup, icon=str(Path(__file__).parent / 'ui' / 'luma.ico'), gui='edgechromium', debug=False, private_mode=False,
                      storage_path=str(settings.data_dir / '.webview'))
        if startup_failed.is_set():
            raise RuntimeError('WebView2 窗口未能完成初始化。请在普通用户桌面运行，确认 Microsoft Edge WebView2 Runtime 可用；可用 Start Local Agent.cmd 查看启动信息。')
    finally:
        server.stop()
        lockfile.close()

if __name__ == '__main__':
    main()
