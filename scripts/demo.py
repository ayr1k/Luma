"""End-to-end API demo. Default: deterministic HTTP mock. --live: configured LAN model."""
import argparse
import json
import secrets
import tempfile
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from fastapi.testclient import TestClient
from local_agent.config import Settings
from local_agent.model import LANModel
from local_agent.service import create_app

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--base-url')
    parser.add_argument('--output', type=Path, default=Path('demo-runs'))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix='demo-', dir=args.output.resolve()))
    project = run / 'project'
    project.mkdir()
    token = secrets.token_urlsafe(32)
    settings = replace(Settings.load(), data_dir=run / 'data', local_token=token)
    server = None
    if args.live:
        if args.base_url:
            settings = replace(settings, base_url=args.base_url)
    else:
        key = 'sk-demo-only'
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.reply({'object': 'list', 'data': [{'id': 'demo-model', 'object': 'model', 'created': 0, 'owned_by': 'demo'}]})

            def reply(self, value):
                if self.headers.get('Authorization') != 'Bearer ' + key:
                    self.send_response(401)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(value).encode())

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                results = [m for m in body['messages'] if m['role'] == 'tool']
                sequence = [('write_file', {'path': 'demo.txt', 'content': 'LAN client demo OK\n'}),
                            ('run_command', {'command': 'echo local-tool-ok'}),
                            ('finish', {'summary': 'Created demo.txt on the client; command was approved locally.'})]
                name, arguments = sequence[min(len(results), 2)]
                self.reply({'id': 'demo', 'object': 'chat.completion', 'created': 0, 'model': 'demo-model',
                    'choices': [{'index': 0, 'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                        'tool_calls': [{'id': 'call-' + str(len(results)), 'type': 'function',
                                        'function': {'name': name, 'arguments': json.dumps(arguments)}}]}}]})
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        settings = replace(settings, base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key=key, model='demo-model')
    try:
        with TestClient(create_app(settings), base_url='http://localhost') as api:
            api.headers['Authorization'] = 'Bearer ' + token
            connection = api.post('/v1/connection/test', json={}).json()
            if not connection['ok']:
                raise RuntimeError(str(connection))
            p = api.post('/v1/projects', json={'path': str(project)}).json()['id']
            base = '/v1/projects/' + p
            response = api.post(base + '/messages', json={'content':
                'Create demo.txt containing exactly LAN client demo OK followed by a newline. '
                'Then read demo.txt to verify it, then request run_command with exactly echo local-tool-ok. '
                'After the command result, call finish. Only work in this demo workspace.'})
            response.raise_for_status()
            state = response.json()
            while state['pending_command']:
                pending = state['pending_command']
                print('Approval workspace:', pending['workspace'])
                print('Approval command:', pending['command'])
                # Only the fixed harmless demo command is authorized by invoking this demo.
                allow = pending['command'].strip() == 'echo local-tool-ok'
                state = api.post(base + '/approvals', json={'approval_id': pending['approval_id'], 'allow': allow}).json()
            target = project / 'demo.txt'
            result = {'mode': 'live-lan' if args.live else 'mock-http', 'status': state['status'],
                      'file_verified': target.exists() and target.read_text(encoding='utf-8').strip() == 'LAN client demo OK',
                      'approved_command_verified': any(x['name'] == 'run_command' and 'EXIT_CODE: 0' in x['result'] and 'local-tool-ok' in x['result'] for x in state['tool_logs']),
                      'tracked_files': list(state['agent_changes']), 'run_directory': str(run)}
            (run / 'result.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
            print(json.dumps(result, indent=2))
            if not (result['file_verified'] and result['approved_command_verified'] and state['status'] == 'completed'):
                raise SystemExit(1)
    finally:
        if server:
            server.shutdown()
            server.server_close()

if __name__ == '__main__':
    main()
