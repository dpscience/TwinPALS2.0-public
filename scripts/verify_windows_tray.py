# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Exercise the portable notification area with real services and an isolated browser receiver."""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import socket
import struct
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit
from xml.etree import ElementTree

from verify_mcp import Client, HTTP, ROOT, wait_until


def check_icon_resources(folder):
    """Compare every embedded Windows image to its payload in the published ICO."""
    import pefile
    ico=(folder/'frontend/dist/favicon.ico').read_bytes()
    count=struct.unpack_from('<H',ico,4)[0]
    expected=set()
    for index in range(count):
        size,offset=struct.unpack_from('<II',ico,6+16*index+8)
        expected.add(ico[offset:offset+size])
    assert count>=8
    for exe in ('TwinPALS.exe','TwinPALS-MCP.exe','_internal/TwinPALS.Tray.exe'):
        with pefile.PE(str(folder/exe),fast_load=True) as image:
            image.parse_data_directories([pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])
            icons=next(r for r in image.DIRECTORY_ENTRY_RESOURCE.entries if r.id==3)
            payloads=set()
            for child in icons.directory.entries:
                node=child.directory.entries[0].data.struct
                payloads.add(image.get_data(node.OffsetToData,node.Size))
            assert expected <= payloads, exe
            if exe.endswith('.Tray.exe'):
                manifest=next(r for r in image.DIRECTORY_ENTRY_RESOURCE.entries if r.id==24)
                node=manifest.directory.entries[0].directory.entries[0].data.struct
                xml=ElementTree.fromstring(image.get_data(node.OffsetToData,node.Size))
                assert xml.findtext('.//{*}dpiAwareness').split(',')[0]=='PerMonitorV2'


def answer_dialog(pid, yes):
    user = ctypes.windll.user32
    matches = []
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @callback
    def inspect(hwnd, _):
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            title = ctypes.create_unicode_buffer(160)
            user.GetWindowTextW(hwnd, title, 160)
            if title.value.startswith('TwinPALS 2.0 · Stop '):
                matches.append(hwnd)
        return True

    user.EnumWindows(inspect, 0)
    if matches:
        return bool(user.PostMessageW(matches[0], 0x111, 6 if yes else 7, 0))
    return False


