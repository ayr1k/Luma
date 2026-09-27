import json,sys
from local_agent.builtin_tools import dispatch
print(json.dumps(dispatch('luma-document-reader',json.load(sys.stdin)),ensure_ascii=False))
