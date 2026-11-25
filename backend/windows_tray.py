# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Per-session Windows shell registrations. Only the owning server executes actions."""
import ctypes
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import threading
import time
import uuid


def directory():
    if os.name != 'nt' or os.environ.get('TWINPALS_NO_TRAY') == '1':
        return None
    session = ctypes.c_ulong()
    if not ctypes.windll.kernel32.ProcessIdToSessionId(os.getpid(), ctypes.byref(session)) or not session.value:
        return None
    return Path(os.environ['LOCALAPPDATA'])/'TwinPALS'/'Tray'/str(session.value)


def helper_path():
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent/'_internal/TwinPALS.Tray.exe'
    return Path(__file__).resolve().parents[1]/'release/_internal/TwinPALS.Tray.exe'


def mutex_exists(name):
    from ctypes import wintypes as w
    kernel = ctypes.windll.kernel32
    kernel.OpenMutexW.restype = w.HANDLE
    handle = kernel.OpenMutexW(0x100000, False, name)
    if handle:
        kernel.CloseHandle(w.HANDLE(handle))
    return bool(handle)


def uninstall_mutex():
    if os.name == 'nt' and getattr(sys, 'frozen', False):
        folder = str(Path(sys.executable).parent).upper().encode('utf-8')
        return 'Local\\TwinPALS.Uninstall.' + hashlib.sha256(folder).hexdigest()


def process_birth(pid):
    from ctypes import wintypes as w
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    kernel.OpenProcess.restype = w.HANDLE
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    times = [w.FILETIME() for _ in range(4)]
    try:
        if kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            return str(times[0].dwHighDateTime << 32 | times[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


def write_json(path, value):
    temporary = path.with_suffix('.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        for attempt in range(4):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 3:
                    raise
                time.sleep(.02)
    finally:
        temporary.unlink(missing_ok=True)


def reopen(data, port):
    """Only dispatch to a live desktop registered for this exact workspace and port."""
    base = directory()
    if not base or not base.exists():
        return False
    for path in base.glob('*.json'):
        try:
            entry = json.loads(path.read_bytes())
            if (entry['role'] == 'desktop' and entry['port'] == port and
                    Path(entry['data']) == data and entry['birth'] == process_birth(entry['pid']) and
                    entry['phase'] in ('Starting', 'Ready') and re.fullmatch('[0-9a-f]{32}', path.stem)):
                write_json(base/(path.stem + '.' + uuid.uuid4().hex + '.cmd'), {'action': 'open'})
                return True
        except (OSError, KeyError, ValueError):
            continue
    return False


def confirm_stop(role, activity):
    if not activity:
        return True
    explanation = ('Active desktop work will stop.' if role == 'desktop' else
                   'Unfinished study steps will resume from their saved inputs when the service starts again.')
    return ctypes.windll.user32.MessageBoxW(None, activity + '\n\n' + explanation,
        'TwinPALS 2.0 · Stop ' + ('desktop?' if role == 'desktop' else 'MCP service?'),
        0x04 | 0x30 | 0x100 | 0x10000) == 6


class TrayRegistration:
    def __init__(self, role, data, port=0):
        self.base = directory()
        self.helper = helper_path()
        self.key = uuid.uuid4().hex
        self.role = role
        self.data = Path(data).resolve()
        self.port = port
        self.stopped = threading.Event()
        self.ready = None
        self.thread = None
        self.phase = 'Starting'
        self.notice = None
        self.open_pending = False
        self.maintenance = uninstall_mutex()
        self.client = ''

    def __enter__(self):
        if self.base and self.helper.is_file():
            try:
                self.base.mkdir(parents=True, exist_ok=True)
                self.birth = process_birth(os.getpid())
                write_json(self.base/(self.key+'.json'), self._state(''))
            except OSError:
                self.base = None
                logging.exception('Windows notification area unavailable')
        else:
            self.base = None
        if self.base or self.maintenance:
            self.thread = threading.Thread(target=self._run, daemon=True, name='TwinPALS tray')
            self.thread.start()
        return self

    def attach(self, activity, open_ui, stop, is_ready):
        self.ready = activity, open_ui, stop, is_ready

    def notify(self, kind, study, title):
        self.notice = dict(id=uuid.uuid4().hex, kind=kind, study=study, title=title[:180])

    def _state(self, activity):
        return dict(role=self.role, pid=os.getpid(), birth=self.birth, data=str(self.data),
                    exe=sys.executable, port=self.port, phase=self.phase, activity=activity, notice=self.notice,
                    client=self.client)

    def __exit__(self, *_):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=2)
        if self.base:
            self._remove()

    def _remove(self):
        for path in [self.base/(self.key+'.json'), *self.base.glob(self.key+'.*.cmd')]:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass

    def _ensure_host(self):
        # Session-local kernel object. The helper also arbitrates simultaneous launches.
        namespace = hashlib.sha256(str(self.base).upper().encode()).hexdigest()[:16].upper()
        if mutex_exists('Local\\TwinPALS.Tray.' + self.base.name + '.' + namespace):
            return
        args = [str(self.helper)]
        opts = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    close_fds=True, cwd=str(self.helper.parent))
        try:
            subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW | 0x01000000, **opts)
        except PermissionError:
            subprocess.Popen(args, creationflags=subprocess.CREATE_NO_WINDOW, **opts)

    def _run(self):
        previous = None
        next_host = 0
        path = self.base/(self.key+'.json') if self.base else None
        while not self.stopped.is_set():
            try:
                ready = self.ready and self.ready[3]()
                if self.maintenance and mutex_exists(self.maintenance):
                    if ready and self.phase != 'Stopping':
                        self.phase = 'Stopping'
                        self.ready[2]()
                    if self.stopped.wait(.15):
                        break
                    continue
                if path is None:
                    self.stopped.wait(.55)
                    continue
                if ready and self.phase == 'Starting':
                    self.phase = 'Ready'
                activity = self.ready[0]() if ready else ''
                state = self._state(activity)
                if state != previous or not path.exists():
                    write_json(path, state)
                    previous = state
                if time.monotonic() >= next_host:
                    self._ensure_host()
                    next_host = time.monotonic()+3
                for cmd in self.base.glob(self.key+'.*.cmd'):
                    try:
                        action = json.loads(cmd.read_bytes())
                    finally:
                        cmd.unlink(missing_ok=True)
                    if action.get('action') == 'open':
                        if ready:
                            study = action.get('study', '')
                            self.ready[1](study if re.fullmatch('[a-f0-9]{32}',study) else '')
                        else:
                            self.open_pending = True
                    elif action.get('action') == 'stop' and ready and self.phase != 'Stopping':
                        if confirm_stop(self.role, self.ready[0]()):
                            self.phase = 'Stopping'
                            self.ready[2]()
                if ready and self.open_pending:
                    self.open_pending = False
                    self.ready[1]('')
            except Exception:
                logging.debug('Tray registration retry', exc_info=True)
            self.stopped.wait(.55)

