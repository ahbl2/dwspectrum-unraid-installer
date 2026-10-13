#!/usr/bin/env python3
"""Read-only local DW Spectrum API audit. Secrets are read only from the private host vault."""
import json
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = 'https://127.0.0.1:7203'
CONTEXT = ssl._create_unverified_context()  # localhost with DW's self-signed TLS certificate
secrets = json.loads(Path('/mnt/cache/dwspectrum-quarantine/config/secrets/dw-api.json').read_text())


def request(path, *, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    kwargs = {'headers': headers}
    if body is not None:
        kwargs['data'] = json.dumps(body).encode()
        kwargs['method'] = 'POST'
    req = urllib.request.Request(BASE + path, **kwargs)
    for attempt in range(12):
        try:
            with urllib.request.urlopen(req, context=CONTEXT, timeout=5) as response:
                return json.load(response)
        except urllib.error.HTTPError:
            raise
        except urllib.error.URLError:
            if attempt == 11:
                raise
            time.sleep(1)

session = request('/rest/v4/login/sessions', body={
    'username': secrets['username'], 'password': secrets['password'], 'setCookie': False,
})
token = session['token']
try:
    devices = request('/rest/v4/devices/', token=token)
    servers = request('/rest/v3/servers', token=token)
    if not isinstance(servers, list) or not servers or any(not isinstance(server, dict) or not server.get('id') for server in servers):
        raise RuntimeError('Unexpected server inventory')
    # Bound worst-case audit duration while failing closed for unexpectedly large sites.
    if len(servers) > 12:
        raise RuntimeError('Server inventory exceeds audited limit of 12')
    storages = []
    for server in servers:
        records = request('/rest/v4/servers/' + str(server['id']) + '/storages', token=token)
        if not isinstance(records, list):
            raise RuntimeError('Unexpected storage record type')
        storages.extend(records)
    if not isinstance(devices, list) or not isinstance(storages, list):
        raise RuntimeError('Unexpected device or storage data')
    safe_pair = (len(servers)==2 and {s.get('status') for s in servers}=={'Online','Offline'}
                 and len({s.get('id') for s in servers})==2
                 and all(s.get('name') and s.get('version') for s in servers)
                 and len({s.get('name') for s in servers})==1
                 and len({s.get('version') for s in servers})==1)
    if len(servers) != 1:
        if not safe_pair or storages or devices:
            raise RuntimeError('Multi-server inventory is outside the empty duplicate-server commissioning exception')
    elif not storages and devices:
        raise RuntimeError('Zero-storage mode requires zero devices')
    print('DW_AUDIT_JSON=' + json.dumps({'devices': [
        {'id': d.get('id'), 'recording_enabled': d.get('schedule',{}).get('isEnabled')}
        for d in devices], 'server_count': len(servers), 'safe_pair': safe_pair, 'storages': [
        {'id': st.get('id'), 'path': st.get('path'), 'status': st.get('status'),
         'isEnabled': st.get('isEnabled'), 'isWritable': st.get('isWritable'),
         'isUsedForWriting': st.get('isUsedForWriting')}
        for st in storages]}))
finally:
    # Never allow cleanup errors to hide the audit outcome.
    try:
        url = BASE + '/rest/v4/login/sessions/' + str(token)
        req = urllib.request.Request(url, headers={'Authorization':'Bearer '+token}, method='DELETE')
        with urllib.request.urlopen(req, context=CONTEXT, timeout=10):
            pass
    except (KeyError, OSError, ValueError):
        pass
