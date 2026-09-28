"""Non-destructive upgrade audit and extension metadata checkpoint."""
import json,shutil,time
from pathlib import Path
from .storage import atomic_json
from .version import VERSION

def audit(root):
    root=Path(root);report=root/'upgrade-report.json'
    try:
        previous=json.loads(report.read_text(encoding='utf-8'))
        if previous.get('version')==VERSION:return previous
    except (OSError,ValueError):pass
    backup=root/'backups'/('before-'+VERSION+'-'+str(time.time_ns()))
    issues=[];count=0
    for name in ['projects.json','preferences.json','model-profiles.json','extensions/registry.json','extensions/bundled-receipts.json','extensions/skill-receipts.json']:
        p=root/name
        if not p.exists():continue
        try:
            if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()):raise ValueError('文件链接位于数据目录外')
            dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dest)
            json.loads(p.read_text(encoding='utf-8'));count+=1
        except (ValueError,OSError) as exc:issues.append({'file':name,'error':type(exc).__name__})
    for p in (root/'sessions').glob('*.json'):
        try:
            value=json.loads(p.read_text(encoding='utf-8'))
            if not isinstance(value,dict):raise ValueError('invalid session')
            count+=1
        except (ValueError,OSError):issues.append({'file':'sessions/'+p.name,'error':'无法读取，原文件已保留'})
    result={'version':VERSION,'checked_at':time.time(),'checked_files':count,'issues':issues,'backup':str(backup) if backup.exists() else '',
            'note':'只检查 JSON 可读性并备份关键设置；不改写会话，不等同于完整数据备份。'}
    atomic_json(report,result);return result
