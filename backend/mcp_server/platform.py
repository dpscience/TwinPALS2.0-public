# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Keep local studies independent of a desktop client and restore them at sign-in."""
import ctypes
import hashlib
import os
import subprocess
import sys
from pathlib import Path

from backend.app import application_root


def command():
    if getattr(sys,'frozen',False):
        return [str(Path(sys.executable).with_name('TwinPALS-MCP.exe'))]
    return [sys.executable,str(application_root()/'scripts/start_mcp.py')]


def launch_service(data,no_logon):
    directory=data/'studies'
    directory.mkdir(parents=True,exist_ok=True)
    args=[*command(),'--serve','--data-dir',str(data)]
    if no_logon:
        args.append('--no-logon-resume')
    kwargs={'cwd':str(application_root()),'stdin':subprocess.DEVNULL,'close_fds':True}
    if getattr(sys,'frozen',False):
        kwargs['env']={**os.environ,'PYINSTALLER_RESET_ENVIRONMENT':'1'}
    with (directory/'service.log').open('ab') as log:
        kwargs.update(stdout=log,stderr=log)
        if os.name=='nt':
            flags=subprocess.CREATE_NEW_PROCESS_GROUP|subprocess.CREATE_NO_WINDOW
            try:
                return subprocess.Popen(args,creationflags=flags|0x01000000,**kwargs)
            except PermissionError:
                return subprocess.Popen(args,creationflags=flags,**kwargs)
        return subprocess.Popen(args,start_new_session=True,**kwargs)


def child_job():
    """Close the service's native children even on a forced process termination."""
    if os.name!='nt':
        return
    from ctypes import wintypes as w
    class Basic(ctypes.Structure):
        _fields_=[('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',w.DWORD),
                  ('working_min',ctypes.c_size_t),('working_max',ctypes.c_size_t),('active',w.DWORD),
                  ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',ctypes.c_uint64*6),('memory',ctypes.c_size_t*4)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateJobObjectW.argtypes=[w.LPVOID,w.LPCWSTR]
    kernel.CreateJobObjectW.restype=w.HANDLE
    kernel.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,w.LPVOID,w.DWORD]
    kernel.GetCurrentProcess.restype=w.HANDLE
    kernel.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.CreateJobObjectW(None,None)
    info=Extended()
    # Native workers inherit the kill-on-close job. Only the shared tray host
    # explicitly requests CREATE_BREAKAWAY_FROM_JOB so it can outlive this service.
    info.basic.flags=0x2000 | 0x0800
    if not handle or not kernel.SetInformationJobObject(handle,9,ctypes.byref(info),ctypes.sizeof(info)) or not kernel.AssignProcessToJobObject(handle,kernel.GetCurrentProcess()):
        err=ctypes.get_last_error()
        if handle:
            kernel.CloseHandle(handle)
        raise ctypes.WinError(err)
    # Deliberately keep the non-inheritable handle until process termination.
    return handle


def logon(data,enabled):
    if os.name!='nt':
        return
    import winreg
    label='TwinPALS study '+hashlib.sha256(os.path.normcase(str(data)).encode()).hexdigest()[:16]
    args=subprocess.list2cmdline([*command(),'--resume','--data-dir',str(data)])
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run',0,winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key,label,0,winreg.REG_SZ,args)
        else:
            try:
                winreg.DeleteValue(key,label)
            except FileNotFoundError:
                pass

