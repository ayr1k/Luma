"""Update installer-selected skills only when their content is an unchanged shipped version."""
import hashlib,json
from .bundle_history import SKILL_DIGESTS
from pathlib import Path
from .storage import atomic_json
LEGACY_DIGESTS = {'luma-code-review': 'f6939a29b138a3472e58d0df9ba21d00f4d4e3f915b9b1f2fbe5b3b1ddcb5f73', 'luma-debugging': '6bcd6ab8f74c97b85bec140dbe9a5c4ad5a69a985d3a1e8ee99a7301a5b6e328', 'luma-document-summary': '5998b308d5e27c3b8f90214222fe7e54b882d53b8f31853d3b3c4433cb6b3737', 'luma-implementation-plan': '266e56c208244af4ba3cdeff2a7a913f3cc0f8fe8dfb93479d6459f31c744cde', 'luma-writing': 'dbcf164c95745f079cf35e378bf2d1da545ff35998e03ebf39f46c0d44bffa48'}

def sync_skills(manager,directory):
 directory=Path(directory)
 if not directory.is_dir():return
 receipt=manager.base/'skill-receipts.json'
 try:seen=json.loads(receipt.read_text(encoding='utf-8')) if receipt.exists() else {}
 except (ValueError,OSError):
  manager.bundle_errors.append({'id':'preset-skills','error':'预置 Skill 更新记录无法读取，未自动更新'});return
 if not isinstance(seen,dict):
  manager.bundle_errors.append({'id':'preset-skills','error':'预置 Skill 记录格式无效'});return
 from .extensions import identifier,bounded,skill_metadata
 for folder in directory.iterdir():
  if not folder.is_dir():continue
  try:
   key=identifier(folder.name);source=bounded(directory,key+'/SKILL.md');content=source.read_text(encoding='utf-8-sig');skill_metadata(content,key)
   digest=hashlib.sha256(content.encode()).hexdigest();target=bounded(manager.skills,key+'/SKILL.md')
   if not target.exists() and key in seen:continue
   if target.exists():
    current=hashlib.sha256(target.read_text(encoding='utf-8-sig').encode()).hexdigest()
    if current not in {digest,seen.get(key),LEGACY_DIGESTS.get(key),*SKILL_DIGESTS.get(key,[])}:continue
   manager.save_skill(key,content);seen[key]=digest;atomic_json(receipt,seen)
  except (ValueError,OSError,UnicodeError) as exc:manager.bundle_errors.append({'id':folder.name,'error':str(exc)[:300]})
