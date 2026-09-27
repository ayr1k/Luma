"""Atomic JSON persistence retaining legacy project IDs and session filenames."""
import hashlib
import re
import uuid
import json
import os
import tempfile
import threading
import time
from functools import wraps
from datetime import datetime
from pathlib import Path

def empty_session(workspace):
    return dict(workspace=str(Path(workspace).resolve()), visible_messages=[], agent_messages=[],
                tool_logs=[], pending_command=None, agent_changes={}, tool_queue=[],
                status='idle', steps=0, no_tool_streak=0)

def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                break
            except PermissionError as exc:
                if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt == 19:
                    raise
                time.sleep(.01)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def synchronized(method):
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.io_lock:
            return method(self, *args, **kwargs)
    return wrapper

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.io_lock = threading.RLock()

    def session_path(self, workspace, session_id=None):
        if session_id is not None:
            if not isinstance(session_id,str) or not re.fullmatch(r"[a-f0-9]{12}",session_id):raise ValueError("Invalid conversation ID")
            return self.root / "sessions" / ("conversation-"+session_id+".json")
        digest = hashlib.sha256(str(Path(workspace).resolve()).encode()).hexdigest()[:16]
        return self.root / 'sessions' / (digest + '.json')

    @synchronized
    def load(self, workspace, session_id=None):
        state = empty_session(workspace)
        path = self.session_path(workspace, session_id)
        if path.exists():
            loaded = json.loads(path.read_text(encoding='utf-8'))
            state.update(loaded)
            if 'status' not in loaded:
                self._upgrade_legacy(state)
        state['workspace'] = str(Path(workspace).resolve())
        if session_id is not None:state['session_id']=session_id
        else:state.pop('session_id',None)
        return state

    @staticmethod
    def _upgrade_legacy(state):
        # Old web.py returned on finish without writing its required tool result.
        # Repair protocol history without executing any historical tool calls.
        history = state['agent_messages']
        repaired = []
        pending = state.get('pending_command')
        index = 0
        while index < len(history):
            msg = history[index]
            repaired.append(msg)
            index += 1
            if msg.get('role') != 'assistant' or not msg.get('tool_calls'):
                continue
            answered = set()
            while index < len(history) and history[index].get('role') == 'tool':
                repaired.append(history[index])
                answered.add(history[index]['tool_call_id'])
                index += 1
            for call in msg['tool_calls']:
                if call['id'] in answered:
                    continue
                if pending and pending.get('tool_call_id') == call['id'] and index == len(history):
                    continue
                if pending and index == len(history):
                    state['tool_queue'].append(call)
                    continue
                fn = call['function']
                result = 'Not executed: unresolved tool call from legacy session.'
                if fn['name'] == 'finish':
                    try:
                        result = json.loads(fn['arguments']).get('summary', 'Task completed.')
                    except (ValueError, TypeError):
                        pass
                repaired.append(dict(role='tool', tool_call_id=call['id'], content=result))
        state['agent_messages'] = repaired
        if pending:
            state['status'] = 'waiting_approval'

    @synchronized
    def save(self, state):
        state['updated_at']=datetime.now().isoformat(timespec='seconds')
        atomic_json(self.session_path(state['workspace'],state.get('session_id')), state)

    @synchronized
    def projects(self):
        path = self.root / 'projects.json'
        data = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
        rows=data if isinstance(data, list) else data.get('projects', [])
        for row in rows:
            row.setdefault('group_id',hashlib.sha256(str(Path(row['path']).resolve()).encode()).hexdigest()[:12])
            row.setdefault('project_name',Path(row['path']).name or row['path'])
            row.setdefault('kind','chat' if Path(row['path']).parent.resolve()==(self.root/'chats').resolve() else 'project')
        return rows

    @synchronized
    def save_projects(self, projects):
        path=self.root/'projects.json'
        backup=self.root/'backups'/'pre-0.7.0-projects.json'
        if path.exists() and not backup.exists():
            atomic_json(backup,json.loads(path.read_text(encoding='utf-8')))
        atomic_json(path, projects)

    def add_project(self, path):
        target = Path(path).expanduser().resolve()
        if not target.is_dir():
            raise ValueError('Project directory does not exist')
        projects = self.projects()
        now = datetime.now().isoformat(timespec='seconds')
        project = next((p for p in projects if Path(p['path']).resolve() == target), None)
        if project is None:
            project = dict(id=hashlib.sha256(str(target).encode()).hexdigest()[:12],
                           name=target.name or str(target), path=str(target), created_at=now)
            projects.insert(0, project)
        project['archived'] = False
        project['last_opened'] = now
        self.save_projects(projects)
        return project

    def project(self, project_id):
        return next((p for p in self.projects() if p['id'] == project_id), None)


    def load_project(self, project):
        return self.load(project['path'],project.get('session_id'))

    def empty_project(self, project):
        state=empty_session(project['path'])
        if project.get('session_id'):state['session_id']=project['session_id']
        return state

    @synchronized
    def add_conversation(self, project_id, name='新任务'):
        rows=self.projects();source=next((p for p in rows if p['id']==project_id),None)
        if source is None:raise ValueError('项目不存在')
        if not Path(source['path']).is_dir():raise ValueError('项目目录不可用')
        if not name.strip():raise ValueError('任务名称不能为空')
        key=uuid.uuid4().hex[:12]
        while any(p['id']==key for p in rows):key=uuid.uuid4().hex[:12]
        row=dict(id=key,session_id=key,group_id=source['group_id'],project_name=source['project_name'],kind=source['kind'],
            name=name.strip(),name_custom=name.strip()!='新任务',path=source['path'],created_at=datetime.now().isoformat(timespec='seconds'),
            default_skills=list(source.get('default_skills',[])),default_plugins=list(source.get('default_plugins',[])),archived=False,pinned=False)
        # Create the empty state before publishing its index; a crash can only leave an orphan empty file.
        self.save(self.empty_project(row));rows.insert(0,row);self.save_projects(rows)
        return row
