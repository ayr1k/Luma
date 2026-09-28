"""Read-only release checks. No credentials, downloads, installers or project data are sent."""
import json,re,time,threading
from pathlib import Path
from urllib.parse import quote
import httpx
from .storage import atomic_json
from .version import VERSION,CODENAME,LTS_VERSION

RELEASES='https://github.com/ayr1k/Luma/releases'
API='https://api.github.com/repos/ayr1k/Luma/releases?per_page=100'

def select_releases(rows):
    result={}
    if not isinstance(rows,list):raise ValueError('发布信息格式无效')
    for row in rows:
        if not isinstance(row,dict) or row.get('draft') or row.get('prerelease'):continue
        tag=str(row.get('tag_name',''))
        match=re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)(?:[-.]?(lts)(?:[-.]?r(\d+))?)?',tag,re.I)
        if not match:continue
        channel='LTS' if match[4] else 'Latest'
        key=(*map(int,match.group(1,2,3)),int(match[5] or 0))
        if channel not in result or key>result[channel]['sort']:
            result[channel]={'version':'.'.join(match.group(1,2,3)),'revision':int(match[5] or 0),'sort':key,'url':RELEASES+'/tag/'+quote(tag,safe='')}
    for row in result.values():row.pop('sort')
    return result

class Updates:
    def __init__(self,root):
        self.path=Path(root)/'updates.json';self.lock=threading.Lock();self.running=False
        try:self.state=json.loads(self.path.read_text(encoding='utf-8'))
        except (ValueError,OSError):self.state={}
        if not isinstance(self.state,dict):self.state={}
        self.state.setdefault('automatic',True);self.state.setdefault('channel','Latest')
    def snapshot(self):
        with self.lock:return {**self.state,'checking':self.running,'current':VERSION,'codename':CODENAME,'lts_anchor':LTS_VERSION,'releases_url':RELEASES}
    def configure(self,automatic,channel):
        if type(automatic) is not bool or channel not in {'Latest','LTS'}:raise ValueError('更新设置无效')
        with self.lock:
            self.state.update(automatic=automatic,channel=channel);atomic_json(self.path,self.state)
        return self.snapshot()
    def check(self,force=False):
        with self.lock:
            due=time.time()-self.state.get('attempted_at',0)>86400
            if not self.running and (force or self.state['automatic'] and due):
                self.running=True;self.state['attempted_at']=time.time()
                threading.Thread(target=self._fetch,daemon=True).start()
        return self.snapshot()
    def _fetch(self):
        try:
            with httpx.Client(timeout=12,follow_redirects=False) as client:
                with client.stream('GET',API,headers={'Accept':'application/vnd.github+json','User-Agent':'Luma/'+VERSION}) as response:
                    response.raise_for_status();data=bytearray()
                    for chunk in response.iter_bytes():
                        data.extend(chunk)
                        if len(data)>4_000_000:raise ValueError('发布信息过大')
            channels=select_releases(json.loads(data))
            with self.lock:self.state.update(channels=channels,checked_at=time.time(),error='')
        except Exception as exc:
            error='无法检查更新，请检查网络后重试。保留上次检查结果。'
            if isinstance(exc,httpx.HTTPStatusError) and exc.response.status_code in {403,429}:error='GitHub 请求受到限制，请稍后重试。'
            with self.lock:self.state['error']=error
        finally:
            with self.lock:
                try:atomic_json(self.path,self.state)
                finally:self.running=False
