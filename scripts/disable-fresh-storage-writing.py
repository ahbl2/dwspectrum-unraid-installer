#!/usr/bin/env python3
"""One-time, narrowly scoped recording-write disable for a fresh DW server.
Refuses unrecognized multi-server sites, multiple storages, or online storage. Never enables writes.
"""
import json,ssl,sys,time,urllib.error,urllib.request
from pathlib import Path

BASE='https://127.0.0.1:7203'
CREDS=Path('/mnt/cache/dwspectrum-quarantine/config/secrets/dw-api.json')
CTX=ssl._create_unverified_context()

def request(path,token=None,method='GET',body=None):
    headers={'Content-Type':'application/json'}
    if token:headers['Authorization']='Bearer '+token
    data=json.dumps(body).encode() if body is not None else None
    req=urllib.request.Request(BASE+path,headers=headers,method=method,data=data)
    for attempt in range(12):
        try:
            with urllib.request.urlopen(req,context=CTX,timeout=5) as res:
                payload=res.read()
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            if attempt == 11:
                raise
            time.sleep(1)

def safe_pair(servers):
    return (len(servers)==2 and all(isinstance(s,dict) for s in servers)
            and {s.get('status') for s in servers}=={'Online','Offline'}
            and len({s.get('id') for s in servers})==2
            and all(s.get('id') and s.get('name') and s.get('version') for s in servers)
            and len({s.get('name') for s in servers})==1
            and len({s.get('version') for s in servers})==1)

def disable():
    c=json.loads(CREDS.read_text())
    session=request('/rest/v4/login/sessions',method='POST',body={'username':c['username'],'password':c['password'],'setCookie':False})
    token=session['token']
    try:
        servers=request('/rest/v3/servers',token)
        if not isinstance(servers,list) or not ((len(servers)==1 and isinstance(servers[0],dict)) or safe_pair(servers)):
            raise ValueError('automatic disable limited to a single-server site')
        server_id=next(s['id'] for s in servers if s.get('status')=='Online') if len(servers)==2 else servers[0].get('id')
        if not server_id:raise ValueError('server identity missing')
        base='/rest/v3/servers/'+str(server_id)+'/storages'
        entries=request(base,token)
        if not isinstance(entries,list):
            raise ValueError('unexpected storage inventory')
        if len(servers)==2:
            if any(request('/rest/v3/servers/'+str(s['id'])+'/storages',token) != [] for s in servers):
                raise ValueError('all server storages must be empty')
        if not entries:
            devices=request('/rest/v4/devices/',token)
            if not isinstance(devices,list) or devices:
                raise ValueError('zero-storage commissioning requires zero devices')
            print('PASS: no storage records and no cameras; no storage writes to disable')
            return
        if len(entries)!=1:
            raise ValueError('automatic disable limited to one preexisting storage')
        record=entries[0]
        if record.get('status')!='Offline' or not record.get('id'):
            raise ValueError('storage is online or lacks identifier')
        if record.get('isUsedForWriting') is True:
            request(base+'/'+str(record['id']),token,method='PATCH',body={'isUsedForWriting':False})
        elif record.get('isUsedForWriting') is not False:
            raise ValueError('storage write assignment cannot be established')
        refreshed=request(base,token)
        if (not isinstance(refreshed,list) or len(refreshed)!=1 or
            refreshed[0].get('status')!='Offline' or refreshed[0].get('isUsedForWriting') is not False):
            raise ValueError('storage write disable could not be verified')
        print('PASS: the sole offline storage has recording writes disabled')
    finally:
        try:request('/rest/v4/login/sessions/'+str(token),token,method='DELETE')
        except (OSError,ValueError,KeyError):pass

if __name__=='__main__':
    try:disable()
    except (OSError,ValueError,KeyError,TypeError) as e:
        print('REFUSED: fresh-install recording write assignment not verified ('+type(e).__name__+')',file=sys.stderr)
        sys.exit(42)
