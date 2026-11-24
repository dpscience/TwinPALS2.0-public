# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import multiprocessing

# Frozen process-pool workers re-enter this executable with private arguments.
# Dispatch them before importing the server or parsing application arguments.
if __name__ == "__main__":
    multiprocessing.freeze_support()

import argparse
import socket
import threading
import webbrowser

from backend import __version__
from backend.windows_tray import TrayRegistration, reopen


def open_when_ready(server,url,stopped):
    # An occupied port or failed startup must never open a different/old UI.
    while not stopped.wait(.05):
        if server.started:
            webbrowser.open(url)
            return


def main():
    import sys
    from pathlib import Path
    if Path(sys.executable).stem.casefold() == "twinpals-mcp":
        from backend.mcp_server.cli import main as mcp_main
        return mcp_main()
    parser=argparse.ArgumentParser(description="TwinPALS local workbench")
    parser.add_argument("--version", action="version", version=f"TwinPALS {__version__}")
    parser.add_argument("--port",type=int,default=18622)
    parser.add_argument("--no-browser",action="store_true")
    parser.add_argument("--data-dir")
    parser.add_argument("--verify-tls", action="store_true", help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.verify_tls:
        import ssl
        ssl.create_default_context()
        return 0
    from backend.app import application_root, default_data_directory
    data=Path(args.data_dir or default_data_directory(application_root())).resolve()
    args.data_dir=data
    if not 1024<=args.port<=65535:
        parser.error("Port must be in 1024..65535")
    stopped=threading.Event()
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as listener:
        if hasattr(socket,'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        try:listener.bind(('127.0.0.1',args.port))
        except OSError as exc:
            if not args.no_browser and reopen(data,args.port):
                return 0
            startup_error(args,parser,f'TwinPALS {__version__} cannot start on port {args.port}: {exc}.\nChoose another --port or stop the existing server. No browser was opened.')
        with TrayRegistration('desktop',data,args.port) as tray:
            return run_desktop(args,listener,stopped,tray,parser)


def run_desktop(args,listener,stopped,tray,parser):
    import uvicorn
    from backend.app import create_app
    from backend.material_database import InvalidCatalogue
    try:
        app=create_app(data_dir=args.data_dir)
    except (InvalidCatalogue,RuntimeError,OSError) as exc:
        startup_error(args,parser,f'TwinPALS {__version__} could not start.\n{exc}\nNo browser was opened.')
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,log_level='info',timeout_graceful_shutdown=3))
    url=f'http://127.0.0.1:{args.port}'
    tray.attach(app.state.tray_activity,lambda _: webbrowser.open(url),lambda: setattr(server,'should_exit',True),lambda: server.started)
    print(f"\nTwinPALS {__version__} | Module 1\nOpen {url}\nUse the TwinPALS tray menu or press Ctrl+C to stop.\n",flush=True)
    if not args.no_browser:
        threading.Thread(target=open_when_ready,args=(server,url,stopped),daemon=True,name='TwinPALS-browser').start()
    try:server.run(sockets=[listener])
    finally:stopped.set()


def startup_error(args,parser,message):
    import ctypes
    import sys
    if getattr(sys,'frozen',False) and not args.no_browser and sys.stderr.isatty():
        window=ctypes.windll.kernel32.GetConsoleWindow()
        if window and not ctypes.windll.user32.IsWindowVisible(window):
            ctypes.windll.user32.MessageBoxW(None,message,'TwinPALS 2.0',0x10)
    parser.exit(1,message+'\n')


if __name__=="__main__":
    raise SystemExit(main())
