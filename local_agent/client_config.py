"""Per-user settings; Virtual Key encrypted with Windows CurrentUser DPAPI."""
import base64
import ctypes
import json
import os
from ctypes import wintypes
from dataclasses import replace
from urllib.parse import urlparse
import ipaddress
from .storage import atomic_json

class Blob(ctypes.Structure):
    _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]

def crypt(value: bytes, decrypt=False) -> bytes:
    if os.name != 'nt':
        raise ValueError('Credential storage requires Windows DPAPI')
    buffer = ctypes.create_string_buffer(value)
    source = Blob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result)):
        raise OSError(ctypes.get_last_error(), 'Windows credential protection is unavailable')
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel = ctypes.WinDLL('kernel32')
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        kernel.LocalFree(ctypes.cast(result.data, ctypes.c_void_p))

def read_config(data_dir):
    path = data_dir / 'client-config.json'
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    # Other Windows users cannot decrypt a copied key; allow reconfiguration.
    try:
        key = crypt(base64.b64decode(data['protected_key']), decrypt=True).decode()
    except (ValueError, KeyError, UnicodeError, OSError):
        key = ''
    return {'base_url': data['base_url'], 'model': data['model'], 'api_key': key}

def update_config(settings, base_url, model, api_key=None, remember_key=True):
    parsed = urlparse(base_url.strip().rstrip('/'))
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/v1'}:
        raise ValueError('地址格式应为 http://192.168.1.77:4000/v1')
    host = parsed.hostname
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if host != 'localhost' and not host.endswith('.local') and '.' in host:
            raise ValueError('当前版本仅支持局域网 IP 或本地主机名')
    else:
        if not (ip.is_private or ip.is_loopback) or ip.is_unspecified or ip.is_multicast:
            raise ValueError('当前版本仅支持局域网地址')
    _ = parsed.port  # Reject malformed ports before writing.
    key = api_key.strip() if api_key and api_key.strip() else settings.api_key
    if not key or not model.strip():
        raise ValueError('首次配置需要模型名称和此客户端的 Virtual Key')
    url = base_url.strip().rstrip('/')
    if not parsed.path:
        url += '/v1'
    if remember_key:
        try:
            protected = base64.b64encode(crypt(key.encode())).decode()
        except OSError as exc:
            raise ValueError('Windows 无法加密保存密钥。可以取消“在这台电脑上保存”后仅本次使用。') from exc
        atomic_json(settings.data_dir / 'client-config.json', {
            'base_url': url, 'model': model.strip(),
            'protected_key': protected, 'schema_version': 1})
    return replace(settings, base_url=url, model=model.strip(), api_key=key)
