import json,sys
from pathlib import Path
request=json.load(sys.stdin)
if request['tool']!='count-files':raise ValueError('Unknown tool')
items=list(Path(request['workspace']).iterdir())
result={'files':sum(p.is_file() for p in items),'directories':sum(p.is_dir() for p in items)}
print(json.dumps({'text':json.dumps(result,ensure_ascii=False)},ensure_ascii=False))
