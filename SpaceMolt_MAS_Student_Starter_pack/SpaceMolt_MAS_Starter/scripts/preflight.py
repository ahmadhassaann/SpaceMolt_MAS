"""Read-only SpaceMolt/Groq/MCP connectivity and environment checks.
No account credentials required. Never prints keys.
"""
from __future__ import annotations
import argparse, importlib.util, json, sys
import requests

def check_url(url, method='GET'):
    try:
        r = requests.request(method, url, timeout=15, headers={'User-Agent':'FAST-MAS-preflight/1.0'})
        print(f'{url} -> HTTP {r.status_code}; content-type={r.headers.get("Content-Type", "unknown")}')
        return r.status_code < 500
    except requests.RequestException as e:
        print(f'{url} -> NETWORK ERROR {type(e).__name__}: {e}')
        return False

def main():
    print('Python:', sys.version.split()[0]); print('External SDKs:')
    for name in ('requests','groq','keyring','mcp','a2a','uvicorn'):
        print(' ',name, 'installed' if importlib.util.find_spec(name) else 'missing')
    print('\nPublic, non-mutating endpoint checks:')
    checks=[check_url('https://spacemolt.com/docs/connections')]
    print('\nPreflight:', 'PASS' if all(checks) else 'CHECK NETWORK OR DOCUMENTATION')
    print('NOTE: This does NOT verify an authenticated MCP call, pilot login, or full mission.')
if __name__=='__main__': main()
