"""Real archive/credential handling with disposable paths and no production tools."""
import importlib.util
import io
import json
import runpy
from pathlib import Path
import stat
import tarfile
import tempfile
import unittest
import urllib.error
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
def module(name,filename):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/filename)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod);return mod

class FreshFlowSecurityTests(unittest.TestCase):
    def test_storage_api_retries_transient_urlerror_only(self):
        tool=module('storage_writer_retry','disable-fresh-storage-writing.py')
        success=io.BytesIO(b'{"ok":true}')
        transient=tool.urllib.error.URLError('not ready')
        with mock.patch.object(tool.urllib.request,'urlopen',side_effect=[transient,success]) as call, \
             mock.patch.object(tool.time,'sleep') as sleep:
            self.assertEqual(tool.request('/ready'),{'ok':True})
        self.assertEqual(call.call_count,2)
        sleep.assert_called_once_with(1)

    def test_storage_api_does_not_retry_http_errors(self):
        tool=module('storage_writer_http','disable-fresh-storage-writing.py')
        denied=tool.urllib.error.HTTPError('https://127.0.0.1',401,'Unauthorized',None,None)
        with mock.patch.object(tool.urllib.request,'urlopen',side_effect=denied) as call, \
             mock.patch.object(tool.time,'sleep') as sleep:
            with self.assertRaises(tool.urllib.error.HTTPError):
                tool.request('/denied')
        self.assertEqual(call.call_count,1)
        sleep.assert_not_called()

    def test_matching_offline_and_online_servers_accepted(self):
        tool=module('storage_writer_pair_good','disable-fresh-storage-writing.py')
        good=[{'id':'a','name':'n','version':'v','status':'Offline'},
              {'id':'b','name':'n','version':'v','status':'Online'}]
        self.assertTrue(tool.safe_pair(good))
        for change in ({'name':'other'},{'version':'other'},{'status':'Offline'},{'id':'a'}):
            bad=[dict(good[0]),dict(good[1])]
            bad[1].update(change)
            self.assertFalse(tool.safe_pair(bad))
        self.assertFalse(tool.safe_pair(good+[dict(good[1],id='c')]))

    def test_matching_server_pair_without_storage_and_cameras(self):
        tool=module('storage_writer_pair_empty','disable-fresh-storage-writing.py')
        servers=[{'id':'a','name':'n','version':'v','status':'Offline'},
                 {'id':'b','name':'n','version':'v','status':'Online'}]
        seen=[]
        def fake(path,token=None,method='GET',body=None):
            seen.append((path,method))
            if path=='/rest/v4/login/sessions':return {'token':'t'}
            if path=='/rest/v3/servers':return servers
            if path.endswith('/storages'):return []
            if path=='/rest/v4/devices/':return []
            return None
        tool.request=fake
        with unittest.mock.patch.object(tool,'CREDS') as f:
            f.read_text.return_value='{"username":"u","password":"p"}'
            tool.disable()
        self.assertIn(('/rest/v3/servers/a/storages','GET'),seen)
        self.assertIn(('/rest/v3/servers/b/storages','GET'),seen)
        self.assertFalse(any(method=='PATCH' for _,method in seen))

    def test_matching_server_pair_with_camera_is_rejected(self):
        tool=module('storage_writer_pair_camera','disable-fresh-storage-writing.py')
        servers=[{'id':'a','name':'n','version':'v','status':'Offline'},
                 {'id':'b','name':'n','version':'v','status':'Online'}]
        def fake(path,token=None,method='GET',body=None):
            if path=='/rest/v4/login/sessions':return {'token':'t'}
            if path=='/rest/v3/servers':return servers
            if path.endswith('/storages'):return []
            if path=='/rest/v4/devices/':return [{'id':'camera'}]
            return None
        tool.request=fake
        with unittest.mock.patch.object(tool,'CREDS') as f:
            f.read_text.return_value='{"username":"u","password":"p"}'
            with self.assertRaisesRegex(ValueError,'zero-storage commissioning'):tool.disable()

    def test_matching_server_pair_with_stale_storage_is_rejected(self):
        tool=module('storage_writer_pair_storage','disable-fresh-storage-writing.py')
        servers=[{'id':'a','name':'n','version':'v','status':'Offline'},
                 {'id':'b','name':'n','version':'v','status':'Online'}]
        def fake(path,token=None,method='GET',body=None):
            if path=='/rest/v4/login/sessions':return {'token':'t'}
            if path=='/rest/v3/servers':return servers
            if path.endswith('/a/storages'):return [{'id':'legacy'}]
            if path.endswith('/b/storages'):return []
            return None
        tool.request=fake
        with unittest.mock.patch.object(tool,'CREDS') as f:
            f.read_text.return_value='{"username":"u","password":"p"}'
            with self.assertRaisesRegex(ValueError,'all server storages must be empty'):tool.disable()

    def test_runtime_audit_retries_transient_api_startup(self):
        script=ROOT/'scripts'/'check-record-storage.py'
        attempts={'login':0}
        def fake_urlopen(req,context=None,timeout=None):
            url=req.full_url
            method=req.get_method()
            if url.endswith('/rest/v4/login/sessions') and method=='POST':
                attempts['login']+=1
                if attempts['login']==1:
                    raise urllib.error.URLError('not ready')
                payload={'token':'t'}
            elif url.endswith('/rest/v4/devices/'):
                payload=[]
            elif url.endswith('/rest/v3/servers'):
                payload=[{'id':'a','name':'n','version':'v','status':'Online'}]
            elif url.endswith('/rest/v4/servers/a/storages'):
                payload=[]
            elif '/rest/v4/login/sessions/' in url and method=='DELETE':
                payload={}
            else:
                raise AssertionError((method,url))
            return io.StringIO(json.dumps(payload))
        output=io.StringIO()
        with mock.patch.object(Path,'read_text',return_value='{"username":"u","password":"p"}'), \
             mock.patch('urllib.request.urlopen',side_effect=fake_urlopen), \
             mock.patch('time.sleep') as sleep, \
             mock.patch('sys.stdout',output):
            runpy.run_path(str(script),run_name='__main__')
        self.assertEqual(attempts['login'],2)
        sleep.assert_called_once_with(1)
        self.assertIn('"server_count": 1',output.getvalue())

    def test_runtime_audit_duplicate_pair_exception_requires_empty_inventory(self):
        script=ROOT/'scripts'/'check-record-storage.py'
        servers=[{'id':'a','name':'n','version':'v','status':'Offline'},
                 {'id':'b','name':'n','version':'v','status':'Online'}]
        def fake_urlopen(req,context=None,timeout=None):
            url=req.full_url
            method=req.get_method()
            if url.endswith('/rest/v4/login/sessions') and method=='POST':
                payload={'token':'t'}
            elif url.endswith('/rest/v4/devices/'):
                payload=[]
            elif url.endswith('/rest/v3/servers'):
                payload=servers
            elif url.endswith('/rest/v4/servers/a/storages'):
                payload=[{'id':'legacy','status':'Offline','isUsedForWriting':False,'isWritable':False}]
            elif url.endswith('/rest/v4/servers/b/storages'):
                payload=[]
            elif '/rest/v4/login/sessions/' in url and method=='DELETE':
                payload={}
            else:
                raise AssertionError((method,url))
            return io.StringIO(json.dumps(payload))
        with mock.patch.object(Path,'read_text',return_value='{"username":"u","password":"p"}'), \
             mock.patch('urllib.request.urlopen',side_effect=fake_urlopen):
            with self.assertRaisesRegex(RuntimeError,'Multi-server inventory'):
                runpy.run_path(str(script),run_name='__main__')

    def test_no_storage_and_no_cameras_is_commissioning_safe(self):
        tool=module('storage_writer_empty','disable-fresh-storage-writing.py')
        calls=[]
        def fake(path,token=None,method='GET',body=None):
            calls.append((path,method,body))
            if path=='/rest/v4/login/sessions':return {'token':'t'}
            if path=='/rest/v3/servers':return [{'id':'s'}]
            if path=='/rest/v3/servers/s/storages':return []
            if path=='/rest/v4/devices/':return []
            return None
        tool.request=fake
        with unittest.mock.patch.object(tool,'CREDS') as f:
            f.read_text.return_value='{"username":"u","password":"p"}'
            tool.disable()
        self.assertFalse(any(method=='PATCH' for _,method,_ in calls))

    def test_no_storage_with_camera_is_rejected(self):
        tool=module('storage_writer_empty_camera','disable-fresh-storage-writing.py')
        def fake(path,token=None,method='GET',body=None):
            if path=='/rest/v4/login/sessions':return {'token':'t'}
            if path=='/rest/v3/servers':return [{'id':'s'}]
            if path=='/rest/v3/servers/s/storages':return []
            if path=='/rest/v4/devices/':return [{'id':'camera'}]
            return None
        tool.request=fake
        with unittest.mock.patch.object(tool,'CREDS') as f:
            f.read_text.return_value='{"username":"u","password":"p"}'
            with self.assertRaises(ValueError):tool.disable()

    def test_credential_enrollment_is_nonclobbering_and_private(self):
        tool=module('credential_enroll','enroll-api-credentials.py')
        with tempfile.TemporaryDirectory() as td:
            d=Path(td)/'config';d.mkdir()
            target=d/'secrets'/'dw-api.json'
            with mock.patch.object(tool.os,'geteuid',return_value=0):
                tool.enroll(target,'admin','EXAMPLE_TEST_ONLY')
                self.assertEqual(stat.S_IMODE(target.stat().st_mode),0o600)
                self.assertEqual(stat.S_IMODE(target.parent.stat().st_mode),0o700)
                self.assertEqual(json.loads(target.read_text())['password'],'EXAMPLE_TEST_ONLY')
                with self.assertRaisesRegex(ValueError,'already exists'):
                    tool.enroll(target,'admin','OVERWRITE_NOT_ALLOWED')
    def test_write_disable_only_single_offline_storage(self):
        tool=module('storage_writer','disable-fresh-storage-writing.py')
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'creds.json';c.write_text('{"username":"test","password":"EXAMPLE"}')
            responses=[{'token':'TEST'},[{'id':'server-1'}],
                       [{'id':'disk-1','status':'Offline','isUsedForWriting':True}],None,
                       [{'id':'disk-1','status':'Offline','isUsedForWriting':False}],None]
            calls=[]
            def req(*args,**kwargs):calls.append((args,kwargs));return responses.pop(0)
            with mock.patch.object(tool,'CREDS',c),mock.patch.object(tool,'request',side_effect=req):
                tool.disable()
            self.assertEqual(len([x for x in calls if x[1].get('method')=='PATCH']),1)
            self.assertEqual(calls[3][1]['body'],{'isUsedForWriting':False})
    def test_storage_disable_refuses_multiserver_scope(self):
        tool=module('storage_writer_no_write','disable-fresh-storage-writing.py')
        with tempfile.TemporaryDirectory() as td:
            c=Path(td)/'creds.json';c.write_text('{"username":"test","password":"EXAMPLE"}')
            calls=[]
            responses=[{'token':'TEST'},[{'id':'one'},{'id':'two'}],None]
            def req(*args,**kwargs):calls.append(kwargs.get('method','GET'));return responses.pop(0)
            with mock.patch.object(tool,'CREDS',c),mock.patch.object(tool,'request',side_effect=req):
                with self.assertRaisesRegex(ValueError,'single-server'):tool.disable()
            self.assertNotIn('PATCH',calls)
    def test_offline_restore_extracts_and_protects_secrets(self):
        tool=module('restore_config','restore-config.py')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);dest=root/'config';dest.mkdir()
            archive=root/'backup.tar.gz'
            with tarfile.open(archive,'w:gz') as tf:
                for name in ('config','config/etc','config/var','config/secrets'):
                    info=tarfile.TarInfo(name);info.type=tarfile.DIRTYPE;tf.addfile(info)
                for name,content in (('config/.initialized',b'1'),('config/secrets/dw-api.json',b'EXAMPLE')):
                    info=tarfile.TarInfo(name);info.size=len(content);tf.addfile(info,io.BytesIO(content))
            with mock.patch.object(tool,'REQUESTS',root/'isolated-requests'),mock.patch.object(tool,'LOCK',root/'lock'),mock.patch.object(tool,'validate_quarantine'),mock.patch.object(tool,'stopped_or_absent'),mock.patch.object(tool.os,'geteuid',return_value=0),mock.patch.object(tool.os,'chown'):
                tool.restore(archive,dest)
            self.assertEqual((dest/'.initialized').read_bytes(),b'1')
            self.assertEqual((dest/'secrets/dw-api.json').read_bytes(),b'EXAMPLE')
            self.assertEqual(stat.S_IMODE((dest/'secrets/dw-api.json').stat().st_mode),0o600)
            self.assertEqual(stat.S_IMODE((dest/'secrets').stat().st_mode),0o700)
            self.assertFalse(list(root.glob('.dw-restore-*')))