def kill_test_process(pid, expected):
    """Keep the process handle through identity verification and simulated failure."""
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    handle = wintypes.HANDLE(kernel.OpenProcess(0x1001, False, pid))
    if not handle:
        return
    try:
        path = ctypes.create_unicode_buffer(32000)
        size = wintypes.DWORD(len(path))
        assert kernel.QueryFullProcessImageNameW(handle,0,path,ctypes.byref(size))
        assert Path(path.value).resolve() == expected.resolve(), path.value
        assert kernel.TerminateProcess(handle, 41)
    finally:
        kernel.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    folder = args.folder.resolve()
    check_icon_resources(folder)
    desktop, mcp = folder/'TwinPALS.exe', folder/'TwinPALS-MCP.exe'
    report = args.report.resolve()
    workspace = report.parent/('tray-test-'+uuid.uuid4().hex[:8])
    workspace.mkdir(parents=True)
    local = workspace/'local'
    session = wintypes.DWORD()
    assert ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(),ctypes.byref(session)) and session.value
    registrations = local/'TwinPALS/Tray'/str(session.value)
    data = workspace/'data'
    receiver = workspace/'TrayControls.exe'
    icon = ROOT/'frontend/public/favicon.ico'
    compiler = Path(os.environ['SystemRoot'])/'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    subprocess.run([str(compiler),'/nologo','/codepage:65001','/target:winexe','/main:TrayControls',
                    '/win32manifest:'+str(ROOT/'native/windows/TwinPALSTray.manifest'),
                    '/reference:System.Windows.Forms.dll','/reference:System.Drawing.dll','/reference:System.Web.Extensions.dll',
                    '/win32icon:'+str(icon),'/out:'+str(receiver),str(ROOT/'native/windows/TwinPALSTray.cs'),
                    str(ROOT/'tests/TrayControls.cs')], check=True)
    opened = workspace/'browser.log'
    env = dict(os.environ, LOCALAPPDATA=str(local), BROWSER='TrayControls.exe %s', TRAY_TEST_OPENED=str(opened),
               PATH=str(workspace)+os.pathsep+os.environ['PATH'], TWINPALS_NO_TRAY='0')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1',0))
        port = sock.getsockname()[1]
    url = f'http://127.0.0.1:{port}'
    base = [str(desktop),'--port',str(port),'--data-dir',str(data)]
    mcp_cmd = [str(mcp),'--no-logon-resume','--data-dir',str(data)]
    flags = subprocess.CREATE_NO_WINDOW
    host_file = registrations/'host.pid'
    checks = []
    subprocess.run([str(receiver),str(report.parent),'--popup',str(folder/'_internal/TwinPALS.Tray.exe')],
                   check=True,env=env,timeout=25)
    checks.append('Packaged notification callbacks: both buttons opened identical native popup sizes in all three service combinations; active status fits and stop commands are last')
    clients, processes = [], []

    def start_desktop():
        print('Starting isolated desktop',flush=True)
        process = subprocess.Popen([*base,'--no-browser'], env=env, creationflags=subprocess.CREATE_NEW_CONSOLE)
        processes.append(process)
        return process

    def connect():
        client = Client(mcp_cmd,env)
        clients.append(client)
        assert Path(client.call('capabilities')['data_directory']) == data
        return client

    def entry(role):
        for file in registrations.glob('*.json'):
            try:
                row=json.loads(file.read_bytes())
                if row['role']==role and row['phase']=='Ready':
                    return row
            except (FileNotFoundError,PermissionError):
                pass

    def host():
        try:
            return int(host_file.read_text())
        except (ValueError,OSError):
            return None

    def click(label):
        print(label,flush=True)
        subprocess.run([str(receiver),str(workspace),str(registrations),label],check=True,timeout=10,env=env)

    def receivers():
        return opened.read_text().splitlines() if opened.exists() else []

    def favicon(base_url):
        for name in ['favicon.svg','favicon.ico']:
            with HTTP.open(base_url+'/'+name,timeout=3) as response:
                assert response.read()==(folder/'frontend/dist'/name).read_bytes()

    try:
        process = start_desktop()
        wait_until(lambda: entry('desktop'),40)
        first_host = wait_until(host,20)
        console_check=('import ctypes,sys; k=ctypes.windll.kernel32; k.FreeConsole(); '
                       'assert k.AttachConsole(int(sys.argv[1])); k.GetConsoleWindow.restype=ctypes.c_void_p; '
                       'window=k.GetConsoleWindow(); assert window and not ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(window)); '
                       'k.FreeConsole()')
        subprocess.run([sys.executable,'-c',console_check,str(process.pid)],creationflags=flags,check=True,timeout=10)
        checks.append('Explorer-style owned console hidden and all icon sizes match across the three PE files')
        with HTTP.open(url+'/api/health') as response:
            assert json.load(response)['status']=='ok'
        favicon(url)
        def attach_window():
            with HTTP.open(url+'/api/client/connect',timeout=5) as stream:
                event=json.loads(stream.readline().decode().removeprefix('data: '))
                assert event['type'] in ('ready','busy')
                return event['type']=='ready'
        assert attach_window()
        # Closing the SSE connection releases the UI lease asynchronously.
        wait_until(attach_window,15)
        click('Open desktop in browser')
        wait_until(lambda: '/ desktop' in receivers(),10)
        subprocess.run(base,check=True,env=env,creationflags=flags,timeout=20)
        wait_until(lambda: receivers().count('/ desktop')==2,10)
        checks.append('Desktop cold start, SSE close/reconnect, menu open and repeated EXE')
        client=connect()
        service=wait_until(lambda: entry('mcp'),35)
        assert host()==first_host and service['notice'] is None
        viewer=client.call('observer_open')['url']
        assert entry('desktop')['port']==port
        assert urlsplit(viewer).hostname=='127.0.0.1' and service['port']==urlsplit(viewer).port
        assert service['port']!=port and urlsplit(viewer).fragment not in json.dumps(service)
        checks.append('Desktop and observer addresses match live HTTP listeners, and the observer credential is absent from tray data')
        favicon(viewer.split('/observe')[0])
        click('Open study observer')
        wait_until(lambda: '/observe viewer' in receivers(),10)
        client.close()
        assert entry('mcp')['pid']==service['pid']
        client=connect()
        spec=dict(request_id='tray-recovery',name='Tray recovery study',steps=[
            dict(key='transport',module=1,changes={'/run/events':250000,'/run/secondary_events':250000})])
        study=client.call('study_submit',**spec)
        def first_study():
            r=entry('mcp') or {}
            notice=r.get('notice') or {}
            return r.get('activity') and notice.get('study')==study['id'] and notice.get('kind')=='started'
        wait_until(first_study,30)
        assert client.call('study_submit',**spec)['id']==study['id']
        subprocess.run([str(receiver),str(report.parent),str(registrations)],check=True,env=env,timeout=15)
        checks.append('Both services share the host, observer, quiet connects and first study notification')
        click('Stop MCP service…')
        wait_until(lambda: answer_dialog(service['pid'],False),15)
        assert client.call('study_status',study_id=study['id'])['runs'][0]['status']=='running'
        click('Stop MCP service…')
        wait_until(lambda: answer_dialog(service['pid'],True),15)
        wait_until(lambda: not (data/'studies/endpoint.json').exists(),45)
        assert process.poll() is None and host()==first_host
        client.close()
        client=connect()
        service=wait_until(lambda: entry('mcp'),35)
        state=wait_until(lambda: next((r for r in client.call('study_status',study_id=study['id'])['runs']
                                        if r['attempt']>=2 and r['status']=='running'),None),45)
        client.call('run_cancel',run_id=state['id'])
        wait_until(lambda: client.call('study_status',study_id=study['id'])['runs'][0]['status']=='cancelled',35)
        wait_until(lambda: entry('mcp') and not entry('mcp')['activity'],15)
        checks.append('Declined and confirmed Windows stop prompts, replay with attempt 2 and explicit run cancellation')
        kill_test_process(first_host,folder/'_internal/TwinPALS.Tray.exe')
        wait_until(lambda: host() and host()!=first_host,15)
        assert entry('desktop') and entry('mcp')
        checks.append('Tray host crash and automatic replacement with both services live')
        click('Stop desktop service…')
        assert process.wait(20)==0
        click('Open study observer')
        wait_until(lambda: receivers().count('/observe viewer')==2,10)
        # Rejoin while MCP is already running, then simulate an abruptly closed desktop.
        process=start_desktop()
        wait_until(lambda: entry('desktop'),40)
        process.kill(); process.wait(10)
        wait_until(lambda: not entry('desktop'),10)
        assert client.call('capabilities')
        click('Stop MCP service…')
        wait_until(lambda: not host_file.exists(),20)
        client.close()
        checks.append('MCP-only menu, reverse launch order, stale desktop removed and final host exit')
        process=start_desktop()
        client=connect()
        wait_until(lambda: entry('desktop') and entry('mcp') and host(),40)
        click('Stop MCP service…')
        click('Stop desktop service…')
        assert process.wait(20)==0
        wait_until(lambda: not host_file.exists(),20)
        checks.append('Concurrent startup, independent idle stop and empty notification area')
        report.write_text(json.dumps(dict(checks=checks,status='passed',
            desktop_sha256=hashlib.sha256(desktop.read_bytes()).hexdigest(),
            tray_sha256=hashlib.sha256((folder/'_internal/TwinPALS.Tray.exe').read_bytes()).hexdigest()),indent=2))
        print(report.read_text(),flush=True)
    finally:
        for client in clients:
            client.close()
        subprocess.run([*mcp_cmd,'--shutdown'],env=env,creationflags=flags,timeout=40,check=False)
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(10)


if __name__=='__main__':
    main()
