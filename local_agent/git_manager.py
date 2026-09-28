"""Explicit, local-only Git operations. Never accepts command strings or remote actions."""
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path, PurePosixPath
from .storage import atomic_json

LIMIT = 512_000
IGNORE = '# Luma: local credentials and generated files\n.env\n.env.*\n!.env.example\n.venv/\n.venv-client/\n__pycache__/\n*.py[cod]\nnode_modules/\nbuild/\ndist/\n'

class GitManager:
    def __init__(self, data_dir):
        self.config = Path(data_dir) / 'git-settings.json'
        self.log_path = Path(data_dir) / 'git-operations.json'

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

    def run(self, cwd, *args, allow=False, limit=LIMIT, executable=None, network=False):
        exe = executable or self.executable()
        if not exe:
            raise ValueError('未检测到 Git，请安装或指定 Git 可执行文件。')
        env = os.environ.copy()
        for name in list(env):
            if name.startswith('GIT_') and name not in {'GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM'}:
                env.pop(name, None)
        env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='Never', GIT_OPTIONAL_LOCKS='0', GIT_PAGER='cat')
        if network:
            env.update(GIT_SSH_COMMAND='ssh -oBatchMode=yes -oStrictHostKeyChecking=yes', GIT_SSH_VARIANT='ssh')
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            try:
                result = subprocess.run([exe, '--no-pager', '--literal-pathspecs', '-c', 'core.quotepath=false', *args],
                    cwd=str(cwd), env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                    timeout=120 if network else 45, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            except subprocess.TimeoutExpired:
                raise ValueError('Git 操作超时。请刷新检查实际状态后再尝试。') from None
            except OSError as exc:
                raise ValueError('无法启动 Git：' + str(exc)) from None
            out.seek(0); raw=out.read(limit+1)
            err.seek(0); error=err.read(8000).decode('utf-8', 'replace').strip()
        if result.returncode and not allow:
            raise ValueError(self.redact(error or raw.decode('utf-8','replace')[:8000] or 'Git 操作失败'))
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
        remote_info=self.remote_info(root,branch)
        return {**env,**remote_info,'state':'ready','root':str(root),'parent_repository':root!=Path(workspace).resolve(), 'branch':branch,'detached':not bool(branch),'head':head,
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
        if action in {'remote-add','remote-edit','remote-remove','fetch','pull','push','test-remote'}:
            return self.remote_action(root,state,body)
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

    @staticmethod
    def redact(text):
        text=re.sub(r'(https?://)[^/\s@]+@',r'\1[已隐藏]@',text,flags=re.I)
        return re.sub(r'(https?://[^\s?#]+)[?#][^\s]*',r'\1?[已隐藏]',text,flags=re.I)

    @staticmethod
    def valid_remote(name):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,99}',name):
            raise ValueError('远程名称只能包含字母、数字、点、短横线和下划线，且须以字母或数字开头。')
        return name

    @staticmethod
    def validate_url(url):
        from urllib.parse import urlsplit
        if not url or any(ord(c)<32 for c in url) or url.startswith('-'):
            raise ValueError('请输入有效的仓库地址。')
        if re.match(r'^[A-Za-z]:[\\/]',url) or url.startswith('/'):
            if not Path(url).is_dir():raise ValueError('本地仓库目录不存在。')
            return url
        if re.fullmatch(r'[\w.-]+@[\w.-]+:[\w./~-]+',url):return url
        parsed=urlsplit(url)
        if parsed.scheme not in {'https','ssh'} or not parsed.hostname or not parsed.path or parsed.query or parsed.fragment:
            raise ValueError('使用 HTTPS、SSH 仓库地址或本地仓库绝对路径；不支持 URL 参数和自定义传输协议。')
        if parsed.password or parsed.scheme=='https' and parsed.username:
            raise ValueError('仓库地址不能包含用户名、密码或令牌，请使用系统 Git 凭据管理。')
        return url

    def remote_info(self, root, branch):
        remotes=[];fingerprint=[]
        for name in self.text(root,'remote').splitlines():
            try:self.valid_remote(name)
            except ValueError:
                remotes.append({'name':name,'fetch_url':'','push_url':'','usable':False,'reason':'远程名称格式不受支持','web_url':''});continue
            fetch=self.text(root,'remote','get-url','--all',name).splitlines()
            push=self.text(root,'remote','get-url','--push','--all',name).splitlines()
            fingerprint.append([name,fetch,push])
            reason=''
            try:
                if len(fetch)!=1 or len(push)!=1:raise ValueError('此远程配置了多个地址，请先在外部 Git 工具简化配置。')
                self.validate_url(fetch[0]);self.validate_url(push[0])
            except ValueError as exc:reason=str(exc)
            url=fetch[0] if fetch else '';web=''
            if not reason:
                m=re.fullmatch(r'(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?',url)
                if m:web='https://github.com/'+m.group(1)
            remotes.append({'name':name,'fetch_url':self.redact(url),'push_url':self.redact(push[0] if push else ''),'usable':not reason,'reason':reason,'web_url':web})
        upstream=self.text(root,'rev-parse','--abbrev-ref','--symbolic-full-name','@{upstream}',allow=True) if branch else ''
        remote=self.text(root,'config','--get',f'branch.{branch}.remote',allow=True) if branch else ''
        merge=self.text(root,'config','--get',f'branch.{branch}.merge',allow=True) if branch else ''
        ahead=behind=None
        if upstream:
            counts=self.text(root,'rev-list','--left-right','--count','HEAD...@{upstream}',allow=True).split()
            if len(counts)==2:ahead,behind=map(int,counts)
        fingerprint.extend([branch,remote,merge])
        return {'remotes':remotes,'upstream':upstream,'upstream_remote':remote,'upstream_branch':merge.removeprefix('refs/heads/'),
                'ahead':ahead,'behind':behind,'remote_token':hashlib.sha256(json.dumps(fingerprint,ensure_ascii=False).encode()).hexdigest()}

    def remote_action(self, root, state, body):
        action=body.action;name=self.valid_remote(body.remote)
        if body.remote_token!=state['remote_token'] or body.token!=state['token']:
            raise ValueError('仓库或远程配置已变化，请刷新后重新确认。')
        row=next((r for r in state['remotes'] if r['name']==name),None)
        if action in {'remote-add','remote-edit'}:
            self.validate_url(body.url)
            if action=='remote-add':
                if row:raise ValueError('远程名称已经存在。')
                self.text(root,'remote','add',name,body.url)
            else:
                if not row:raise ValueError('远程不存在。')
                # A separate push URL is not silently retained or overwritten by this form.
                if self.text(root,'config','--get-all',f'remote.{name}.pushurl',allow=True):
                    raise ValueError('此远程配置了独立推送地址，请在外部工具调整，避免意外更改推送目标。')
                self.text(root,'remote','set-url',name,body.url)
            return {'message':'远程配置已保存；尚未连接或上传。'}
        if not row:raise ValueError('远程不存在，请刷新。')
        if action=='remote-remove':
            self.text(root,'remote','remove',name)
            return {'message':'已移除本地远程配置；服务器上的仓库不受影响。'}
        if not row['usable']:raise ValueError(row['reason'])
        if state['conflicts'] or state['operation_pending']:
            raise ValueError('请先在外部工具完成冲突、合并或变基，再同步。')
        if action in {'pull','push'}:
            if not state['head'] or state['detached']:raise ValueError('请先创建本地提交并切换到本地分支。')
            if not body.branch or body.branch.startswith('-') or body.branch=='HEAD':raise ValueError('请选择明确的远程分支名称。')
            self.text(root,'check-ref-format','refs/heads/'+body.branch)
            if action=='pull' and state['files']:raise ValueError('请先提交或在外部工具处理工作区修改，再拉取。')
        # Explicit target/refspecs avoid push.default, mirror, auto-stash, and recursive submodule surprises.
        prefix=['-c','protocol.ext.allow=never','-c','protocol.version=2']
        try:
            if action=='test-remote':args=['ls-remote','--heads',name]
            elif action=='fetch':args=['fetch','--no-recurse-submodules','--no-tags',name,'+refs/heads/*:refs/remotes/'+name+'/*']
            elif action=='pull':
                args=['-c','rebase.autoStash=false','-c','merge.autoStash=false','pull','--ff-only','--no-rebase','--no-autostash','--no-recurse-submodules','--no-tags',name,body.branch]
            elif action=='push':
                args=['-c',f'remote.{name}.mirror=false','-c','push.followTags=false','push','--porcelain','--no-force','--recurse-submodules=no','--set-upstream',name,'HEAD:refs/heads/'+body.branch]
            else:raise ValueError('不支持此远程操作。')
            self.run(root,*prefix,*args,network=True)
        except ValueError as exc:
            detail=str(exc);low=detail.lower()
            if any(v in low for v in ['authentication','could not read username','permission denied','credential','terminal prompts disabled','repository not found']):
                hint='认证或访问权限失败。请查看“Git 和 GitHub 支持”，在本机 Git 完成登录或 SSH 配置后重试。'
            elif any(v in low for v in ['non-fast-forward','fetch first','not possible to fast-forward','divergent','diverging']):
                hint='本地与远程历史不能直接快进。请先 Fetch 并查看领先/落后；需要合并或变基时在外部工具处理，本次不会强制覆盖。'
            elif 'host key verification' in low:hint='SSH 主机尚未验证或主机密钥发生变化。请在系统终端核验主机后重试。'
            else:hint='远程操作失败。请检查地址、网络与权限；超时后先刷新并 Fetch 核对实际状态。'
            raise ValueError(hint+'\n'+self.redact(detail)) from None
        return {'message':{'test-remote':'远程连接成功（已验证读取权限，写入权限以实际 Push 结果为准）。','fetch':'已获取远程信息，本地工作文件未改变。','pull':'已完成快进拉取。','push':'已推送当前分支并设置跟踪分支。'}[action]}

    def record(self,action,root,ok,message):
        try:rows=json.loads(self.log_path.read_text(encoding='utf-8'))
        except (ValueError,OSError):rows=[]
        if not isinstance(rows,list):rows=[]
        rows.append({'time':time.time(),'action':action,'workspace':str(root),'ok':ok,'message':self.redact(str(message))[:1500]})
        atomic_json(self.log_path,rows[-50:])

    def operations(self,workspace=None):
        try:rows=json.loads(self.log_path.read_text(encoding='utf-8'))
        except (ValueError,OSError):return []
        if not isinstance(rows,list):return []
        return [r for r in rows if workspace is None or r.get('workspace')==str(workspace)][::-1]

    def clone(self,url,parent,name):
        url=self.validate_url(url)
        parent=Path(parent).expanduser()
        if not parent.is_absolute() or not parent.is_dir():raise ValueError('请选择已有的本地父文件夹。')
        parent=parent.resolve()
        if not re.fullmatch(r'[^<>:"/\\|?*\x00-\x1f]{1,100}',name) or name in {'.','..'} or name.endswith((' ','.')):
            raise ValueError('新文件夹名称无效。')
        if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*[f'COM{i}' for i in range(1,10)],*[f'LPT{i}' for i in range(1,10)]}:raise ValueError('不能使用系统保留名称。')
        target=parent/name
        if target.exists():raise ValueError('目标已经存在，请使用新的文件夹名称。')
        stage=parent/('.luma-clone-'+uuid.uuid4().hex)
        stage.mkdir()
        try:
            with tempfile.TemporaryDirectory(prefix='luma-empty-hooks-') as hooks:
                self.run(parent,'-c','core.hooksPath='+hooks,'-c','protocol.file.allow=always',
                         'clone','--no-recurse-submodules','--',url,str(stage),network=True)
            if target.exists():raise ValueError('目标文件夹已被创建，请检查临时克隆目录。')
            stage.rename(target)
            self.record('clone',target,True,'克隆完成');return str(target)
        except ValueError as exc:
            hint=self.redact(str(exc))+'；未添加为项目。临时目录保留在 '+str(stage)
            self.record('clone',target,False,hint)
            raise ValueError(hint) from None