if __name__=='__main__':unittest.main()

class ProvisioningAndBuildTests(unittest.TestCase):
    def test_resume_validates_pristine_marked_volume(self):
        tool=module('fresh_resume','fresh-install.py')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);cache=root/'cache';cache.mkdir();target=cache/'quarantine';target.mkdir()
            img=cache/'storage.ext4'
            with img.open('wb') as f:f.truncate(tool.CAPACITY)
            for d in tool.REQUIRED:(target/d).mkdir()
            (target/tool.MARKER).write_text(tool.MARKER_CONTENT)
            def commands(*args,**kwargs):
                if args[0]=='lsattr':return '----------------C---- '+str(args[-1])
                if 'FSTYPE' in args:return 'ext4'
                if 'SOURCE' in args:return '/dev/loop17'
                if 'BACK-FILE' in args:return str(img)
                raise AssertionError('unexpected command')
            with mock.patch.object(tool,'CACHE',cache),mock.patch.object(tool,'TARGET',target),mock.patch.object(tool,'IMAGE',img),mock.patch.object(tool,'mounted',return_value=True),mock.patch.object(tool,'assert_reserved_space'),mock.patch.object(tool.os,'geteuid',return_value=0),mock.patch.object(tool,'run',side_effect=commands):
                tool.check_resume()
                (target/'config/.initialized').write_text('existing-data')
                with self.assertRaisesRegex(tool.Refused,'no longer pristine'):tool.check_resume()
    def test_local_vendor_build_returns_immutable_image_id_only(self):
        tool=module('builder','build-official-image.py')
        expected='sha256:'+'a'*64
        with mock.patch.object(tool.subprocess,'run') as cmd, mock.patch.object(tool.subprocess,'check_output',return_value=expected+'\n'):
            self.assertEqual(tool.build(ROOT/'versions/6.1.2.42997.env'),expected)
            self.assertIn('DW_SHA256=', ' '.join(cmd.call_args.args[0]))
            self.assertEqual(cmd.call_args.kwargs['stdout'],tool.sys.stderr)
    def test_compose_can_use_immutable_local_image(self):
        source=(ROOT/'scripts/private-setup.sh').read_text()
        self.assertIn("startswith('sha256:')",source)
        self.assertIn('DW_COMPOSE_SOURCE',source)

