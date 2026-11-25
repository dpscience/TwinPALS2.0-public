# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""MCP stdio transport. Stdout contains exclusively newline-framed JSON-RPC."""
import argparse
from http.client import HTTPConnection
import json
import multiprocessing
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from backend.app import application_root, default_data_directory
from backend.windows_tray import TrayRegistration
from . import VERSION
from . import platform
from . import knowledge
from .engine import read
from .studies import Queue
from .tools import invoke, listing

VERSIONS=('2025-11-25','2025-06-18','2025-03-26','2024-11-05')


class Connection:
    def __init__(self,data,no_logon=False):
        self.data=data
        self.no_logon=no_logon

    def send(self,endpoint,path,body=None,timeout=1200):
        address=urlsplit(endpoint['url'])
        if address.scheme!='http' or address.hostname!='127.0.0.1' or not address.port:
            raise ValueError('Invalid local coordinator address.')
        channel=HTTPConnection('127.0.0.1',address.port,timeout=timeout)
        try:
            channel.request('GET' if body is None else 'POST',path,
                            body=None if body is None else json.dumps(body).encode(),
                            headers={'Authorization':'Bearer '+endpoint['token'],'Content-Type':'application/json'})
            response=channel.getresponse()
            if response.status!=200:
                raise OSError(f'Local study service returned HTTP {response.status}.')
            return json.load(response)
        finally:
            channel.close()

    def existing(self):
        endpoint=read(self.data/'studies/endpoint.json')
        if endpoint:
            try:
                ping=self.send(endpoint,'/control/ping',timeout=1)
                if ping.get('service')=='TwinPALS' and ping.get('pid')==endpoint['pid']:
                    return endpoint
            except (OSError,ValueError):
                pass
        return None

    def connect(self):
        endpoint=self.existing()
        if endpoint:
            return endpoint
        process=platform.launch_service(self.data,self.no_logon)
        deadline=time.monotonic()+35
        while time.monotonic()<deadline:
            endpoint=self.existing()
            if endpoint:
                return endpoint
            if process.poll() not in (None,0):
                break
            time.sleep(.12)
        raise RuntimeError('The local study service did not start. See '+str(self.data/'studies/service.log'))

    def call(self,name,arguments):
        result=self.send(self.connect(),'/control/tool',{'name':name,'arguments':arguments})
        if 'error' in result:
            raise ValueError(result['error'])
        return result['value']


def rpc(message,connection):
    if not isinstance(message,dict) or message.get('jsonrpc')!='2.0' or not isinstance(message.get('method'),str):
        return {'jsonrpc':'2.0','id':message.get('id') if isinstance(message,dict) else None,'error':{'code':-32600,'message':'Invalid JSON-RPC request'}}
    if 'id' not in message:
        return None
    reply={'jsonrpc':'2.0','id':message['id']}
    method=message['method']
    params=message.get('params',{})
    if not isinstance(params,dict):
        return {**reply,'error':{'code':-32602,'message':'params must be an object'}}
    if method=='initialize':
        version=params.get('protocolVersion')
        result={'protocolVersion':version if version in VERSIONS else VERSIONS[0],
                'capabilities':{'tools':{},'resources':{}},'serverInfo':{'name':'TwinPALS','title':'TwinPALS 2.0','version':VERSION},
                'instructions':'M1 simulates detector response, M2 digitizes coincidences, and M3 measures the recorded pulses and lifetime spectra. Start with knowledge_read(topic="overview"), then use knowledge_search for the relevant method, assumptions and units. Read the current profile and catalogue before study_submit. Cite run receipts for results, the official version link when available, and the scientific basis, Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663.'}
    elif method=='ping':
        result={}
    elif method=='tools/list':
        result={'tools':listing()}
    elif method=='resources/list':
        result={'resources':knowledge.resources()}
    elif method=='resources/templates/list':
        result={'resourceTemplates':[]}
    elif method=='resources/read':
        try:
            uri=params.get('uri')
            result={'contents':[{'uri':uri,'mimeType':'text/markdown','text':knowledge.resource_text(uri)}]}
        except ValueError as exc:
            return {**reply,'error':{'code':-32002,'message':str(exc)}}
    elif method=='tools/call':
        if not isinstance(params.get('name'),str) or not isinstance(params.get('arguments',{}),dict):
            return {**reply,'error':{'code':-32602,'message':'Supply name and object arguments'}}
        try:
            name=params['name']
            arguments=params.get('arguments',{})
            value=invoke(None,name,arguments) if name in ('knowledge_read','knowledge_search') else connection.call(name,arguments)
            result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False,allow_nan=False)}]}
        except (ValueError,OSError,RuntimeError) as exc:
            result={'content':[{'type':'text','text':str(exc)}],'isError':True}
    else:
        return {**reply,'error':{'code':-32601,'message':'Method not found'}}
    return {**reply,'result':result}


