"""Trusted local code runner. Process separation is NOT an OS sandbox."""
import json, os, runpy, subprocess, sys, tempfile, time
from pathlib import Path
from contextlib import contextmanager
import shutil

@contextmanager
def request_directory():
    parent=Path(tempfile.gettempdir()).resolve()
    folder=Path(tempfile.mkdtemp(prefix='luma-plugin-',dir=parent)).resolve()
    try:yield str(folder)
    finally:
        if folder.parent!=parent or not folder.name.startswith('luma-plugin-'):raise ValueError('Invalid temporary directory')
        for attempt in range(40):
            try:
                shutil.rmtree(folder)
                break
            except PermissionError:
                if attempt==39:raise
                time.sleep(.05)


def windows_job(proc):
    """Terminate the worker and its descendants when the job handle closes."""
    if os.name != 'nt':return None
    import ctypes
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(n,ctypes.c_uint64) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateJobObjectW(None,None)
    info=Extended();info.basic.flags=0x2000
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle,w.HANDLE(int(proc._handle))):
        if handle:kernel.CloseHandle(handle)
        proc.kill();proc.wait()
        raise ValueError('无法建立插件进程生命周期管理，请检查 Windows 权限')
    return lambda:kernel.CloseHandle(handle)

def worker(entry, request, output):
    sys.stdin = open(request, encoding='utf-8')
    sys.stdout = open(output, 'w', encoding='utf-8', buffering=1)
    sys.argv = [entry]
    sys.path.insert(0, str(Path(entry).parent))
    runpy.run_path(entry, run_name='__main__')
    sys.stdout.flush()

def run_plugin(entry, request, workspace, data_directory, cancel_event, timeout=30):
    entry = str(Path(entry).resolve())
    with request_directory() as temp:
        folder=Path(temp); source=folder/'request.json'; output=folder/'output.json'; errors=folder/'errors.txt'
        source.write_text(json.dumps(dict(api_version=1, tool=request['tool'], input=request['input'], workspace=str(workspace), data_directory=str(data_directory)),ensure_ascii=False),encoding='utf-8')
        command=([sys.executable,'--plugin-worker'] if getattr(sys,'frozen',False) else [sys.executable,'-m','local_agent.plugin_worker'])+[entry,str(source),str(output)]
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','TEMP','TMP','PATH','PATHEXT','COMSPEC','SYSTEMDRIVE','USERPROFILE','LOCALAPPDATA','APPDATA'}}
        env['PYTHONUTF8']='1';env['PYTHONDONTWRITEBYTECODE']='1'
        # Source installs need the application import path; no provider credentials are passed.
        if not getattr(sys,'frozen',False):env['PYTHONPATH']=str(Path(__file__).resolve().parent.parent)
        with errors.open('wb') as err:
            proc=subprocess.Popen(command,cwd=str(Path(entry).parent),env=env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=err,creationflags=0x08000000 if os.name=='nt' else 0,start_new_session=os.name!='nt')
            close_job=windows_job(proc)
            started=time.monotonic()
            try:
                while proc.poll() is None:
                    if cancel_event.is_set():raise ValueError('插件执行已取消')
                    if time.monotonic()-started>timeout:raise ValueError('插件执行超时（30 秒）')
                    if any(p.exists() and p.stat().st_size>1024*1024 for p in (output,errors)):raise ValueError('插件输出超过限制')
                    time.sleep(.05)
                if proc.returncode:raise ValueError('插件运行失败，退出码 '+str(proc.returncode))
                if not output.exists() or output.stat().st_size>1024*1024:raise ValueError('插件输出缺失或超过限制')
                try:result=json.loads(output.read_text(encoding='utf-8'))
                except (ValueError,UnicodeError):raise ValueError('插件必须返回 JSON 对象')
                if not isinstance(result,dict) or not isinstance(result.get('text'),str) or len(result['text'])>64000:raise ValueError('插件 text 输出无效或过长')
                return result['text']
            finally:
                if close_job:close_job()
                if proc.poll() is None:
                    if os.name=='nt':proc.kill()
                    else:
                        import signal
                        os.killpg(proc.pid,signal.SIGKILL)
                    proc.wait(timeout=5)

if __name__=='__main__':worker(*sys.argv[1:])
