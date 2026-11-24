# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Exercise a final installer in a fresh test directory on a Windows test account."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.error
import urllib.request
import winreg

from build_installer import compiler
from package_release import ROOT, sha256, verify_folder
from verify_mcp import Client
import verify_portable as desktop

KEY = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\{EFB6315D-091C-4B7C-B04C-BF6C1DF58097}_is1'


def registration():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
    except FileNotFoundError:
        return None
    with key:
        return Path(winreg.QueryValueEx(key, 'InstallLocation')[0]).resolve()


@contextmanager
def running_desktop(program, env):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    base = 'http://127.0.0.1:' + str(port)
    process = subprocess.Popen([program / 'TwinPALS.exe', '--no-browser', '--port', str(port)], cwd=program,
                               env=env, creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 45
        while True:
            try:
                if desktop.request(base, '/api/health')['status'] == 'ok':
                    break
            except (OSError, urllib.error.URLError):
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('Installed desktop failed its health check')
                time.sleep(.15)
        with urllib.request.urlopen(base + '/api/client/connect', timeout=15) as lease:
            for line in lease:
                if line.startswith(b'data: '):
                    desktop.CLIENT_TOKEN = json.loads(line[6:])['token']
                    break
            yield base
            desktop.request(base, '/api/client/close', {'token': desktop.CLIENT_TOKEN})
    finally:
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=20)
        desktop.require_closed_port(port)