def stdio(connection, source, sink, tray):
    for line in source:
        try:
            req=json.loads(line)
        except (ValueError,UnicodeDecodeError):
            response={'jsonrpc':'2.0','id':None,'error':{'code':-32700,'message':'Parse error'}}
        else:
            response=rpc(req,connection)
            if isinstance(req, dict) and req.get('method') == 'initialize' and 'result' in (response or {}):
                client = req['params'].get('clientInfo', {}) if 'params' in req else {}
                name = client.get('name') if isinstance(client, dict) else None
                if isinstance(name, str):
                    tray.client = ''.join(ch for ch in name if ch.isprintable()).strip()[:48]
        if response is not None:
            sink.write(json.dumps(response,ensure_ascii=False,allow_nan=False).encode()+b'\n')
            sink.flush()


def client_session(connection):
    with TrayRegistration('client', connection.data) as tray:
        if tray.thread is None:
            stdio(connection, sys.stdin.buffer, sys.stdout.buffer, tray)
            return
        finished = threading.Event()
        errors = []

        def exchange():
            # A host can keep either pipe open indefinitely. Private streams let
            # the bridge exit without waiting for a blocked read/write at shutdown.
            try:
                with open(sys.stdin.fileno(), 'rb', closefd=False) as source, \
                        open(sys.stdout.fileno(), 'wb', closefd=False) as sink:
                    stdio(connection, source, sink, tray)
            except BrokenPipeError:
                pass
            except Exception as exc:
                errors.append(exc)
            finally:
                finished.set()

        tray.attach(lambda: '', lambda _: None, finished.set, lambda: True)
        threading.Thread(target=exchange, daemon=True, name='MCP stdio').start()
        finished.wait()
        if errors:
            raise errors[0]


def main():
    multiprocessing.freeze_support()
    parser=argparse.ArgumentParser(description='TwinPALS local study server for MCP clients')
    parser.add_argument('--data-dir',type=Path,default=default_data_directory(application_root()))
    parser.add_argument('--no-logon-resume',action='store_true',help='Skip Windows sign-in registration for an isolated or temporary workspace.')
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--serve',action='store_true',help=argparse.SUPPRESS)
    modes.add_argument('--resume',action='store_true',help='Resume pending local studies, then exit the launcher.')
    modes.add_argument('--observer',action='store_true',help='Open the read-only live observer.')
    modes.add_argument('--shutdown',action='store_true',help='Stop this workspace coordinator, preserving unfinished work.')
    modes.add_argument('--print-config',choices=('codex','claude-desktop','claude-code','copilot-cli','vscode'))
    modes.add_argument('--version',action='version',version='TwinPALS MCP '+VERSION)
    args=parser.parse_args()
    data=args.data_dir.resolve()
    connection=Connection(data,args.no_logon_resume)
    if args.print_config:
        if not sys.stdout.isatty():
            sys.stdout.reconfigure(encoding='utf-8')
        cmd=[*platform.command(),'--data-dir',str(data)]
        if args.no_logon_resume:
            cmd.append('--no-logon-resume')
        config={'command':cmd[0],'args':cmd[1:]}
        if args.print_config=='codex':
            print('[mcp_servers.twinpals]\ncommand = '+json.dumps(cmd[0],ensure_ascii=False)+'\nargs = '+json.dumps(cmd[1:],ensure_ascii=False))
        elif args.print_config=='vscode':
            print(json.dumps({'servers':{'twinpals':{'type':'stdio',**config}}},indent=2,ensure_ascii=False))
        elif args.print_config=='copilot-cli':
            print(json.dumps({'mcpServers':{'twinpals':{'type':'stdio',**config,'tools':['*']}}},indent=2,ensure_ascii=False))
        else:
            print(json.dumps({'mcpServers':{'twinpals':config}},indent=2,ensure_ascii=False))
    elif args.serve:
        from .service import serve
        return serve(data,args.no_logon_resume)
    elif args.resume:
        if (data/'studies/queue.sqlite').is_file() and Queue(data).rows("SELECT id FROM runs WHERE status IN ('queued','running','cancelling') LIMIT 1"):
            connection.connect()
    elif args.shutdown:
        endpoint=connection.existing()
        if endpoint:
            connection.send(endpoint,'/control/shutdown',{})
    elif args.observer:
        print(connection.call('observer_open',{'open_browser':True})['url'])
    else:
        client_session(connection)
    return 0

if __name__=='__main__':
    raise SystemExit(main())

