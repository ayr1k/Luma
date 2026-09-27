"""Run on the gateway host. Master key stays in host environment."""
import argparse
import os
import httpx

parser = argparse.ArgumentParser()
parser.add_argument('client_name')
parser.add_argument('--gateway', default='http://127.0.0.1:4000')
args = parser.parse_args()
response = httpx.post(args.gateway.rstrip('/') + '/key/generate',
    headers={'Authorization': 'Bearer ' + os.environ['LITELLM_MASTER_KEY']},
    json={'models': ['local-agent-coder'], 'key_alias': args.client_name,
          'duration': '30d', 'rpm_limit': 30, 'metadata': {'client_id': args.client_name}}, timeout=30)
if response.status_code >= 400:
    raise SystemExit(f'Key creation failed: HTTP {response.status_code}; inspect gateway locally')
print('Store this key only in this client’s LITELLM_API_KEY:')
print(response.json()['key'])
