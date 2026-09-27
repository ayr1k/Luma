"""Endpoint-scoped, non-secret model preferences; additive to the LTS data format."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, ConfigDict
from .preferences import Preferences
from .storage import atomic_json

PARAMETERS = ('temperature', 'top_p', 'max_tokens', 'reasoning_effort', 'timeout')
CAPABILITIES = ('vision', 'tools', 'reasoning', 'streaming')

class CapabilityOverrides(BaseModel):
    model_config = ConfigDict(extra='forbid')
    vision: Literal['unknown','supported','unsupported'] = 'unknown'
    tools: Literal['unknown','supported','unsupported'] = 'unknown'
    reasoning: Literal['unknown','supported','unsupported'] = 'unknown'
    streaming: Literal['unknown','supported','unsupported'] = 'unknown'

class DiagnosticRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    probe: Literal['models','text','streaming','tools','reasoning'] = 'models'

def safe_failure(exc):
    status = getattr(exc, 'status_code', None)
    name = type(exc).__name__
    if status == 401: return 'authentication', '密钥无效或已过期，请更新连接设置。'
    if status == 403: return 'permission', '当前密钥无访问权限，请联系主机管理员。'
    if status == 404: return 'not_found', '模型或接口不存在，请检查模型列表与主机地址。'
    if status in (400,422): return 'request_rejected', '模型或网关拒绝请求，请检查参数和能力支持；可将思考强度恢复为模型默认。'
    if status == 429: return 'rate_limit', '请求受限或配额不足，请稍后重试。'
    if 'Timeout' in name: return 'timeout', '主机响应超时，请检查模型加载状态或调整超时。'
    if 'Connection' in name: return 'connection', '无法连接主机，请检查地址、局域网服务和防火墙。'
    if isinstance(exc, RuntimeError) and str(exc) in {'Model stream was interrupted or reached its output limit','Incomplete streamed tool call'}:
        return 'incomplete_output', '输出被截断或工具参数未完整接收，未执行不完整工具。请检查输出上限和连接，不要直接重放已执行操作。'
    return 'provider_error', '模型服务未完成请求，请运行模型诊断；不会自动重发或重放工具。'

class ModelProfiles:
    def __init__(self, root, legacy):
        self.path = root / 'model-profiles.json'
        self.data = {'version':1, 'defaults':{k:getattr(legacy,k) for k in PARAMETERS}, 'profiles':{}}
        try:
            value=json.loads(self.path.read_text(encoding='utf-8'))
            if value.get('version')==1 and isinstance(value.get('profiles'),dict):
                Preferences.model_validate(value['defaults'])
                self.data=value
        except (OSError,ValueError,TypeError,KeyError,AttributeError):
            if self.path.exists():
                raise ValueError('模型档案文件损坏，请先备份并检查 model-profiles.json') from None

    def key(self, settings):
        # Never put credentials or server addresses into exported reports or keys.
        return hashlib.sha256((settings.base_url.rstrip('/')+'\0'+settings.model).encode()).hexdigest()

    def entry(self, settings):
        return self.data['profiles'].setdefault(self.key(settings), {'parameters':dict(self.data['defaults']), 'manual':{}, 'tested':{}})

    def effective(self, settings, current):
        return Preferences.model_validate({**current.model_dump(),**self.entry(settings)['parameters']})

    def save(self):
        atomic_json(self.path,self.data)

    def save_parameters(self, settings, options):
        entry=self.entry(settings)
        values={k:getattr(options,k) for k in PARAMETERS}
        if entry['parameters']!=values:
            entry['tested']={} # Results from another parameter set must not look current.
        entry['parameters']=values
        self.save()

    def set_manual(self, settings, value):
        self.entry(settings)['manual']=value.model_dump()
        self.save()

    def record(self, settings, probe, passed, code):
        self.entry(settings)['tested'][probe]={'passed':passed,'code':code,'at':datetime.now(timezone.utc).isoformat()}
        self.save()

    def describe(self, settings):
        e=self.entry(settings)
        return {'model':settings.model, 'parameters':e['parameters'], 'capabilities':{
            k:{'manual':e['manual'].get(k,'unknown'), 'declared':'unknown', 'tested':e['tested'].get(k)} for k in CAPABILITIES},
            'diagnostics':e['tested'], 'note':'能力档案用于参考，不绕过模式权限或审批。测试仅代表当前路由的一次结果；失败不等于模型永远不支持。主机未提供经验证的能力声明时显示未知。'}
