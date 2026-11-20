"""Safe SpaceMolt pilot registration/login status helper (HTTP v2 ONLY).
Registration and status are setup activities, not assessed autonomous gameplay.
Game-playing agents must implement authenticated MCP themselves.

Examples:
 python examples/pilot_setup.py register --username GROUP01-A --empire nebula
 python examples/pilot_setup.py register --username GROUP01-B --empire nebula
 python examples/pilot_setup.py status --username GROUP01-A

IMPORTANT: Registration creates a permanent account. Do not repeat once successful.
"""
from __future__ import annotations
import argparse
import getpass
import json
from typing import Any
import requests
import keyring

API = 'https://game.spacemolt.com/api/v2'
VAULT = 'spacemolt-course-test'  # Reuses instructor's previously tested Windows keyring entry.
TIMEOUT = 35

def first_field(obj: Any, names: set[str], depth: int = 0) -> str | None:
    if depth > 8: return None
    if isinstance(obj, dict):
        for k,v in obj.items():
            if str(k).lower() in names and isinstance(v,str) and v: return v
        for v in obj.values():
            found=first_field(v,names,depth+1)
            if found: return found
    elif isinstance(obj,list):
        for v in obj:
            found=first_field(v,names,depth+1)
            if found: return found
    return None

class APIClient:
    def __init__(self):
        self.s=requests.Session()
        self.s.headers.update({'Content-Type':'application/json','User-Agent':'FAST-MAS-registration/1.0'})
        r=self.s.post(API+'/session',json={},timeout=TIMEOUT)
        data=self._parse(r)
        sid=first_field(data,{'session_id','sessionid'})
        if not sid and isinstance(data.get('session'),dict): sid=data['session'].get('id')
        if not sid: sid=r.headers.get('X-Session-Id')
        if not sid: raise RuntimeError('Session created, but no session ID was found; inspect official docs')
        self.s.headers['X-Session-Id']=sid
    @staticmethod
    def _parse(r):
        try: obj=r.json()
        except ValueError: raise RuntimeError(f'Non-JSON SpaceMolt response: HTTP {r.status_code}')
        if not r.ok or obj.get('error') or obj.get('success') is False:
            code=obj.get('error')
            if isinstance(code,dict): code=code.get('code') or 'error'
            raise RuntimeError(f'SpaceMolt HTTP {r.status_code}: error={str(code or "unknown")[:90]}')
        return obj
    def action(self,tool,action,payload=None):
        return self._parse(self.s.post(API+f'/{tool}/{action}',json=payload or {},timeout=TIMEOUT))

def registration(username,empire):
    print('Get registration code from https://spacemolt.com/dashboard')
    print('Registration is a real account-creation action; use a NEW username.')
    code=getpass.getpass('Registration code (hidden): ').strip().strip('`')
    if not code: raise SystemExit('Registration code required')
    client=APIClient()
    data=client.action('spacemolt_auth','register',{'username':username,'empire':empire,'registration_code':code})
    code='' # Avoid retaining/printing the registration code.
    password=first_field(data,{'password','generated_password','player_password'})
    if not password:
        raise SystemExit('Registration may have completed, but password was not machine-readable. Check SpaceMolt dashboard. Do NOT retry blindly.')
    keyring.set_password(VAULT,username,password)
    if keyring.get_password(VAULT,username)!=password:
        raise RuntimeError('Credential store verification failed. Use official dashboard password recovery.')
    print(f'[PASS] Registered {username} ({empire}); password saved to Windows Credential Manager')
    print('[SECURITY] Do not share registration code/password/session details')

def status(username):
    password=keyring.get_password(VAULT,username)
    if not password:
        password=getpass.getpass('Existing pilot password (hidden): ')
        if not password: raise SystemExit('A pilot password is required')
        if input('Store in Windows Credential Manager? [y/N] ').strip().lower()=='y':
            keyring.set_password(VAULT,username,password)
    client=APIClient()
    client.action('spacemolt_auth','login',{'username':username,'password':password})
    data=client.action('spacemolt','get_status')
    structured=data.get('structuredContent')
    if isinstance(structured,dict):
        player=structured.get('player',{})
        print('[PASS] Authenticated pilot:',player.get('username',username))
        print('Credits:',player.get('credits','unknown'))
        print('Home system:',player.get('home_system','unknown'))
        print('Ore mined:',player.get('stats',{}).get('ore_mined','unknown'))
    else:
        print('[PASS] Authenticated. Redacted status text:')
        print(str(data.get('result','Status retrieved'))[:300])
    print('[NOTE] This is HTTP v2 registration/status; assessed gameplay must use MCP.')

def main():
    p=argparse.ArgumentParser()
    p.add_argument('action',choices=('register','status'))
    p.add_argument('--username',required=True)
    p.add_argument('--empire',default='nebula')
    a=p.parse_args()
    if a.action=='register': registration(a.username,a.empire)
    else: status(a.username)
if __name__=='__main__': main()