class PreMarkerRecoveryTests(unittest.TestCase):
    def test_recover_only_pristine_interrupted_provisioning(self):
        tool=module('recover_module','fresh-install.py')
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td);image=cache/'storage.ext4'
            with image.open('wb') as fd:fd.truncate(tool.CAPACITY)
            target=cache/'quarantine';target.mkdir()
            (target/'lost+found').mkdir()
            (target/'config').mkdir()
            def cmd(*args):
                if args[0]=='lsattr':return '----------------C---- '+str(args[-1])
                if 'FSTYPE' in args:return 'ext4'
                if 'SOURCE' in args:return '/dev/loop99'
                if 'BACK-FILE' in args:return str(image)
                raise AssertionError(args)
            with mock.patch.object(tool,'CACHE',cache),mock.patch.object(tool,'IMAGE',image),mock.patch.object(tool,'TARGET',target),mock.patch.object(tool.os,'geteuid',return_value=0),mock.patch.object(tool.os,'chown'),mock.patch.object(tool,'mounted',return_value=True),mock.patch.object(tool,'assert_reserved_space'),mock.patch.object(tool,'run',side_effect=cmd):
                tool.recover_pre_marker()
                self.assertEqual((target/tool.MARKER).read_text(),tool.MARKER_CONTENT)
                for name in tool.REQUIRED:self.assertTrue((target/name).is_dir())
                (target/tool.MARKER).unlink()
                (target/'config/user-data').write_text('PROTECT')
                with self.assertRaises(tool.Refused):tool.recover_pre_marker()
                self.assertEqual((target/'config/user-data').read_text(),'PROTECT')

