"""Source and frozen GUI entrypoint with local diagnostics and headless self-test."""
import json
import logging
import multiprocessing
import sys
from pathlib import Path

def self_test(output):
    from .config import Settings
    from .desktop import LocalServer, Bridge
    from .client_config import crypt
    settings = Settings.load()
    server = LocalServer(settings)
    result = {'frozen': bool(getattr(sys, 'frozen', False)), 'ui_asset': False, 'api': False}
    try:
        html = (Path(__file__).parent / 'ui/index.html').read_text(encoding='utf-8')
        result['ui_asset'] = 'settings-dialog' in html
        server.start()
        bridge = Bridge(server.url, server.token)
        result['api'] = bridge.request('configuration')['ok'] and bridge.request('preferences')['ok']
        from .extensions import Extensions
        from .plugin_worker import run_plugin
        import threading
        runner=settings.data_dir/'selftest-worker.py'
        runner.write_text("import json, sys; request=json.load(sys.stdin); print(json.dumps({'text':'worker-ok'}))",encoding='utf-8')
        result['plugin_worker'] = run_plugin(runner,{'tool':'selftest','input':{}},settings.data_dir,settings.data_dir,threading.Event()) == 'worker-ok'
        result['extensions_api'] = bridge.request('extensions')['ok']
        result['icon_asset'] = (Path(__file__).parent / 'ui/luma.ico').is_file()
        from ddgs import DDGS
        result['search_dependency'] = type(DDGS(timeout=5)).__name__ == 'DDGS'
        from ddgs.engines import ENGINES
        result['search_engine'] = 'duckduckgo' in ENGINES.get('text', {})
        import base64, io
        from PIL import Image
        from pypdf import PdfReader, PdfWriter
        from .attachments import prepare_attachments
        from .schemas import AttachmentInput
        image_buffer = io.BytesIO()
        Image.new('RGB', (8, 8), 'white').save(image_buffer, format='PNG')
        prepared = prepare_attachments([AttachmentInput(name='test.png', data=base64.b64encode(image_buffer.getvalue()).decode())])
        pdf_buffer = io.BytesIO()
        writer = PdfWriter(); writer.add_blank_page(width=100, height=100); writer.write(pdf_buffer)
        fixture=settings.data_dir/'selftest-project';fixture.mkdir(exist_ok=True)
        (fixture/'image.png').write_bytes(image_buffer.getvalue())
        (fixture/'document.pdf').write_bytes(pdf_buffer.getvalue())
        builtin_checks=[]
        for plugin,tool,args in [
            ('luma-project-overview','overview',{}),
            ('luma-document-reader','read-document',{'path':'document.pdf'}),
            ('luma-image-tools','transform',{'path':'image.png','output':'small.webp'}),
            ('luma-file-organizer','scan',{})]:
            runner.write_text("import json,sys; from local_agent.builtin_tools import dispatch; print(json.dumps(dispatch("+repr(plugin)+",json.load(sys.stdin))))",encoding='utf-8')
            answer=run_plugin(runner,{'tool':tool,'input':args},fixture,settings.data_dir,threading.Event())
            builtin_checks.append(not answer.startswith('ERROR:'))
        result['builtin_plugins']=all(builtin_checks)
        result['attachment_dependencies'] = prepared[0]['kind'] == 'image' and len(PdfReader(pdf_buffer).pages) == 1
        from .code_preview import code_preview
        result['syntax_dependency'] = any(k == 'keyword' for k, v in code_preview('test.py', 'def f(): return 1')['tokens'])
        result['developer_credentials_absent'] = not bool(settings.api_key)
        try:
            result['credential_store'] = crypt(crypt(b'test'), decrypt=True) == b'test'
        except OSError as exc:
            result['credential_store'] = False
            result['credential_error'] = exc.errno
    finally:
        server.stop()
    Path(output).write_text(json.dumps(result, indent=2), encoding='utf-8')
    return 0 if all(result.get(k) for k in ('ui_asset', 'api', 'icon_asset', 'search_dependency', 'search_engine', 'attachment_dependencies', 'syntax_dependency', 'plugin_worker', 'extensions_api', 'builtin_plugins')) else 1

def main():
    multiprocessing.freeze_support()
    if len(sys.argv) == 5 and sys.argv[1] == "--plugin-worker":
        from .plugin_worker import worker
        worker(*sys.argv[2:])
        return
    import os
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w')
    if len(sys.argv) == 3 and sys.argv[1] == '--self-test':
        raise SystemExit(self_test(sys.argv[2]))
    from .config import Settings
    settings = Settings.load()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    # No API request logging: no keys, prompts or project content in startup.log.
    log = settings.data_dir / 'startup.log'
    logging.basicConfig(filename=log, level=logging.WARNING,
                        format='%(asctime)s %(levelname)s %(name)s %(message)s', encoding='utf-8')
    try:
        from .desktop import main as desktop_main
        desktop_main()
    except Exception as exc:
        logging.getLogger('local_agent').error('Startup failed: %s', type(exc).__name__)
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f'{exc}\n\n启动日志：{log}', 'Luma 启动失败', 0x10)
        raise SystemExit(1)

if __name__ == '__main__':
    main()
