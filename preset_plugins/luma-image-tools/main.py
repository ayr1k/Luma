import json,sys
from local_agent.builtin_tools import dispatch
print(json.dumps(dispatch('luma-image-tools',json.load(sys.stdin)),ensure_ascii=False))