def verify(setup, work, previous_setup=None):
    if registration() is not None:
        raise ValueError('Use a disposable Windows account without an existing TwinPALS Setup registration.')
    work.mkdir(parents=True, exist_ok=False)
    profile = work / 'Test Windows profile'
    profile.mkdir()
    data = profile / 'TwinPALS' / 'Data'
    program = work / 'Installed TwinPALS'
    env = dict(os.environ, LOCALAPPDATA=str(profile), TWINPALS_NO_TRAY='1')
    checks = []

    def run(exe, name, *options, success=True):
        log = work / (name + '.log')
        command = [exe, '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-', '/LOG=' + str(log), *options]
        result = subprocess.run(command, timeout=900, cwd=work)
        if (result.returncode == 0) != success:
            raise RuntimeError(f'{name}: code {result.returncode}; inspect {log}')
        checks.append(name)

    def install(exe, name, dest, success=True):
        run(exe, name, '/NOICONS', '/TASKS=', '/DIR=' + str(dest), success=success)

    def uninstall(name):
        if registration() != program or not program.is_relative_to(work):
            raise RuntimeError('Unexpected uninstall location; no uninstaller launched')
        run(program / 'unins000.exe', name)
        if registration() or (program / 'TwinPALS.exe').exists():
            raise RuntimeError('Uninstall registration or owned executable survived')

    # A small genuine earlier Inno installation exercises the stable Windows
    # product identity before the first published TwinPALS installer exists.
    older = previous_setup
    if older is None:
        prior = work / 'prior'
        prior.mkdir()
        include = prior / 'payload.iss'
        include.write_text(f'Source: "{ROOT / "LICENSE"}"; DestDir: "{{app}}"\n', encoding='utf-8-sig')
        subprocess.run([compiler(), '/Q', '/DProductVersion=0.0.1', '/DPayloadList=' + str(include),
                        '/O' + str(prior), ROOT / 'native/windows/installer/TwinPALS.iss'], check=True)
        older = prior / 'TwinPALS-setup.exe'
    occupied = work / 'Portable copy'
    occupied.mkdir()
    (occupied / 'TwinPALS.exe').write_bytes(b'preserve')
    try:
        install(setup, 'reject-occupied-folder', occupied, False)
        assert (occupied / 'TwinPALS.exe').read_bytes() == b'preserve' and registration() is None
        install(setup, 'clean-install', program)
        assert registration() == program and not data.exists() and not (program / 'data').exists()
        installed = verify_folder(program)
        checks.append('all-installed-payload-hashes')
        mcp = program / 'TwinPALS-MCP.exe'
        config = json.loads(subprocess.check_output([mcp, '--print-config', 'claude-desktop'], env=env))
        args = config['mcpServers']['twinpals']
        assert Path(args['command']) == mcp and Path(args['args'][1]) == data
        with running_desktop(program, env) as base:
            state = desktop.request(base, '/api/m1/state')
            assert Path(state['database_path']) == data / 'catalogue.tpdb'
            material = dict(state['entries'][0], id='installer-test-material', name='Installer test material')
            desktop.request(base, '/api/materials', {'entry': material})
            state['ui']['selection']['bins'] = 173
            desktop.request(base, '/api/session', dict(profile=state['profile'], ui=state['ui'],
                            module2=state['module2'], module3=state['module3'], client_id='setup-qa', sequence=1))
            install(setup, 'block-update-while-running', program, False)
            assert desktop.request(base, '/api/health')['status'] == 'ok'
            run(program / 'unins000.exe', 'block-uninstall-while-running', success=False)
        checks.append('desktop-factory-and-custom-data')
        client = Client([str(mcp), '--no-logon-resume'], env)
        try:
            assert client.call('capabilities')
        finally:
            client.close()
            subprocess.run([mcp, '--shutdown'], env=env, check=True, timeout=45)
        deadline = time.monotonic() + 30
        while (data / 'studies/endpoint.json').exists():
            if time.monotonic() >= deadline:
                raise RuntimeError('The test MCP coordinator did not stop')
            time.sleep(.1)
        queue = data / 'studies/queue.sqlite'
        assert queue.is_file()
        checks.append('installed-mcp-stdio-and-queue')
        stream = data / 'runs' / 'preservation-test.tpstream'
        stream.parent.mkdir(exist_ok=True)
        stream.write_bytes(b'TwinPALS installer retention fixture')
        sample = [data / 'catalogue.tpdb', data / 'app-state.json', queue, stream]
        before = [sha256(p) for p in sample]

        def preserved():
            if [sha256(p) for p in sample] != before:
                raise RuntimeError('A user-owned file changed during the installer operation')

        unknown = program / 'personal-notes.txt'
        unknown.write_bytes(b'keep')
        install(setup, 'same-version-repair', program)
        preserved()
        install(older, 'block-downgrade', program, False)
        preserved()
        uninstall('uninstall-preserves-data')
        preserved()
        assert unknown.read_bytes() == b'keep'
        program = work / 'Reinstalled TwinPALS'
        install(older, 'install-earlier-version', program)
        assert registration() == program
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, KEY, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            previous_version = winreg.QueryValueEx(key, 'DisplayVersion')[0]
        install(setup, 'upgrade-from-earlier-version', program)
        assert registration() == program
        preserved()
        with running_desktop(program, env) as base:
            state = desktop.request(base, '/api/m1/state')
            assert state['ui']['selection']['bins'] == 173
            assert any(row['id'] == 'installer-test-material' for row in state['entries'])
        checks.append('reinstall-opens-original-catalogue-and-settings')
        uninstall('final-uninstall')
        preserved()
        report = dict(status='passed', version=installed['version'], installer_sha256=sha256(setup),
                      verified_program_files=len(installed['files']), user_files_checked=len(sample), checks=checks,
                      previous_version=previous_version, previous_setup_source='release' if previous_setup else 'fixture',
                      previous_setup_sha256=sha256(older), actual_system_runtime='present')
        (work / 'installer-verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        return report
    finally:
        if registration() == program:
            uninstall('test-cleanup')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--previous-setup', type=Path, help='Earlier released TwinPALS installer; a minimal earlier-version fixture is used when omitted')
    parser.add_argument('--work', type=Path, required=True, help='New directory for test program, data, logs and report')
    options = parser.parse_args()
    prior = options.previous_setup.resolve(strict=True) if options.previous_setup else None
    print(json.dumps(verify(options.setup.resolve(), options.work.resolve(), prior), indent=2))

