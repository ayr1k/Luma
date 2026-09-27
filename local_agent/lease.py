"""OS-held lease shared by desktop, API and compatibility entrypoints."""
import os

class DataLease:
    def __init__(self, directory):
        self.directory = directory
        self.handle = None

    def acquire(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        handle = (self.directory / '.runtime.lock').open('a+b')
        if handle.tell() == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError('这个数据目录已由另一个 Local Agent 使用。请先关闭已有桌面、API 或 Streamlit 进程。') from exc
        self.handle = handle
        return self

    def close(self):
        if self.handle:
            self.handle.close()
            self.handle = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *args):
        self.close()
