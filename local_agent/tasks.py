"""One active execution per service; snapshot reads never mutate a running session."""
import threading
import uuid
import copy
from pathlib import Path
from .attachments import prepare_attachments

class Tasks:
    def __init__(self, operation_lock, core_factory, store, on_done=None):
        self.on_done = on_done
        self.on_event = None
        self.lock = operation_lock
        self.core_factory = core_factory
        self.store = store
        self.guard = threading.Lock()
        self.jobs = {}
        self.closed = False

    def start(self, project_id, action, body):
        with self.guard:
            if self.closed:
                raise ValueError('Service is shutting down')
            if not self.lock.acquire(blocking=False):
                raise ValueError('另一个任务正在运行，请等待或停止后续执行')
            try:
                prepared = prepare_attachments(body.attachments) if action == 'send' else []
                if action == 'send' and not body.content.strip() and not prepared:
                    raise ValueError('请输入消息或添加附件')
                engine = self.core_factory(project_id)
                if action in {'send','revise','continue'}:
                    for sibling in self.store.projects():
                        if sibling['id']!=project_id and str(engine.workspace)==str(Path(sibling['path']).resolve()) and self.store.load_project(sibling).get('pending_command'):
                            raise ValueError('同一项目的其他任务正在等待审批，请先处理，避免文件状态变化')
                if action == 'send':
                    selected_skills = engine.extensions.selected(body.skills) if engine.extensions else []
                    engine.selected_skills = selected_skills
                    engine.selected_plugins = engine.extensions.selected_plugins(body.plugins) if engine.extensions else []
                    if engine.state.get('pending_command') or engine.state['tool_queue'] or engine.state['status'] == 'interrupted':
                        raise ValueError('请处理待审批任务，或为已中断任务新建会话')
                    rows = self.store.projects()
                    for row in rows:
                        if row['id'] == project_id and row['name'] in {'新对话','新任务'} and not row.get('name_custom'):
                            row['name'] = ' '.join(body.content.split())[:28] or (prepared[0]['name'] if prepared else '新对话')
                            self.store.save_projects(rows)
                            break
                elif action in {'continue', 'stop-paused'}:
                    if engine.state['status'] != 'paused' or engine.state.get('pending_command') or engine.state['tool_queue']:
                        raise ValueError('当前任务不处于暂停状态')
                elif action == 'revise':
                    prepared = engine.prepare_revision(body.message_index, body.content)
                else:
                    pending = engine.state.get('pending_command')
                    if not pending or pending['approval_id'] != body.approval_id:
                        raise ValueError('Stale or invalid approval')
                event = threading.Event()
                engine.cancel_event = event
                task_id = uuid.uuid4().hex
                job = dict(id=task_id, project_id=project_id, workspace=engine.workspace,
                           event=event, running=True, session_id=engine.state.get('session_id'))
                # Completed in-memory handles are only short-lived UI transport state.
                for old in list(self.jobs):
                    if len(self.jobs) < 100:
                        break
                    if not self.jobs[old]['running']:
                        del self.jobs[old]
                self.jobs[task_id] = job
                thread = threading.Thread(target=self._run, args=(job, engine, action, body, prepared), daemon=True)
                job['thread'] = thread
                # Publish preparation before returning the asynchronous handle.
                # Keep approval consumption and execution status transitions in the worker.
                engine.state['progress']={'stage':'queued'}
                engine.save(engine.state)
                thread.start()
            except BaseException:
                self.lock.release()
                raise
        return self.get(task_id)

    def _run(self, job, engine, action, body, prepared):
        try:
            if action == 'send':
                engine.submit(body.content, prepared, skills=engine.selected_skills, plugins=engine.selected_plugins)
            elif action == 'continue':
                engine.resume()
            elif action == 'stop-paused':
                engine.cancel()
            elif action == 'revise':
                engine.revise(body.content, prepared)
            else:
                engine.approve(body.approval_id, body.allow)
        except Exception as exc:
            engine.state['status'] = 'failed'
            engine.visible(f'任务异常：{type(exc).__name__}。请检查连接或新建会话。')
            try:
                engine.persist()
            except OSError:
                with self.guard:
                    job['storage_error'] = '会话保存失败。请检查磁盘空间或目录权限；不要重复执行未经核对的命令。'
                    job['failure_snapshot'] = copy.deepcopy(engine.state)
        finally:
            with self.guard:
                job['running'] = False
                self.lock.release()
            if self.on_event:
                try:self.on_event(dict(project_id=job['project_id'],task_id=job['id'],status='failed' if job.get('storage_error') else engine.state['status']))
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Task event delivery failed')
            if self.on_done:
                try:
                    self.on_done('failed' if job.get('storage_error') else engine.state['status'])
                except Exception:
                    import logging
                    logging.getLogger(__name__).exception('Task notification failed')

    def get(self, task_id):
        with self.guard:
            job = self.jobs.get(task_id)
            if job is None:
                raise KeyError(task_id)
            # Atomic store writes provide complete snapshots while tools execute.
            return dict(id=job['id'], project_id=job['project_id'], running=job['running'],
                        cancel_requested=job['event'].is_set(), error=job.get('storage_error'),
                        session=job.get('failure_snapshot') or self.store.load(job['workspace'],job.get('session_id')))

    def cancel(self, task_id):
        with self.guard:
            job = self.jobs.get(task_id)
            if job is None:
                raise KeyError(task_id)
            if job['running']:
                job['event'].set()
        return self.get(task_id)

    def active(self, project_id):
        with self.guard:
            return any(j['running'] and j['project_id'] == project_id for j in self.jobs.values())

    def forget(self, project_id):
        with self.guard:
            for task_id, job in list(self.jobs.items()):
                if job['project_id'] == project_id and not job['running']:
                    del self.jobs[task_id]

    def shutdown(self):
        with self.guard:
            self.closed = True
            jobs = [j for j in self.jobs.values() if j['running']]
            for job in jobs:
                job['event'].set()
        for job in jobs:
            # Model and terminal calls already have bounded timeouts. Do not release
            # the data-directory lease until their safe boundary has been reached.
            job['thread'].join()
