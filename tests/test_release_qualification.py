import importlib.util
import pathlib
import tempfile
import unittest
from unittest import mock
ROOT=pathlib.Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('qualification',ROOT/'tools/qualify-development.py')
qualification=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(qualification)
class DevelopmentQualification(unittest.TestCase):
    def test_policy_passes_but_does_not_certify(self):
        self.assertTrue(all(qualification.check().values()))
        self.assertNotIn('certified_for_unraid_fresh_install',qualification.check())
    def test_installer_xml_would_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            (fake/'templates').mkdir()
            (fake/'templates'/'dwspectrum.xml').write_text('<Container version="2"/>')
            with mock.patch.object(qualification,'ROOT',fake):
                # Copy only inputs actually required by the checks; do not create installs.
                import shutil
                shutil.copy2(ROOT/'compose.yaml',fake/'compose.yaml')
                for name in qualification.MANDATORY:
                    dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
                shutil.copy2(ROOT/'scripts/fresh-install.py',fake/'scripts/fresh-install.py')
                shutil.copy2(ROOT/'scripts/disable-fresh-storage-writing.py',fake/'scripts/disable-fresh-storage-writing.py')
                checks=qualification.check()
            self.assertFalse(checks['no_unsafe_ca_docker_template'])

    def test_nested_container_template_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            import shutil
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            shutil.copy2(ROOT/'compose.yaml',fake/'compose.yaml')
            nested=fake/'other'/'nested';nested.mkdir(parents=True)
            (nested/'container.xml').write_text('<Container version="2"/>')
            with mock.patch.object(qualification,'ROOT',fake):
                self.assertFalse(qualification.check()['no_unsafe_ca_docker_template'])
    def test_privilege_escalation_is_rejected(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            data=yaml.safe_load((ROOT/'compose.yaml').read_text())
            for mutation in ({'privileged':True},{'cap_add':['SYS_ADMIN']},{'devices':['/dev/kvm:/dev/kvm']},{'network_mode':'host'},{'pid':'host'},{'use_api_socket':True}):
                modified=yaml.safe_load((ROOT/'compose.yaml').read_text())
                modified['services']['dwspectrum'].update(mutation)
                (fake/'compose.yaml').write_text(yaml.safe_dump(modified))
                with mock.patch.object(qualification,'ROOT',fake):
                    self.assertFalse(qualification.check()['privilege_boundary'],str(mutation))

    def test_second_service_is_rejected_even_if_it_has_no_profile(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            doc=yaml.safe_load((ROOT/'compose.yaml').read_text())
            doc['services']['privileged-sidecar']={'image':'alpine:3','privileged':True}
            (fake/'compose.yaml').write_text(yaml.safe_dump(doc))
            with mock.patch.object(qualification,'ROOT',fake):
                checks=qualification.check()
                self.assertFalse(checks['single_service_only'])
                self.assertFalse(checks['privilege_boundary'])

    def test_external_include_rejected(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            doc=yaml.safe_load((ROOT/'compose.yaml').read_text())
            doc['include']=['sidecar.yaml']
            (fake/'compose.yaml').write_text(yaml.safe_dump(doc))
            with mock.patch.object(qualification,'ROOT',fake):
                self.assertFalse(qualification.check()['single_service_only'])
    def test_interpolated_socket_option_rejected(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            doc=yaml.safe_load((ROOT/'compose.yaml').read_text())
            doc['services']['dwspectrum']['use_api_socket']='${USE_API_SOCKET:-false}'
            (fake/'compose.yaml').write_text(yaml.safe_dump(doc))
            with mock.patch.object(qualification,'ROOT',fake):
                checks=qualification.check()
                self.assertFalse(checks['static_compose_manifest'])
                self.assertFalse(checks['privilege_boundary'])

    def test_service_extends_and_unbraced_interpolation_rejected(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            for mutation in ({'extends':{'file':'other.yml','service':'base'}},{'privileged':'$PRIVILEGED'},{'use_api_socket':'$SOCKET'}):
                doc=yaml.safe_load((ROOT/'compose.yaml').read_text())
                doc['services']['dwspectrum'].update(mutation)
                (fake/'compose.yaml').write_text(yaml.safe_dump(doc))
                with mock.patch.object(qualification,'ROOT',fake):
                    checks=qualification.check()
                    self.assertFalse(checks['static_compose_manifest'],str(mutation))
                    self.assertFalse(checks['privilege_boundary'],str(mutation))

    def test_lifecycle_hooks_and_inherited_volumes_rejected(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            for mutation in ({'post_start':[{'command':'id','privileged':True}]},
                             {'pre_stop':[{'command':'id','privileged':True}]},
                             {'volumes_from':['container:unapproved:rw']}):
                doc=yaml.safe_load((ROOT/'compose.yaml').read_text())
                doc['services']['dwspectrum'].update(mutation)
                (fake/'compose.yaml').write_text(yaml.safe_dump(doc))
                with mock.patch.object(qualification,'ROOT',fake):
                    checks=qualification.check()
                    self.assertFalse(checks['no_lifecycle_hooks_or_inherited_mounts'],str(mutation))
                    self.assertFalse(checks['privilege_boundary'],str(mutation))

    def test_allowlist_blocks_gpu_and_future_unknown_options(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            for mutation in ({'gpus':'all'},{'deploy':{'resources':{'reservations':{'devices':[{'capabilities':['gpu']}]}}}}, {'unknown_future_privilege':True}):
                doc=yaml.safe_load((ROOT/'compose.yaml').read_text())
                doc['services']['dwspectrum'].update(mutation)
                (fake/'compose.yaml').write_text(yaml.safe_dump(doc))
                with mock.patch.object(qualification,'ROOT',fake):
                    checks=qualification.check()
                    self.assertFalse(checks['approved_compose_keys'],str(mutation))
                    self.assertFalse(checks['privilege_boundary'],str(mutation))
    def test_extra_volume_bind_field_is_rejected(self):
        import shutil,yaml
        with tempfile.TemporaryDirectory() as temp:
            fake=pathlib.Path(temp)
            for name in qualification.MANDATORY:
                dst=fake/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,dst)
            doc=yaml.safe_load((ROOT/'compose.yaml').read_text())
            doc['services']['dwspectrum']['volumes'][0]['volume']={'nocopy':False}
            (fake/'compose.yaml').write_text(yaml.safe_dump(doc))
            with mock.patch.object(qualification,'ROOT',fake):
                self.assertFalse(qualification.check()['approved_volume_keys'])
