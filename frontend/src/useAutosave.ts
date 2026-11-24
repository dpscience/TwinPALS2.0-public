// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useCallback,useEffect,useMemo,useRef,useState} from 'react';
import type {Profile} from './m1types';
import type {ViewSettings} from './Preferences';
import {api,setCloseState} from './api';

export function useAutosave(profile:Profile|null,ui:ViewSettings,module2:import('./m2types').PulseProfile|null,module3:import('./m3types').LifetimeProfile|null){
 const client=useRef(crypto.randomUUID()),sequence=useRef(0),latest=useRef(''),saved=useRef('');
 const pending=useRef<Promise<void>|null>(null);
 const [status,setStatus]=useState<'saved'|'saving'|'error'>('saved'),[error,setError]=useState('');
 // Live progress re-renders must not serialize the entire application profile.
 const value=useMemo(()=>profile&&module2&&module3?JSON.stringify({profile,ui,module2,module3}):'',[profile,ui,module2,module3]);latest.current=value;
 setCloseState(()=>latest.current?{...JSON.parse(latest.current),client_id:client.current,sequence:++sequence.current}:null);
 const persist=useCallback(()=>{
  if(pending.current)return pending.current;
  if(!latest.current||latest.current===saved.current)return Promise.resolve();
  // One writer, with at most the latest unsaved edit queued behind it. Flush
  // waits for that edit too; progress polls never add work to this queue.
  pending.current=(async()=>{
   setStatus('saving');setError('');
   try{
    while(latest.current&&latest.current!==saved.current){
     const text=latest.current,current=++sequence.current;
     await api('/session',{method:'POST',body:JSON.stringify({...JSON.parse(text),client_id:client.current,sequence:current})});
     saved.current=text;
    }
    setStatus('saved');
   }catch(e){setStatus('error');setError((e as Error).message);throw e;}
   finally{pending.current=null;}
  })();
  return pending.current;
 },[]);
 useEffect(()=>{
  if(!value)return;
  if(!saved.current){saved.current=value;return;}
  if(value===saved.current)return;
  setStatus('saving');const timer=setTimeout(()=>void persist().catch(()=>{}),250);return()=>clearTimeout(timer);
 },[value,persist]);
 useEffect(()=>{
  const hidden=()=>{if(document.visibilityState==='hidden')void persist().catch(()=>{});};
  document.addEventListener('visibilitychange',hidden);
  return()=>document.removeEventListener('visibilitychange',hidden);
 },[persist]);
 return {status,error,flush:persist};
}
