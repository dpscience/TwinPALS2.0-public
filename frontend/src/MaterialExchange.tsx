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
import type {Entry,MaterialCategory} from './types';
import {categories} from './materialModel';
const families:Record<MaterialCategory,[string,string]>={sample:['bulk','.tpmaterial'],foil:['bulk','.tpmaterial'],shield:['bulk','.tpmaterial'],coupling:['optical','.tpoptical'],window:['optical','.tpoptical'],scintillator:['scintillator','.tpscint'],pmt:['pmt','.tppmt'],digitizer:['digitizer','.tpdigitizer'],wrapping:['wrapping','.tpwrap']};
type Result={entries:Entry[];revision:number;imported_id?:string};
type Preview={entry:Entry;existing:'unchanged'|'different'|null;duplicates:{id:string;name:string}[];sha256:string;revision:number};
export function MaterialExchange({entry,category,close,changed,browse,flush}:{entry?:Entry;category:MaterialCategory;close:()=>void;changed:(r:Result)=>void;browse:(kind:string,initial?:string)=>Promise<string|null>;flush:()=>Promise<void>}){
 const confirm=useConfirm(),[paths,setPaths]=usePreference('dialog_paths'),[family,extension]=families[category],kind=(entry?'save':'open')+'_entry_'+family;
 const [path,setPath]=useState(entry?entry.id+extension:paths[kind]??''),[identifier,setIdentifier]=useState(''),[preview,setPreview]=useState<Preview|null>(null),[replace,setReplace]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
 const act=async(fn:()=>Promise<void>)=>{setBusy(true);setError('');try{await flush();await fn();}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 const update=(value:string)=>{setPath(value);setIdentifier('');setPreview(null);setReplace(false);setError('');};
 const inspect=()=>act(async()=>{const p=await api<Preview>('/materials/entry/preview',{method:'POST',body:JSON.stringify({path,category,id:identifier||undefined})});setPreview(p);setIdentifier(p.entry.id);setReplace(false);setPaths(p=>({...p,[kind]:path}));});
 const save=()=>act(async()=>{const write=(overwrite=false)=>api('/materials/entry/export',{method:'POST',body:JSON.stringify({path,id:entry!.id,overwrite})});try{await write();}catch(e){if(!/already exists/i.test((e as Error).message))throw e;if(!await confirm(`Replace this material file?\n\n${path}`,{acceptLabel:'Replace file'}))return;await write(true);}setPaths(p=>({...p,[kind]:path}));close();});
 const load=()=>act(async()=>{if(!preview)return;const detail=preview.duplicates.length?' Entries with matching names or content already exist; this will create a separate entry.':'';if(!await confirm(`${replace?'Replace':'Import'} “${preview.entry.name}” in ${categories[category]}?${detail}`,{acceptLabel:replace?'Replace entry':'Import entry',destructive:replace}))return;try{const result=await api<Result>('/materials/entry/import',{method:'POST',body:JSON.stringify({path,category,id:preview.entry.id,revision:preview.revision,sha256:preview.sha256,replace})});changed(result);close();}catch(e){setPreview(null);setReplace(false);throw e;}});
 return <Modal title={entry?'Export material entry':`Import into ${categories[category].toLowerCase()}`} close={close} busy={busy} error={error}>
  <Field label="Material file" help={`Use ${extension}. ${family==='bulk'?'Sample, foil and shielding entries can be exchanged between these categories.':family==='optical'?'Coupling and window entries share this format.':'Contains this material’s values, curves and references.'}`}><div className="path-control"><input disabled={busy} value={path} onChange={e=>update(e.target.value)}/><button title="Choose a material file" disabled={busy} aria-label="Choose material file" onClick={()=>void act(async()=>{const value=await browse(kind,path);if(value)update(value);})}><FolderOpen size={15}/></button></div></Field>
  {!entry&&<Field label="Import identifier" help="Leave blank to keep the file’s ID. Use a new ID to keep an existing entry and import a separate copy."><input disabled={busy} placeholder="From file" value={identifier} onChange={e=>{setIdentifier(e.target.value);setPreview(null);setReplace(false);}}/></Field>}
  {preview&&<div className="entry-import-preview"><strong>{preview.entry.name}</strong><code>{preview.entry.id}</code>{preview.existing?<><p>{preview.existing==='unchanged'?'This entry is already in the database with the same values.':'This identifier already exists with different values.'}</p>{preview.existing==='different'&&<label className="toggle"><input type="checkbox" disabled={busy} checked={replace} onChange={e=>setReplace(e.target.checked)}/>Replace the existing entry</label>}<p className="field-note">Change the import identifier above to keep both entries.</p></>:<p>New entry in {categories[category].toLowerCase()}.</p>}{preview.duplicates.length>0&&<p>Matching name or content: {preview.duplicates.map(e=>`${e.name} (${e.id})`).join(', ')}.</p>}</div>}
  <div className="dialog-actions"><button disabled={busy} title="Close without changing the database" onClick={close}>Cancel</button>{entry?<button className="primary" disabled={busy||!path.trim()} onClick={()=>void save()}>Export entry</button>:preview?<button className="primary" disabled={busy||!!preview.existing&&!replace} onClick={()=>void load()}>Import entry</button>:<button className="primary" disabled={busy||!path.trim()} onClick={()=>void inspect()}>Preview import</button>}</div>
 </Modal>;
}