class PreformatPreservationTests(unittest.TestCase):
    def test_unmountable_image_is_preserved_without_deletion(self):
        tool=module('preformat_preserve','fresh-install.py')
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td);img=cache/'storage.ext4';target=cache/'quarantine';target.mkdir()
            with img.open('wb') as fd:fd.truncate(tool.CAPACITY)
            original=img.stat().st_size
            fake=type('Blkid',(),{'returncode':2,'stdout':''})()
            def mount(q):return q==cache
            with mock.patch.object(tool,'CACHE',cache),mock.patch.object(tool,'IMAGE',img),mock.patch.object(tool,'TARGET',target),mock.patch.object(tool,'mounted',side_effect=mount),mock.patch.object(tool.os,'geteuid',return_value=0),mock.patch.object(tool,'assert_reserved_space'),mock.patch.object(tool,'run',return_value='---------------C---- /test'),mock.patch.object(tool.subprocess,'run',return_value=fake):
                tool.preserve_unmountable_preformat()
            self.assertFalse(img.exists())
            retained=list(cache.glob('storage.ext4.preserved-*'))
            self.assertEqual(len(retained),1)
            self.assertEqual(retained[0].stat().st_size,original)
    def test_detectable_filesystem_is_never_renamed_or_formatted(self):
        tool=module('preformat_refuse','fresh-install.py')
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td);img=cache/'storage.ext4';target=cache/'quarantine';target.mkdir()
            with img.open('wb') as fd:fd.truncate(tool.CAPACITY)
            fake=type('Blkid',(),{'returncode':0,'stdout':'ext4'})()
            with mock.patch.object(tool,'CACHE',cache),mock.patch.object(tool,'IMAGE',img),mock.patch.object(tool,'TARGET',target),mock.patch.object(tool,'mounted',side_effect=lambda q:q==cache),mock.patch.object(tool.os,'geteuid',return_value=0),mock.patch.object(tool,'assert_reserved_space'),mock.patch.object(tool,'run',return_value='---------------C---- /test'),mock.patch.object(tool.subprocess,'run',return_value=fake):
                with self.assertRaisesRegex(tool.Refused,'detectable filesystem'):tool.preserve_unmountable_preformat()
            self.assertTrue(img.exists())

