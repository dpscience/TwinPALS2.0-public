# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Operate the English Inno uninstall wizard on its own disposable Windows desktop."""
import ctypes as c
from ctypes import wintypes as w
import subprocess
import time
import uuid


class StartupInfo(c.Structure):
    _fields_ = [('size', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                ('layout', w.DWORD * 8), ('show', w.WORD), ('reserved_size', w.WORD),
                ('reserved_data', c.c_void_p), ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class ProcessInfo(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


def api(lib, name, result, *arguments):
    function = getattr(lib, name)
    function.restype, function.argtypes = result, arguments
    return function


def verify_dialog(program, work, cancel):
    program = program.resolve(strict=True)
    if program.parent != work.resolve(strict=True):
        raise ValueError('The wizard test requires a direct child of its test directory')
    kernel = c.WinDLL('kernel32', use_last_error=True)
    user = c.WinDLL('user32', use_last_error=True)
    register = api(user, 'CreateDesktopW', w.HANDLE, w.LPCWSTR, c.c_void_p, c.c_void_p, w.DWORD, w.DWORD, c.c_void_p)
    callback = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
    windows = api(user, 'EnumDesktopWindows', w.BOOL, w.HANDLE, callback, w.LPARAM)
    children = api(user, 'EnumChildWindows', w.BOOL, w.HWND, callback, w.LPARAM)
    visible = api(user, 'IsWindowVisible', w.BOOL, w.HWND)
    enabled = api(user, 'IsWindowEnabled', w.BOOL, w.HWND)
    caption = api(user, 'GetWindowTextW', c.c_int, w.HWND, w.LPWSTR, c.c_int)
    class_name = api(user, 'GetClassNameW', c.c_int, w.HWND, w.LPWSTR, c.c_int)
    post = api(user, 'PostMessageW', w.BOOL, w.HWND, w.UINT, w.WPARAM, w.LPARAM)
    spawn = api(kernel, 'CreateProcessW', w.BOOL, w.LPCWSTR, w.LPWSTR, c.c_void_p, c.c_void_p,
                w.BOOL, w.DWORD, c.c_void_p, w.LPCWSTR, c.POINTER(StartupInfo), c.POINTER(ProcessInfo))
    close = api(kernel, 'CloseHandle', w.BOOL, w.HANDLE)
    wait = api(kernel, 'WaitForSingleObject', w.DWORD, w.HANDLE, w.DWORD)
    name = 'TwinPALS-Uninstall-Test-' + uuid.uuid4().hex
    desktop = register(name, None, None, 0, 0x1ff, None)
    if not desktop:
        raise c.WinError(c.get_last_error())
    process = ProcessInfo()
    order = ['Cancel'] if cancel else ['Close processes and continue', 'Keep my data', 'Yes', 'OK']
    stage = 0

    def enumerate_handles(fn, root):
        handles = []
        @callback
        def visit(hwnd, _):
            if visible(hwnd) and enabled(hwnd):
                handles.append(hwnd)
            return True
        fn(root, visit, 0)
        return handles

    try:
        startup = StartupInfo(size=c.sizeof(StartupInfo), desktop=name)
        exe = program / 'unins000.exe'
        command = subprocess.list2cmdline([str(exe), '/NORESTART', '/LANG=english', '/LOG=' +
                                           str(work / ('cancel-uninstall.log' if cancel else 'confirmed-uninstall.log'))])
        if not spawn(str(exe), c.create_unicode_buffer(command), None, None, False, 0, None,
                     str(work), c.byref(startup), c.byref(process)):
            raise c.WinError(c.get_last_error())
        close(process.thread)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            for window in enumerate_handles(windows, desktop):
                buttons = {}
                for child in enumerate_handles(children, window):
                    kind, label = c.create_unicode_buffer(64), c.create_unicode_buffer(160)
                    class_name(child, kind, len(kind))
                    if 'button' in kind.value.lower():
                        caption(child, label, len(label))
                        buttons[label.value.replace('&', '').strip()] = child
                if stage == 0 and 'Close processes and continue' not in buttons:
                    continue
                if stage < len(order) and order[stage] in buttons:
                    if not post(buttons[order[stage]], 0x00F5, 0, 0):  # BM_CLICK
                        raise c.WinError(c.get_last_error())
                    stage += 1
            if wait(process.process, 0) == 0 and stage == len(order):
                return
            time.sleep(.1)
        raise RuntimeError(f'Uninstall wizard timed out after {order[:stage]}')
    finally:
        if process.process:
            close(process.process)
        api(user, 'CloseDesktop', w.BOOL, w.HANDLE)(desktop)
