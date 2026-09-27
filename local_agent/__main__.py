import argparse
import json
from .config import Settings
from .model import LANModel
from .storage import Store
from .core import AgentCore

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('serve')
    sub.add_parser('desktop')
    sub.add_parser('check').add_argument('--inference', action='store_true')
    sub.add_parser('chat').add_argument('workspace')
    sub.add_parser('check-extension').add_argument('path')
    args = parser.parse_args()
    if args.action == 'check-extension':
        import tempfile,base64
        from pathlib import Path
        from .extensions import Extensions
        path=Path(args.path)
        with tempfile.TemporaryDirectory() as temp:
            manager=Extensions(temp)
            result=manager.validate_package(directory=str(path)) if path.is_dir() else manager.validate_package(data=base64.b64encode(path.read_bytes()).decode())
        print(json.dumps(result,ensure_ascii=False,indent=2))
        raise SystemExit(0 if result['ok'] else 1)
    settings = Settings.load()
    if args.action == 'desktop':
        from .desktop import main as desktop_main
        desktop_main()
    elif args.action == 'serve':
        import uvicorn
        from .service import create_app
        uvicorn.run(create_app(settings), host='127.0.0.1', port=settings.port)
    elif args.action == 'check':
        try:
            result = LANModel(settings).check(args.inference)
        except Exception as exc:
            result = {'ok': False, 'error_type': type(exc).__name__}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result['ok'] else 1)
    else:
        import atexit
        from .lease import DataLease
        lease = DataLease(settings.data_dir).acquire()
        atexit.register(lease.close)
        store = Store(settings.data_dir)
        project = store.add_project(args.workspace)
        engine = AgentCore(store.load(project['path']), LANModel(settings), store.save)
        while True:
            pending = engine.state.get('pending_command')
            if pending:
                print('Workspace:', pending['workspace'], '\nCommand:', pending['command'])
                engine.approve(pending['approval_id'], input('Allow? [y/N] ').lower() == 'y')
            else:
                prompt = input('You> ').strip()
                if prompt in {'exit', 'quit'}:
                    break
                if not prompt:
                    continue
                engine.submit(prompt)
            if engine.state['visible_messages']:
                print(engine.state['visible_messages'][-1]['content'])

if __name__ == '__main__':
    main()
