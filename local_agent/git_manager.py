"""Explicit, local-only Git operations. Never accepts command strings or remote actions."""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from .storage import atomic_json

LIMIT = 512_000
IGNORE = '# Luma: local credentials and generated files\n.env\n.env.*\n!.env.example\n.venv/\n.venv-client/\n__pycache__/\n*.py[cod]\nnode_modules/\nbuild/\ndist/\n'

class GitManager:
    def __init__(self, data_dir):
        self.config = Path(data_dir) / 'git-settings.json'

    def executable(self):
        try:
            configured = json.loads(self.config.read_text(encoding='utf-8')).get('path', '')
        except (OSError, ValueError):
            configured = ''
        candidates = [configured, shutil.which('git')]
        if os.name == 'nt':
            for base in [os.environ.get('ProgramFiles'), os.environ.get('LOCALAPPDATA')]:
                if base:
                    candidates.extend([str(Path(base)/'Git/cmd/git.exe'), str(Path(base)/'Programs/Git/cmd/git.exe')])
        return next((str(Path(p).resolve()) for p in candidates if p and Path(p).is_file()), None)

    def run(self, cwd, *args, allow=False, limit=LIMIT, executable=None):
        exe = executable or self.executable()
        if not exe:
            raise ValueError('未检测到 Git，请安装或指定 Git 可执行文件。')
        env = os.environ.copy()
        for name in list(env):
            if name.startswith('GIT_') and name not in {'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM'}:
                env.pop(name, None)
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', GIT_OPTIONAL_LOCKS='0', GIT_PAGER='cat')
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                result = subprocess.run([exe, '--no-pager', '--literal-pathspecs', '-c', 'core.quotepath=false', *args],
                    cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                    timeout=45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                raise ValueError('Git 操作超时。请刷新检查实际状态后再尝试。') from None
            except OSError as exc:
                raise ValueError('无法启动 Git：' + str(exc)) from None
            out.seek(0); raw=out.read(limit+1)
            err.seek(0); error=err.read(8000).decode('utf-8', 'replace').strip()
        if result.returncode and not allow:
            raise ValueError(error or raw.decode('utf-8','replace')[:8000] or 'Git 操作失败')
        return raw, result.returncode, len(raw)>limit

    def text(self, root, *args, allow=False):
        data, code, truncated=self.run(root,*args,allow=allow)
        if truncated:
            raise ValueError('Git 输出过大，请使用外部 Git 工具处理该仓库。')
        return data.decode('utf-8','replace').strip() if not code else ''

    def environment(self):
        exe=self.executable()
        if not exe:return {'installed':False,'path':'','version':'','error':''}
        try:return {'installed':True,'path':exe,'version':self.text(Path.home(),'--version'),'error':''}
        except ValueError as exc:return {'installed':False,'path':exe,'version':'','error':str(exc)}

    def configure_path(self, path):
        if not path:
            atomic_json(self.config,{'path':''});return self.environment()
        candidate=Path(path).expanduser()
        if not candidate.is_absolute() or not candidate.is_file() or candidate.name.lower() not in {'git','git.exe'}:
            raise ValueError('请选择有效的 Git 可执行文件（git.exe），不能是脚本或目录。')
        data,_,_=self.run(Path.home(),'--version',executable=str(candidate))
        if not data.startswith(b'git version '):raise ValueError('所选文件不是有效的 Git。')
        atomic_json(self.config,{'path':str(candidate.resolve())})
        return self.environment()

    def root(self, workspace):
        workspace=Path(workspace).resolve()
        raw,code,_=self.run(workspace,'rev-parse','--show-toplevel',allow=True)
        if code:
            # Preserve ownership and corruption errors instead of pretending this is a new repository.
            _,_,_=self.run(workspace,'rev-parse','--is-inside-work-tree')
            raise ValueError('当前路径不是工作区仓库。')
        root=Path(raw.decode('utf-8','replace').strip()).resolve()
        if not workspace.is_relative_to(root):raise ValueError('Git 仓库根目录与项目路径不一致。')
        return root

    def status(self, workspace):
        env=self.environment()
        if not env['installed']:return {**env,'state':'missing'}
        try:root=self.root(workspace)
        except ValueError as exc:
            text=str(exc)
            if 'not a git repository' in text.lower():return {**env,'state':'uninitialized','workspace':str(workspace),'ignore_preview':IGNORE,'ignore_exists':(Path(workspace)/'.gitignore').exists()}
            return {**env,'state':'error','error':text}
        raw,_,truncated=self.run(root,'status','--porcelain=v1','-z','--untracked-files=all')
        if truncated:raise ValueError('仓库改动数量过大，请先在外部 Git 工具处理。')
        parts=raw.decode('utf-8','replace').split('\0');files=[];i=0
        while i<len(parts) and parts[i]:
            item=parts[i];i+=1;x,y=item[:2];path=item[3:];old=None
            if x in 'RC' or y in 'RC':old=parts[i];i+=1
            conflict=x=='U' or y=='U' or x+y in {'AA','DD'}
            files.append({'path':path,'old_path':old,'index':x,'worktree':y,'staged':x not in ' ?','unstaged':y!=' ' or x=='?', 'conflict':conflict})
        head=self.text(root,'rev-parse','--verify','HEAD',allow=True)
        branch=self.text(root,'symbolic-ref','--short','HEAD',allow=True)
        refs=self.text(root,'for-each-ref','--format=%(refname:short)','refs/heads').splitlines()
        index=Path(self.text(root,'rev-parse','--git-path','index'))
        if not index.is_absolute():index=root/index
        stamp=hashlib.sha256(raw+head.encode()+(index.read_bytes() if index.exists() else b'')).hexdigest()
        pending=any((root/Path(self.text(root,'rev-parse','--git-path',name))).exists() for name in ['MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD','rebase-merge','rebase-apply'])
        return {**env,'state':'ready','root':str(root),'parent_repository':root!=Path(workspace).resolve(), 'branch':branch,'detached':not bool(branch),'head':head,
            'branches':refs,'files':files,'token':stamp,'conflicts':any(f['conflict'] for f in files),'operation_pending':pending,
            'identity':{'name':self.text(root,'config','user.name',allow=True),'email':self.text(root,'config','user.email',allow=True)}}

    def validate_path(self, root, path):
        p=PurePosixPath(path)
        if not path or p.is_absolute() or '..' in p.parts or '.git' in [v.lower() for v in p.parts] or '\\' in path or '\0' in path or re.match(r'^[A-Za-z]:',path):
            raise ValueError('无效的仓库相对路径。')
        # Git may list symlinks; never follow one out of the repository to preview its target.
        return Path(root)/path

    def blob(self, root, ref, path):
        data,code,truncated=self.run(root,'show',f'{ref}:{path}',allow=True)
        return (b'' if code else data),truncated

    def detail(self, workspace, path, area='worktree', commit=''):
        root=self.root(workspace);target=self.validate_path(root,path)
        if area=='history':
            if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',commit):raise ValueError('无效的提交 ID。')
            self.text(root,'cat-file','-e',commit+'^{commit}')
            parent=self.text(root,'rev-parse','--verify',commit+'^',allow=True)
            before,t1=self.blob(root,parent,path) if parent else (b'',False)
            after,t2=self.blob(root,commit,path)
            args=['show','--format=','--no-ext-diff','--no-textconv','--no-color',commit,'--',path]
        else:
            status=self.status(workspace)
            row=next((f for f in status.get('files',[]) if f['path']==path),None)
            if not row:raise ValueError('文件状态已变化，请刷新。')
            old=row['old_path'] or path
            if area=='index':
                before,t1=self.blob(root,'HEAD',old);after,t2=self.blob(root,'',path)
                args=['diff','--cached','--no-ext-diff','--no-textconv','--no-color','--',old,path]
            else:
                before,t1=self.blob(root,'',path)
                if target.is_symlink():after=os.readlink(target).encode();t2=False
                elif not target.resolve().is_relative_to(root):raise ValueError('文件链接指向仓库之外，无法预览。')
                elif target.is_file():
                    with target.open('rb') as f:after=f.read(LIMIT+1)
                    t2=len(after)>LIMIT
                else:after=b'';t2=False
                args=['diff','--no-ext-diff','--no-textconv','--no-color','--',path]
        binary=b'\0' in before or b'\0' in after
        patch,_,truncated=self.run(root,*args)
        if not patch and area=='worktree' and before!=after and not binary:
            patch=''.join(difflib.unified_diff(before.decode('utf-8','replace').splitlines(True),after.decode('utf-8','replace').splitlines(True),fromfile='a/'+path,tofile='b/'+path)).encode()
        return {'path':path,'diff':patch[:LIMIT].decode('utf-8','replace'),'before':'' if binary else before[:LIMIT].decode('utf-8','replace'),'after':'' if binary else after[:LIMIT].decode('utf-8','replace'),'binary':binary,'truncated':truncated or t1 or t2 or len(patch)>LIMIT}

    def history(self, workspace, commit=''):
        root=self.root(workspace)
        if commit:
            if not re.fullmatch(r'[0-9a-f]{40}|[0-9a-f]{64}',commit):raise ValueError('无效的提交 ID。')
            raw,_,truncated=self.run(root,'diff-tree','--root','--no-commit-id','--name-only','--no-renames','-r','-z',commit)
            return {'files':raw.decode('utf-8','replace').strip('\0').split('\0') if raw else [],'truncated':truncated}
        if not self.text(root,'rev-parse','--verify','HEAD',allow=True):return {'commits':[]}
        data=self.text(root,'log','-40','--format=%H%x09%an%x09%aI%x09%s')
        return {'commits':[dict(zip(['id','author','time','title'],line.split('\t',3))) for line in data.splitlines() if len(line.split('\t',3))==4]}

    def action(self, workspace, body):
        action=body.action
        if action=='init':
            state=self.status(workspace)
            if state['state']!='uninitialized':raise ValueError('项目已经属于仓库，或 Git 环境不可用。请刷新检查。')
            self.text(workspace,'check-ref-format','--branch',body.branch or 'main')
            self.text(workspace,'init','-b',body.branch or 'main')
            if body.ignore:
                try:
                    with (Path(workspace)/'.gitignore').open('x',encoding='utf-8') as f:f.write(IGNORE)
                except FileExistsError:pass
            return {'message':'本地仓库已初始化，尚未提交或上传文件。'}
        state=self.status(workspace)
        if state['state']!='ready':raise ValueError('Git 仓库不可用，请刷新。')
        root=Path(state['root'])
        if str(root)!=body.root:raise ValueError('仓库范围已变化，请刷新并确认仓库根目录。')
        if action=='identity':
            if not body.name.strip() or not body.email.strip() or any(c in body.name+body.email for c in '\r\n\0'):raise ValueError('请填写有效的姓名和邮箱。')
            scope='--global' if body.global_identity else '--local'
            self.text(root,'config',scope,'user.name',body.name.strip());self.text(root,'config',scope,'user.email',body.email.strip())
            return {'message':'提交身份已保存。'}
        if body.token!=state['token']:raise ValueError('仓库状态已变化，请刷新后重试。')
        if state['conflicts'] or state['operation_pending']:raise ValueError('仓库存在冲突或未完成的合并操作，请先在外部 Git 工具处理。')
        if action in {'stage','unstage'}:
            if not body.paths:raise ValueError('请先选择文件。')
            paths=[]
            for path in body.paths:
                self.validate_path(root,path)
                row=next((r for r in state['files'] if r['path']==path),None)
                if not row or not row['staged' if action=='unstage' else 'unstaged']:raise ValueError('文件状态已变化，请刷新。')
                paths.append(path)
                if row['old_path']:paths.append(row['old_path'])
            if action=='stage':self.text(root,'add','--',*paths)
            elif state['head']:self.text(root,'reset','-q','HEAD','--',*paths)
            else:self.text(root,'rm','--cached','-q','-f','--',*paths)
        elif action=='commit':
            if not body.message.strip():raise ValueError('请填写提交说明。')
            if not all(state['identity'].values()):raise ValueError('请先设置提交身份。')
            if not any(r['staged'] for r in state['files']):raise ValueError('没有已暂存的文件。')
            if state['detached']:raise ValueError('当前处于分离 HEAD，请先创建或切换到本地分支。')
            self.text(root,'commit','-m',body.message.strip())
        elif action in {'switch','branch'}:
            if state['files']:raise ValueError('请先提交或在外部工具处理未提交修改，再切换或创建分支。')
            if not body.branch or body.branch.startswith('-'):raise ValueError('请填写有效的分支名称。')
            self.text(root,'check-ref-format','--branch',body.branch)
            if action=='switch':
                if body.branch not in state['branches']:raise ValueError('请选择已有的本地分支。')
                self.text(root,'switch','--no-guess',body.branch)
            else:self.text(root,'switch','-c',body.branch)
        else:raise ValueError('不支持此 Git 操作。')
        return {'message':{'stage':'文件已暂存。','unstage':'已取消暂存，文件内容保留。','commit':'已保存本地提交。','switch':'已切换分支。','branch':'已创建并切换到新分支。'}[action]}

    def staged_prompt(self, workspace, token):
        state=self.status(workspace)
        if state.get('token')!=token:raise ValueError('暂存状态已变化，请刷新。')
        if not any(r['staged'] for r in state['files']):raise ValueError('没有已暂存的文件。')
        patch,_,truncated=self.run(state['root'],'diff','--cached','--no-ext-diff','--no-textconv','--no-color',limit=24000)
        return patch[:24000].decode('utf-8','replace'),truncated
