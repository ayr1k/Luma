"""Read-only review snapshots and optimistic, per-file review actions."""
import base64
import difflib
import hashlib
import json
import os
import tempfile
from pathlib import Path

from .files import file_sha256
from .tools import safe_path

PREVIEW_LIMIT = 512_000


def digest(value):
    return hashlib.sha256(value).hexdigest() if value is not None else None


def before_bytes(change):
    if not change.get('existed_before'):
        return None
    if change.get('before_bytes') is not None:
        return base64.b64decode(change['before_bytes'], validate=True)
    value = change.get('before_content')
    if value is None:
        raise ValueError('缺少修改前快照，无法撤销')
    return value.encode('utf-8')


def current_file(workspace, path):
    target = safe_path(workspace, path)
    # Never act on a replaced link, directory, or metadata path.
    raw = workspace / path
    if raw.is_symlink() or any(p.lower() == '.git' for p in Path(path).parts):
        raise ValueError('此路径不允许审阅操作')
    if target.exists() and not target.is_file():
        raise ValueError('文件已被替换为目录或其他类型')
    return target, file_sha256(target)


def revision(change, current_hash):
    data = json.dumps([change, current_hash], sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(data).hexdigest()


def row(workspace, path, change):
    try:
        target, actual = current_file(workspace, path)
        problem = '' if actual == change.get('after_hash') else '文件在 Agent 修改后又发生变化，禁止撤销'
        original = before_bytes(change)
        if digest(original) != change.get('before_hash') and 'before_hash' in change:
            problem = '原始快照校验失败，禁止撤销'
        token = revision(change, actual)
    except (OSError, ValueError) as exc:
        problem = str(exc) if isinstance(exc, ValueError) else '文件不可访问'
        actual, token = None, None
    return dict(path=path, kind='modified' if change.get('existed_before') else 'added',
                revision=token, can_revert=not problem, warning=problem,
                unchanged=actual == change.get('before_hash') and not problem,
                rounds=list(change.get('review_rounds', {})))


def overview(state):
    workspace = Path(state['workspace'])
    rows = [row(workspace, p, c) for p, c in state['agent_changes'].items()]
    rounds = {}
    for c in state['agent_changes'].values():
        for key, r in c.get('review_rounds', {}).items():
            rounds[key] = {'id': key, 'created_at': r.get('created_at'), 'label': r.get('label', '任务')}
    return dict(files=rows, rounds=sorted(rounds.values(), key=lambda r: r['created_at'] or '', reverse=True),
                current_turn=state.get('turn_id'),
                busy=bool(state.get('pending_command') or state.get('tool_queue') or state.get('status') in {'running', 'paused', 'interrupted'}))


def text_preview(data):
    if data is None:
        return '', None
    if len(data) > PREVIEW_LIMIT:
        return None, '文件超过 500 KB，暂不提供文本对照'
    try:
        text = data.decode('utf-8')
        if '\x00' in text:
            raise UnicodeError()
        return text, None
    except UnicodeError:
        return None, '二进制或非 UTF-8 文件，暂不提供文本对照'


def detail(state, path, turn=None):
    change = state['agent_changes'].get(path)
    if change is None:
        raise ValueError('该文件不在当前待审阅清单中')
    info = row(Path(state['workspace']), path, change)
    if turn:
        snap = change.get('review_rounds', {}).get(turn)
        if snap is None:
            raise ValueError('该轮没有此文件的编辑快照')
        original = before_bytes(snap)
        after = base64.b64decode(snap['after_bytes'], validate=True) if snap.get('after_bytes') is not None else None
    else:
        original = before_bytes(change)
        target, _ = current_file(Path(state['workspace']), path)
        # Bound disk reads; snapshots already reside in the session.
        after = None
        if target.exists():
            with target.open('rb') as handle:
                after = handle.read(PREVIEW_LIMIT + 1)
        if digest(after) != change.get('after_hash'):
            info['warning'] = info['warning'] or '当前内容与 Agent 修改后的内容不同'
    a, ae = text_preview(original)
    b, be = text_preview(after)
    lines = []
    additions = deletions = 0
    limited = False
    if ae is None and be is None:
        # Avoid pathological quadratic matching of huge/repeated line lists.
        left, right = a.splitlines(), b.splitlines()
        if len(left) + len(right) > 12000:
            limited = True
        else:
            for tag, i, j, x, y in difflib.SequenceMatcher(None, left, right, autojunk=True).get_opcodes():
                if tag == 'equal':
                    # Collapsed context for large unchanged spans.
                    pairs = list(zip(range(i, j), range(x, y)))
                    for n, (old, new) in enumerate(pairs):
                        if len(pairs) > 12 and 4 <= n < len(pairs) - 4:
                            if n == 4: lines.append(dict(kind='gap', text=f'… 省略 {len(pairs)-8} 行未修改内容 …'))
                            continue
                        lines.append(dict(kind='context', old=old+1, new=new+1, text=left[old]))
                if tag in {'replace', 'delete'}:
                    deletions += j-i
                    lines.extend(dict(kind='delete', old=n+1, new=None, text=left[n]) for n in range(i,j))
                if tag in {'replace', 'insert'}:
                    additions += y-x
                    lines.extend(dict(kind='add', old=None, new=n+1, text=right[n]) for n in range(x,y))
    return dict(**info, before=a, after=b, before_missing=original is None, after_missing=after is None,
                lines=lines, additions=additions, deletions=deletions, turn=turn,
                preview_error=ae or be or ('行数过多，仅显示前后原文' if limited else None),
                byte_only=original != after and a == b)


def resolve(engine, action, selections):
    state = engine.state
    if state.get('pending_command') or state.get('tool_queue') or state.get('status') in {'running', 'paused', 'interrupted'}:
        raise ValueError('请先结束或停止当前任务，再处理文件变更')
    if action not in {'keep', 'revert'} or not selections or len({s['path'] for s in selections}) != len(selections):
        raise ValueError('无效的文件选择')
    changes = state['agent_changes']
    # Validate the whole selection before doing any writes.
    for selected in selections:
        if selected['path'] not in changes:
            raise ValueError('清单已变化，请刷新后重试')
    done, skipped = [], []
    for selected in selections:
        path = selected['path']
        change = changes[path]
        try:
            target, actual = current_file(engine.workspace, path)
            if selected['revision'] != revision(change, actual):
                raise ValueError('审阅后文件或记录发生变化，请刷新')
            if action == 'revert':
                original = before_bytes(change)
                if actual != change.get('after_hash'):
                    raise ValueError('后续修改受保护，未撤销')
                if 'before_hash' in change and digest(original) != change['before_hash']:
                    raise ValueError('原始快照校验失败')
                if original is None:
                    if target.exists(): target.unlink()
                else:
                    fd, temp = tempfile.mkstemp(dir=target.parent, prefix='.luma-revert-')
                    try:
                        with os.fdopen(fd, 'wb') as handle:
                            handle.write(original)
                            handle.flush()
                            os.fsync(handle.fileno())
                        _, fresh = current_file(engine.workspace, path)
                        if fresh != actual:
                            raise ValueError('撤销前文件发生变化')
                        os.replace(temp, target)
                    finally:
                        if os.path.exists(temp): os.unlink(temp)
        except (OSError, ValueError) as exc:
            skipped.append(dict(path=path, reason=str(exc) if isinstance(exc, ValueError) else '文件操作失败，已保留追踪记录'))
            continue
        del changes[path]
        # Persist per file: a later failure must not lose prior review decisions.
        engine.persist()
        done.append(path)
    return dict(action=action, done=done, skipped=skipped)
