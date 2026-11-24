// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useState} from 'react';
import {FolderOpen} from 'lucide-react';
import {Modal} from './Modal';
import {Field} from './Fields';
import {api} from './api';
import {usePreference} from './Preferences';
import {useConfirm} from './Confirm';
import type {State} from './m1types';
export function ProfileExchange({mode,close,loaded,browse,flush}:{mode:'load'|'save';close:()=>void;loaded:(state:State)=>void;browse:(kind:string,initial?:string)=>Promise<string|null>;flush:()=>Promise<void>}){
 const confirm=useConfirm(),[paths,setPaths]=usePreference('dialog_paths'),kind=mode==='load'?'open_app_profile':'save_app_profile';
 const [path,setPath]=useState(paths[kind]??(mode==='save'?'TwinPALS.tpprofile':'')),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const apply=async()=>{setBusy(true);setError('');try{
  await flush();
  if(mode==='load'){
   const preview=await api<{sha256:string}>('/profile/preview',{method:'POST',body:JSON.stringify({path})});
   if(!await confirm('Replace the current profile with this file? Module settings, view choices and remembered paths will be replaced.',{title:'Load profile?',acceptLabel:'Load profile'}))return;
   const value=await api<State>('/profile/import',{method:'POST',body:JSON.stringify({path,sha256:preview.sha256,confirmed:true})});loaded(value);
  }else{
   const save=(overwrite=false)=>api('/profile/export',{method:'POST',body:JSON.stringify({path,overwrite})});
   try{await save();}catch(e){if(!/already exists/i.test((e as Error).message))throw e;if(!await confirm(`Overwrite this profile file?\n\n${path}`,{acceptLabel:'Replace file'}))return;await save(true);}
   setPaths(p=>({...p,[kind]:path}));
  }
  close();
 }catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 return <Modal title={mode==='load'?'Load profile':'Save profile'} close={close} busy={busy} error={error}><Field label="Profile file" help="A .tpprofile stores all module settings and interface preferences, including remembered paths. Referenced materials come from the separate material database."><div className="path-control"><input disabled={busy} value={path} onChange={e=>{setPath(e.target.value);setError('');}}/><button disabled={busy} aria-label="Choose profile file" onClick={async()=>{setBusy(true);try{const value=await browse(kind,path);if(value){setPath(value);setError('');}}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}><FolderOpen size={15}/></button></div></Field><div className="dialog-actions"><button disabled={busy} onClick={close}>Cancel</button><button className="primary" disabled={busy||!path.trim()} onClick={()=>void apply()}>{mode==='load'?'Load profile':'Save profile'}</button></div></Modal>;
}