class PostformatReservationTests(unittest.TestCase):
    def test_provision_reserves_twice_and_mounts_only_after_checks(self):
        tool=module('fresh_reservation_success','fresh-install.py')
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); img=base/'volume'/'storage.ext4'; target=base/'quarantine'
            calls=[]
            def fake_run(*args):
                calls.append(args)
                if args[0]=='lsattr':return '---------------C----- '+str(img)
                if 'FSTYPE' in args:return 'ext4'
                if 'SOURCE' in args:return '/dev/loop4'
                if 'BACK-FILE' in args:return str(img)
                if args[0]=='df':return 'Size\n8369172480'
                return ''
            with mock.patch.object(tool,'IMAGE',img),mock.patch.object(tool,'TARGET',target),mock.patch.object(tool,'check_cache'),mock.patch.object(tool,'run',side_effect=fake_run),mock.patch.object(tool,'assert_reserved_space') as reserve,mock.patch.object(tool.os,'posix_fallocate') as allocate,mock.patch.object(tool.os,'chown'):
                tool.provision()
            self.assertEqual(allocate.call_count,2)
            reserve.assert_called_once()
            self.assertEqual((target/tool.MARKER).read_text(),tool.MARKER_CONTENT)
            self.assertLess(next(i for i,x in enumerate(calls) if x[0]=='mkfs.ext4'),next(i for i,x in enumerate(calls) if x[0]=='mount'))

    def test_postformat_reservation_failure_preserves_file_without_mount(self):
        tool=module('fresh_reservation_failure','fresh-install.py')
        with tempfile.TemporaryDirectory() as td:
            base=Path(td); img=base/'volume'/'storage.ext4'; target=base/'quarantine'
            calls=[]
            def fake_run(*args):
                calls.append(args)
                if args[0]=='lsattr':return '---------------C----- '+str(img)
                return ''
            with mock.patch.object(tool,'IMAGE',img),mock.patch.object(tool,'TARGET',target),mock.patch.object(tool,'check_cache'),mock.patch.object(tool,'run',side_effect=fake_run),mock.patch.object(tool.os,'posix_fallocate',side_effect=[None,OSError('ENOSPC')]):
                with self.assertRaises(OSError):tool.provision()
            self.assertTrue(img.exists())
            self.assertFalse(any(x[0]=='mount' for x in calls))
