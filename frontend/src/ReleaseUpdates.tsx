// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useCallback, useEffect, useId, useRef, useState} from 'react';
import {ArrowDownToLine, ArrowUpRight, ChevronUp, RefreshCw, X} from 'lucide-react';
import {api} from './api';
import './release-updates.css';

type Status = {installed:string; latest:string|null; available:boolean; state:string; url:string|null};
function stored(key:string) {
  try {return localStorage.getItem('twinpals.updates.'+key);} catch {return null;}
}
function remember(key:string,value:string) {
  try {localStorage.setItem('twinpals.updates.'+key,value);} catch { /* storage is optional */ }
}

export default function ReleaseUpdates({version, observerToken}:{version?:string; observerToken?:string}) {
  const [status,setStatus]=useState<Status|null>(null);
  const [auto,setAuto]=useState(()=>stored('automatic')!=='off');
  const [panel,show]=useState<'notice'|'settings'|null>(null);
  const [busy,setBusy]=useState(false);
  const [failed,setFailed]=useState(false);
  const id=useId(), box=useRef<HTMLDivElement>(null), trigger=useRef<HTMLButtonElement>(null);
  const active=useRef<AbortController|null>(null);
  const check=useCallback(async (refresh:boolean,manual:boolean)=>{
    active.current?.abort();
    const abort=new AbortController(); active.current=abort;
    setBusy(true); setFailed(false);
    const path='/releases/latest?refresh='+refresh+'&manual='+manual;
    try {
      let result:Status;
      if(observerToken===undefined) result=await api<Status>(path,{signal:abort.signal});
      else {
        const response=await fetch('/observe/api'+path,{signal:abort.signal,headers:{Authorization:'Bearer '+observerToken}});
        if(!response.ok)throw Error();
        result=await response.json();
      }
      if(abort.signal.aborted)return;
      setStatus(result);
      if(refresh&&!manual&&result.available&&result.latest&&stored('shown')!==result.latest){
        remember('shown',result.latest);
        show(current=>current??'notice');
      }
    } catch {if(!abort.signal.aborted)setFailed(true);}
    finally {if(!abort.signal.aborted)setBusy(false);}
  },[observerToken]);
  useEffect(()=>{
    void check(stored('automatic')!=='off',false);
    return ()=>active.current?.abort();
  },[check]);
  useEffect(()=>{
    if(!panel)return;
    function outside(e:PointerEvent){if(!box.current?.contains(e.target as Node))show(null);}
    function escape(e:KeyboardEvent){if(e.key==='Escape'){show(null);trigger.current?.focus();}}
    document.addEventListener('pointerdown',outside);
    document.addEventListener('keydown',escape);
    return ()=>{document.removeEventListener('pointerdown',outside);document.removeEventListener('keydown',escape);};
  },[panel]);
  const installed=status?.installed??version;
  const available=status?.available&&status.url;
  const detail=busy?'Checking GitHub…':failed||status?.state==='offline'?'GitHub could not be reached.':
    available?'Installed version '+installed:status?.state==='checked'?(status.latest?'You have the latest version.':'No published release found.'):'Automatic checking is off.';
  return <div className="release-updates" ref={box}>
    {available&&<button type="button" className="release-badge" onClick={()=>show(panel==='notice'?null:'notice')} aria-expanded={panel==='notice'} aria-controls={id}>
      <ArrowDownToLine size={13}/> Update available · {status!.latest}
    </button>}
    <button ref={trigger} type="button" className="release-version" aria-label="Version and update settings" aria-expanded={panel==='settings'} aria-controls={id} onClick={()=>show(panel==='settings'?null:'settings')}>
      TwinPALS {installed}<ChevronUp size={12}/>
    </button>
    {panel&&<section id={id} className="release-popover" aria-label="Software updates">
      <div className="release-heading"><strong>{panel==='notice'&&available?'TwinPALS '+status!.latest+' is available':'Software updates'}</strong>
        <button type="button" aria-label="Dismiss update panel" onClick={()=>{show(null);trigger.current?.focus();}}><X size={14}/></button></div>
      <p aria-live="polite">{detail}</p>
      {available&&<a href={status!.url!} target="_blank" rel="noopener noreferrer">View release <ArrowUpRight size={13}/></a>}
      {panel==='settings'&&<div className="release-preferences"><label><input type="checkbox" checked={auto} onChange={e=>{const value=e.target.checked;setAuto(value);remember('automatic',value?'on':'off');if(value)void check(true,false);}}/>Check automatically at startup</label>
        <button type="button" disabled={busy} onClick={()=>void check(true,true)}><RefreshCw size={12}/>Check for updates</button></div>}
    </section>}
  </div>;
}

