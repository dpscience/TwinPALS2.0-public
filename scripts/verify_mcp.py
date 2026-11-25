# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Exercise the real stdio and recovery paths in an isolated, disposable data folder."""
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import time
import uuid
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import __version__
HTTP=build_opener(ProxyHandler({}))


class Client:
    def __init__(self,command,env,client_name='TwinPALS smoke'):
        self.proc=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   cwd=ROOT,env=env,text=True,encoding='utf-8',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.seq=0
        self.called=set()
        self.response_ref=None
        init=self.request('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':client_name,'version':'1'}})
        assert init['protocolVersion']=='2025-11-25'
        self.write({'jsonrpc':'2.0','method':'notifications/initialized'})

    def write(self,message):
        self.proc.stdin.write(json.dumps(message)+'\n')
        self.proc.stdin.flush()

    def request(self,method,params):
        self.seq+=1
        self.write({'jsonrpc':'2.0','id':self.seq,'method':method,'params':params})
        line=self.proc.stdout.readline()
        if not line:
            raise RuntimeError(self.proc.stderr.read())
        res=json.loads(line)
        assert res['id']==self.seq,res
        return res['result']

    def call(self,tool_name,**args):
        response=self.request('tools/call',dict(name=tool_name,arguments=args))
        if response.get('isError'):
            raise ValueError(response['content'][0]['text'])
        self.called.add(tool_name)
        result=json.loads(response['content'][0]['text'])
        self.response_ref=None
        if isinstance(result,dict) and 'response_id' in result:
            self.response_ref=result['response_id']
            result=json.loads(Path(result['path']).read_bytes())
        return result

    def close(self):
        if self.proc.poll() is None:
            self.proc.stdin.close()
            assert self.proc.wait(timeout=15)==0
        self.proc.stdout.close()
        self.proc.stderr.close()


def http(url,token=None,method='GET',body=None):
    req=Request(url,method=method,headers={'Authorization':'Bearer '+(token or ''),'Content-Type':'application/json'},
                data=json.dumps(body).encode() if body is not None else None)
    with HTTP.open(req,timeout=15) as response:
        return response.read()


def wait_until(fn,seconds):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        value=fn()
        if value:
            return value
        time.sleep(.15)
    raise RuntimeError('Timed out waiting for '+fn.__name__)


