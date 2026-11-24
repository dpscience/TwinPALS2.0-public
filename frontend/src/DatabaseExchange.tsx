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
import type {Entry} from './types';
type Result={entries:Entry[];revision:number};
type Preview={sha256:string;revision:number;added:{id:string;name:string}[];conflicts:{id:string;name:string}[];unchanged:{id:string;name:string}[]};
export function DatabaseExchange({mode,close,changed,browse,flush}:{mode:'import'|'export';close:()=>void;changed:(result:Result)=>void;browse:(kind:string,initial?:string)=>Promise<string|null>;flush:()=>Promise<void>}){
 const confirm=useConfirm(),[paths,setPaths]=usePreference('dialog_paths');
 const kind=mode==='import'?'open_materials':'save_materials';
 const [path,setPath]=useState(paths[kind]??(mode==='export'?'Database.tpcatalogue':'')),[busy,setBusy]=useState(false),[error,setError]=useState(''),[preview,setPreview]=useState<Preview|null>(null),[replace,setReplace]=useState(false);
 const act=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');try{await flush();await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 const update=(value:string)=>{setPath(value);setPreview(null);setError('');setReplace(false);};
 const inspect=()=>act(async()=>{setPreview(await api<Preview>('/materials/import/preview',{method:'POST',body:JSON.stringify({path})}));setPaths(p=>({...p,[kind]:path}));});
 const exportFile=()=>act(async()=>{const save=(overwrite=false)=>api('/materials/export',{method:'POST',body:JSON.stringify({path,overwrite})});try{await save();}catch(e){if(!/already exists/i.test((e as Error).message))throw e;if(!await confirm(`Overwrite this database export?\n\n${path}`,{acceptLabel:'Replace file'}))return;await save(true);}setPaths(p=>({...p,[kind]:path}));close();});
 const importFile=()=>act(async()=>{if(!preview)return;if(!await confirm(`Import ${preview.added.length} new material entries${replace?` and replace ${preview.conflicts.length} existing entries`:''}?`,{title:'Import database?',acceptLabel:'Import',destructive:replace&&preview.conflicts.length>0}))return;const result=await api<Result>('/materials/import',{method:'POST',body:JSON.stringify({path,sha256:preview.sha256,revision:preview.revision,replace_existing:replace})});changed(result);close();});
 return <Modal title={mode==='import'?'Import database':'Export database'} close={close} error={error} busy={busy}>
  <Field label="Database file" help="A .tpcatalogue file contains materials, photomultipliers, digitizers, curves and references, separated by category."><div className="path-control"><input disabled={busy} value={path} onChange={e=>update(e.target.value)}/><button disabled={busy} aria-label="Choose database file" onClick={async()=>{setBusy(true);try{const value=await browse(kind,path);if(value)update(value);}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}><FolderOpen size={15}/></button></div></Field>
  {preview&&<div className="database-import-preview"><div className="exchange-counts"><span>{preview.added.length} new</span><span>{preview.conflicts.length} different</span><span>{preview.unchanged.length} unchanged</span></div>{preview.conflicts.length>0&&<><label className="toggle"><input type="checkbox" checked={replace} disabled={busy} onChange={e=>setReplace(e.target.checked)}/><span>Replace existing entries with matching IDs</span></label><div className="exchange-conflicts">{preview.conflicts.map(e=><div key={e.id}><strong>{e.name}</strong><code>{e.id}</code></div>)}</div></>}<p className="field-note">Entries not included in the file stay in the database.</p></div>}
  <div className="dialog-actions"><button disabled={busy} onClick={close}>Cancel</button>{mode==='export'?<button className="primary" disabled={busy||!path.trim()} onClick={()=>void exportFile()}>Export database</button>:preview?<button className="primary" disabled={busy||(!preview.added.length&&(!replace||!preview.conflicts.length))} onClick={()=>void importFile()}>Import database</button>:<button className="primary" disabled={busy||!path.trim()} onClick={()=>void inspect()}>Preview import</button>}</div>
 </Modal>;
}
