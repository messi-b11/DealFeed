"""Exercise the installed entry point's actual archive guard without host mutation."""
import hashlib
import io
import shlex
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / 'scripts/activate-release.sh').read_text()
GUARD = SCRIPT.split('# BEGIN ARCHIVE_VALIDATION_PYTHON\n', 1)[1].split('# END ARCHIVE_VALIDATION_PYTHON', 1)[0].split("<<'PY'\n", 1)[1].rsplit('\nPY\n', 1)[0]


class ArtifactValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / 'upload.tar.gz'
        self.checksum = self.root / 'upload.sha256'
        self.snapshot = self.root / 'snapshot.tar.gz'
        self.destination = self.root / 'release'
        self.destination.mkdir()

    def artifact(self, extra=None, omit=None, lock='fastapi==0.143.0\n'):
        contents = {
            'backend/app.py': b'example backend',
            'backend/requirements.lock.txt': lock.encode(),
            'scripts/serve_app.py': b'example serving module',
            'out/index.html': b'<!doctype html>hello',
            'out/_next/static/chunk.js': b'example chunk',
        }
        with tarfile.open(self.source, 'w:gz') as bundle:
            for name, content in contents.items():
                if name == omit:
                    continue
                info = tarfile.TarInfo(name)
                info.size = len(content)
                info.mode = 0o7777  # Untrusted permissions must not survive.
                bundle.addfile(info, io.BytesIO(content))
            if extra:
                for info, content in extra:
                    bundle.addfile(info, io.BytesIO(content) if content else None)
        self.checksum.write_text(hashlib.sha256(self.source.read_bytes()).hexdigest() + '\n')

    def validate(self):
        return subprocess.run(
            [sys.executable, '-c', GUARD, str(self.source), str(self.checksum), str(self.snapshot), str(self.destination)],
            capture_output=True, text=True,
        )

    def test_extracts_application_and_normalizes_permissions(self):
        self.artifact()
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.destination / 'out/index.html').read_bytes(), b'<!doctype html>hello')
        self.assertEqual((self.destination / 'out/index.html').stat().st_mode & 0o7777, 0o644)

    def test_rejects_traversal_absolute_and_unexpected_paths(self):
        for name in ['out/../../outside', '/etc/cron.d/application', 'scripts/arbitrary-root.sh', 'venv/bin/python', './out/alias.js']:
            with self.subTest(name=name):
                self.snapshot.unlink(missing_ok=True)
                info = tarfile.TarInfo(name)
                info.size = 1
                self.artifact(extra=[(info, b'x')])
                result = self.validate()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(list(self.destination.iterdir()), [])

    def test_rejects_symlinks_hardlinks_and_devices(self):
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]:
            with self.subTest(kind=kind):
                self.snapshot.unlink(missing_ok=True)
                info = tarfile.TarInfo('out/link')
                info.type = kind
                info.linkname = '/etc/passwd'
                self.artifact(extra=[(info, None)])
                self.assertNotEqual(self.validate().returncode, 0)
                self.assertEqual(list(self.destination.iterdir()), [])

    def test_rejects_missing_required_file(self):
        self.artifact(omit='scripts/serve_app.py')
        self.assertNotEqual(self.validate().returncode, 0)

    def test_rejects_duplicate_members(self):
        info = tarfile.TarInfo('out/index.html')
        info.size = 1
        self.artifact(extra=[(info, b'x')])
        self.assertNotEqual(self.validate().returncode, 0)

    def test_rejects_corrupted_checksum(self):
        self.artifact()
        self.checksum.write_text('0' * 64 + '\n')
        self.assertNotEqual(self.validate().returncode, 0)
        self.assertFalse(any(self.destination.iterdir()))

    def test_rejects_upload_symlink(self):
        self.artifact()
        actual = self.root / 'actual.tar.gz'
        self.source.rename(actual)
        self.source.symlink_to(actual)
        self.assertNotEqual(self.validate().returncode, 0)

    def test_rejects_dependency_options_and_sources(self):
        for lock in ['--index-url https://example.com\n', '-e /tmp/payload\n', 'package @ https://example.com/payload.whl\n', 'fastapi>=0.1\n', '']:
            with self.subTest(lock=lock):
                self.snapshot.unlink(missing_ok=True)
                self.artifact(lock=lock)
                self.assertNotEqual(self.validate().returncode, 0)
                self.assertFalse(any(self.destination.iterdir()))

    def test_client_rejects_command_injection_without_ssh(self):
        result = subprocess.run(['bash', str(ROOT / 'scripts/deploy-release.sh'), 'host;touch /tmp/unwanted', 'archive', 'a' * 40, 'key', 'known'], capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_server_rejects_extra_arguments_before_root_actions(self):
        result = subprocess.run(['bash', str(ROOT / 'scripts/activate-release.sh'), 'a' * 40, 'extra'], capture_output=True)
        self.assertEqual(result.returncode, 2)


class ActivationLifecycleTests(unittest.TestCase):
    """Run the actual shell flow with host paths and privileged commands sandboxed."""
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.app = self.root / 'app'
        self.previous = self.app / 'releases/previous'
        (self.previous / 'out').mkdir(parents=True)
        (self.previous / 'out/index.html').write_text('previous frontend')
        (self.app / 'current').symlink_to(self.previous)
        self.state = self.root / 'state'
        self.state.mkdir()
        (self.state / 'dealfeed.sqlite').touch()
        self.config = self.root / 'dealfeed.env'
        self.config.touch()
        self.uploads = self.root / 'uploads'
        self.uploads.mkdir()
        self.commit = 'a' * 40
        archive = self.uploads / (self.commit + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as bundle:
            for name, content in {
                'backend/app.py': b'example app',
                'backend/requirements.lock.txt': b'fastapi==0.143.0\n',
                'scripts/serve_app.py': b'example server',
                'out/index.html': b'candidate frontend',
            }.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                bundle.addfile(member, io.BytesIO(content))
        (self.uploads / (self.commit + '.sha256')).write_text(hashlib.sha256(archive.read_bytes()).hexdigest())

    def activate(self, mode):
        # The production script has no test-mode bypass or configurable privileged paths.
        # Only this test copy rewrites them, then substitutes fake host commands.
        source = SCRIPT
        for old, new in [
            ('/var/lib/dealfeed-deploy', self.uploads),
            ('/var/lib/dealfeed-release.', self.root / 'snapshot.'),
            ('/var/lib/dealfeed', self.state),
            ('/opt/dealfeed', self.app),
            ('/etc/dealfeed.env', self.config),
            ('/run/lock/dealfeed-release.lock', self.root / 'release.lock'),
        ]:
            source = source.replace(old, str(new))
        source = source.replace('/usr/bin/python3', shlex.quote(sys.executable))
        python = shlex.quote(sys.executable)
        log = shlex.quote(str(self.root / 'restart.log'))
        current_index = shlex.quote(str(self.app / 'current/out/index.html'))
        stubs = f"""
id() {{ printf '0\\n'; }}
flock() {{ :; }}
chown() {{ :; }}
sleep() {{ :; }}
install() {{ mkdir -p "${{!#}}"; }}
readlink() {{ {python} -I -c 'from pathlib import Path; import sys; print(Path(sys.argv[-1]).resolve())' "$@"; }}
mv() {{ {python} -I -c 'import os,sys; os.replace(sys.argv[-2],sys.argv[-1])' "$@"; }}
runuser() {{
  if [[ {shlex.quote(mode)} == build-failure && "$*" == *"-m pip install"* ]]; then return 1; fi
  return 0
}}
systemctl() {{
  printf '%s\\n' "$*" >> {log}
  if [[ {shlex.quote(mode)} == restart-failure && $(wc -l < {log}) -eq 1 ]]; then return 1; fi
}}
curl() {{
  if [[ {shlex.quote(mode)} == health-failure ]]; then return 1; fi
  if [[ "${{!#}}" == */api/health ]]; then
    printf '%s\\n' '{{"status":"ok","storage":"sqlite"}}'
  else
    cat {current_index}
  fi
}}
"""
        source = source.replace('umask 022\n', stubs + '\numask 022\n', 1)
        script = self.root / 'activation-under-test.sh'
        script.write_text(source)
        return subprocess.run(['bash', str(script), self.commit], capture_output=True, text=True, timeout=20)

    def test_success_keeps_candidate_active(self):
        result = self.activate('success')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        active = (self.app / 'current').resolve()
        self.assertNotEqual(active, self.previous)
        self.assertEqual((active / 'source-commit').read_text().strip(), self.commit)
        self.assertEqual((self.app / 'previous-release').read_text().strip(), str(self.previous))
        self.assertEqual((self.root / 'restart.log').read_text().count('restart dealfeed'), 1)

    def test_health_failure_restores_previous_and_exits_failed(self):
        result = self.activate('health-failure')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / 'current').resolve(), self.previous)
        self.assertEqual((self.root / 'restart.log').read_text().count('restart dealfeed'), 2)
        self.assertIn('restoring previous', result.stderr)

    def test_restart_failure_restores_previous(self):
        result = self.activate('restart-failure')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / 'current').resolve(), self.previous)
        self.assertEqual((self.root / 'restart.log').read_text().count('restart dealfeed'), 2)

    def test_build_failure_does_not_switch_or_restart(self):
        result = self.activate('build-failure')
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.app / 'current').resolve(), self.previous)
        self.assertFalse((self.root / 'restart.log').exists())


if __name__ == '__main__':
    unittest.main()