def physical_prefix(path):
    from backend.streams import FRAME
    result=[]
    with path.open('rb') as stream:
        stream.seek(8)
        size=struct.unpack('<I',stream.read(4))[0]
        stream.seek(size,1)
        while len(result)<32:
            head=stream.read(FRAME.size)
            if len(head)!=FRAME.size:break
            tag,n,crc=FRAME.unpack(head)
            payload=stream.read(n)
            if len(payload)!=n:break
            if tag in (b'EVNT',b'APLS'):
                result.append((tag,crc,hashlib.sha256(payload).digest()))
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exe',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--test-logon',action='store_true',help='Exercise the actual transient per-user Windows startup entry.')
    parser.add_argument('--browser',action='store_true')
    args=parser.parse_args()
    data=ROOT/'tmp'/('mcp qa '+uuid.uuid4().hex[:9])
    data.mkdir()
    print('Isolated workspace:',data,flush=True)
    executable=args.exe.resolve() if args.exe else None
    base=[str(executable)] if executable else [sys.executable,'-m','backend.mcp_server.cli']
    command=[*base,'--data-dir',str(data)]
    if not args.test_logon:
        command+=['--no-logon-resume']
    env=dict(os.environ,HTTP_PROXY='http://127.0.0.1:1',HTTPS_PROXY='http://127.0.0.1:1',NO_PROXY='',PYTHONIOENCODING='utf-8')
    if executable:
        system=os.environ['SystemRoot']
        env['PATH']=system+'\\System32;'+system
        for key in list(env):
            if key in ('PYTHONPATH','PYTHONHOME','VIRTUAL_ENV') or key.startswith('G4') or key=='GEANT4_DATA_DIR':
                env.pop(key)
    clients=[]
    def client():
        c=Client(command,env)
        clients.append(c)
        return c

    def run_rows():
        with contextlib.closing(sqlite3.connect(data/'studies/queue.sqlite')) as db:
            return list(db.execute('select name,status,attempt from runs order by rowid'))

    def endpoint():
        return json.loads((data/'studies/endpoint.json').read_bytes())

    def registered():
        import winreg
        key='TwinPALS study '+hashlib.sha256(os.path.normcase(str(data)).encode()).hexdigest()[:16]
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as k:
            try:return winreg.QueryValueEx(k,key)[0]
            except FileNotFoundError:return None

    checks={}
    ports=[]
    report={'version':__version__,'workspace':str(data),'executable':str(executable or sys.executable),'checks':checks}
    if executable:
        report['mcp_exe_sha256']=hashlib.sha256(executable.read_bytes()).hexdigest()
    try:
        cli=client()
        names={t['name'] for t in cli.request('tools/list',{})['tools']}
        chapters=cli.call('knowledge_search',query='',limit=20)['topics']
        resources=cli.request('resources/list',{})['resources']
        assert {r['uri'] for r in resources}=={c['uri'] for c in chapters}
        for chapter in chapters:
            method=cli.call('knowledge_read',topic=chapter['topic'])
            contents=cli.request('resources/read',{'uri':chapter['uri']})['contents']
            assert method['text'] in contents[0]['text'] and method['references'] and method['version']==__version__
        assert not (data/'studies/endpoint.json').exists()
        checks['offline_method_topics']=len(chapters)
        assert {'catalogue_save','study_submit','study_compare','spectrum_query','observer_open'}<=names
        caps=cli.call('capabilities')
        assert Path(caps['data_directory'])==data
        checks['stdio_tools']=len(names)
        print('Connected via MCP stdio.',flush=True)
        assert cli.call('profile_get',module=1,pointer='/source')=='na22'
        assert cli.call('profile_get',module=3,schema_only=True,pointer='/properties')
        operations=cli.call('workbench_routes',search='/api/m1/state')
        assert any(operation['path']=='/api/m1/state' for operation in operations)
        desktop=cli.call('workbench_call',method='GET',path='/api/m1/state')
        assert desktop['profile']['source']=='na22' and cli.response_ref
        page=cli.call('result_read',response_id=cli.response_ref,pointer='/entries',offset=1,limit=2)
        assert page['items']==desktop['entries'][1:3] and page['total']==len(desktop['entries'])
        viewer=cli.call('observer_open')['url']
        url,token=viewer.split('#')
        service=endpoint()
        ports.append(urlsplit(url).port)
        assert b'<html' in http(url).lower()
        assert json.loads(http(url+'/api/status',token))['runs']==[]
        for target,method,credential in ((url+'/api/status','POST',token),(url+'/api/status','GET',None),(service['url']+'/control/tool','POST',token)):
            try:http(target,credential,method,{} if method=='POST' else None)
            except HTTPError as exc:assert exc.code==403
            else:raise AssertionError('Observer could write or read unauthenticated')
        checks['observer_access']='GET-only, writer credential independent'

        tube_ref=cli.call('catalogue_list',category='pmt')[0]
        tube=cli.call('catalogue_get',id=tube_ref['id'])
        tube.update(id='mcp-qa-photomultiplier',name='MCP verification tube')
        created=cli.call('catalogue_save',entry=tube)
        assert created['revision']==1
        created['description']='Revision check'
        assert cli.call('catalogue_save',entry=created,expected_revision=1)['revision']==2
        try:cli.call('catalogue_save',entry=created,expected_revision=1)
        except ValueError:pass
        else:raise AssertionError('Stale catalogue revision accepted')
        checks['pmt']='Created, updated, stale write rejected'

        c1={'/run/events':650,'/run/secondary_events':650,'/run/auto_seed':False,'/run/seed':52231}
        spec=dict(request_id='portable-physics',name='Portable physics study',objective='Check provenance and acquisition',max_parallel=2,cpu_budget=2,steps=[
            dict(key='reference',module=1,changes=c1),dict(key='cascade',module=1,changes={'/source':'co60','/run/events':18000}),
            dict(key='acquire',module=2,input_from='reference',changes={'/waveform_pairs':8,'/activity_Bq':10000,'/acquisition/trigger':'either','/channels/0/threshold_mV':1,'/channels/1/threshold_mV':1},queries=[dict(name='features',path='/api/m2/analysis',body={'bins':40})]),
            dict(key='lifetime',module=3,input_from='acquire')])
        study=cli.call('study_submit',**spec)
        study_id=study['id']
        interrupted_file=data/'studies'/study_id/study['runs'][1]['id']/'attempt-001/primary-1.tpstream.part'
        assert cli.call('study_submit',**spec)['id']==study_id
        try:cli.call('study_submit',**{**spec,'name':'conflict'})
        except ValueError:pass
        else:raise AssertionError('Conflicting idempotency key accepted')
        before=cli.call('study_status',study_id=study_id,manifest=True)
        if args.test_logon:
            assert str(data) in registered()
        cli.close()
        cli=client()
        assert cli.call('study_submit',**spec)['id']==study_id
        assert endpoint()['pid']==service['pid']
        cli.close()
        def detached_completion():
            rows=run_rows()
            return rows if rows[0][1]=='completed' and rows[1][1]=='running' and interrupted_file.is_file() and interrupted_file.stat().st_size>65000 else None
        observed=wait_until(detached_completion,100)
        checks['disconnected_progress']=observed
        print('First M1 completed with client disconnected; second M1 still running.',flush=True)
        # This PID came from our own authenticated, isolated workspace.
        assert json.loads(http(service['url']+'/control/ping',service['token']))['pid']==service['pid']
        os.kill(service['pid'],signal.SIGTERM)
        def original_closed():
            with socket.socket() as sock:
                sock.settimeout(.1)
                return sock.connect_ex(('127.0.0.1',ports[0]))!=0
        wait_until(original_closed,15)
        # Use the same executable mode as Windows sign-in, without any MCP client.
        subprocess.run([*command,'--resume'],check=True,timeout=50,cwd=ROOT,env=env)
        recovered=endpoint()
        ports.append(urlsplit(recovered['url']).port)
        assert recovered['pid']!=service['pid']
        def finished():
            rows=run_rows()
            if any(r[1] in ('failed','blocked','cancelled') for r in rows):
                raise RuntimeError(str(rows))
            return rows if all(r[1]=='completed' for r in rows) else None
        rows=wait_until(finished,220)
        assert rows[0][2]==1 and rows[1][2]==2,rows
        cli=client()
        assert cli.call('study_status',study_id=study_id,manifest=True)==before
        jobs=cli.call('study_status',study_id=study_id)['runs']
        receipts=[cli.call('run_result',run_id=j['id']) for j in jobs]
        a,b,pulse,life=receipts
        for output in (a['outputs'][0],pulse['outputs'][0]):
            location=Path(output['path'])
            inventory=cli.call('stream_list',directory=str(location.parent))
            assert any(row['path']==str(location) and row['bytes']==location.stat().st_size for row in inventory['streams'])
            info=cli.call('stream_inspect',path=str(location))
            assert info['completion']['status']=='completed' and info['header']
        assert a['metrics']['completed']==1300 and b['metrics']['completed']==36000
        assert b['profile']['run']['seed']==before['steps'][1]['profile']['run']['seed']
        prefix=physical_prefix(interrupted_file)
        assert len(prefix)>=8 and prefix==physical_prefix(Path(b['outputs'][0]['path']))[:len(prefix)]
        checks['replay_physical_frames']=len(prefix)
        assert pulse['inputs']==a['outputs'] and life['inputs']==pulse['outputs']
        assert pulse['metrics']['waveforms']==life['metrics']['total_processed']==8
        m2_wave=cli.call('waveform_read',run_id=jobs[2]['id'],index=3,pointer='/waveform')
        m3_wave=cli.call('waveform_read',run_id=jobs[3]['id'],index=3,pointer='/waveform')
        assert m2_wave==m3_wave and len(m2_wave)==4
        assert cli.call('run_result',run_id=jobs[2]['id'],artifact='features',pointer='/total')==8
        layers=cli.call('spectrum_query',run_id=jobs[3]['id'],direction='merged',display={'individual':True})
        saved=cli.call('run_result',run_id=jobs[3]['id'],artifact='analysis',pointer='/comparisons/merged/stages')
        assert layers['stages']==saved
        ranking=cli.call('study_compare',study_id=study_id,metric='/completed')
        assert [r['value'] for r in ranking]==[36000,1300]
        assert Path(cli.call('study_report',study_id=study_id)['path']).is_file()
        draft=cli.call('study_document',study_id=study_id,filename='methods.md',run_ids=[jobs[3]['id']],content='Eight simulated waveform pairs were analyzed.\n')
        assert Path(draft['path']).read_text().startswith('Eight')
        checks['recovered_attempts']=rows
        checks['source_counts']=[1300,36000]
        checks['waveform_pairs']=8
        checks['random_access_waveform']='All A/B samples identical on M2 and M3 seek'
        checks['query_rebin_report_document']='passed'
        checks['frozen_seed_on_retry']=b['profile']['run']['seed']
        if args.test_logon:
            wait_until(lambda:registered() is None,8)
            checks['windows_sign_in']='Registry command created, --resume executed independently, entry removed'
        if args.browser:
            viewer=cli.call('observer_open')['url']
            bfile=data/'browser.json'
            subprocess.run(['node',str(ROOT/'scripts/verify_mcp_ui.cjs'),str(bfile)],input=viewer,text=True,check=True,timeout=80,cwd=ROOT)
            report['browser']=json.loads(bfile.read_bytes())
            ui_root=(executable.parent if executable else ROOT)/'frontend/dist'
            report['browser']['frontend_files']={p.relative_to(ui_root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                                                 for p in ui_root.rglob('*') if p.is_file()}
        checks['proxy']='External HTTP(S) proxy pointed to an unreachable local address'
        study_ids={item['id'] for item in cli.call('study_list')}
        assert study_id in study_ids
        control=cli.call('study_submit',request_id='test-cancel-retry',name='Run controls',
                         max_parallel=1,cpu_budget=1,steps=[
                             dict(key='first',module=1,changes={'/run/events':250,'/run/secondary_events':250}),
                             dict(key='second',module=1,changes={'/run/events':40,'/run/secondary_events':40})])
        run_id=control['runs'][1]['id']
        cli.call('run_cancel',run_id=run_id)
        def control_state():
            return cli.call('study_status',study_id=control['id'])['runs'][1]['status']
        wait_until(lambda:control_state()=='cancelled',15)
        assert cli.call('run_retry',run_id=run_id)['id']==run_id
        wait_until(lambda:control_state()=='completed',75)
        assert cli.call('run_result',run_id=run_id,pointer='/metrics/completed')==80
        if caps['cpu_budget']>=3:
            parallel=cli.call('study_submit',request_id='three-detector-runs',name='Three detector runs',
                              max_parallel=3,cpu_budget=3,steps=[
                                  dict(key=key,module=1,workers=1,changes={
                                      '/run/events':600,'/run/secondary_events':600})
                                  for key in ('first','second','third')])
            def all_three_done():
                jobs=cli.call('study_status',study_id=parallel['id'])['runs']
                assert all(job['status'] not in ('failed','cancelled','blocked') for job in jobs),jobs
                return all(job['status']=='completed' for job in jobs)
            wait_until(all_three_done,90)
            receipts=[cli.call('run_result',run_id=job['id']) for job in parallel['runs']]
            assert max(r['started'] for r in receipts)<min(r['finished'] for r in receipts)
            assert all(r['workers']==1 and r['metrics']['completed']==1200 for r in receipts)
            checks['simultaneous_module1_runs']=len(receipts)
        if args.test_logon:
            wait_until(lambda:registered() is None,8)
        used=set().union(*(c.called for c in clients))
        assert used==names,sorted(names-used)
        checks['tools_exercised']=sorted(used)
    finally:
        for c in clients:
            c.close()
        subprocess.run([*command,'--shutdown'],timeout=40,cwd=ROOT,env=env)
        wait_until(lambda:not (data/'studies/endpoint.json').exists(),30)
    report.update(status='passed',server_stopped=True,ports=ports)
    if 'browser' in report:
        report['browser']['server_stopped']=True
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Passed:',args.report,flush=True)

if __name__=='__main__':
    main()

