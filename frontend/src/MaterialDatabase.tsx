// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useConfirm} from './Confirm';
import {useRef,useState} from 'react';
import {Database,Download,Plus,Search,Upload} from 'lucide-react';
import type {Entry,MaterialCategory} from './types';
import {api} from './api';
import {usePreference} from './Preferences';
import {categories,categoryHelp,newEntry} from './materialModel';
import {deviceSummary} from './m2types';
import type {Component as Digitizer} from './m2types';
import EntryEditor from './EntryEditor';
import {MaterialStatus} from './materialReadiness';
import {compositionText} from './compositionText';
import {MaterialExchange} from './MaterialExchange';
import {DatabaseExchange} from './DatabaseExchange';

type Result={entries:Entry[];revision:number};
type Props={entries:Entry[];path:string;changed:(result:Result)=>void;browse:(kind:string,initial?:string)=>Promise<string|null>;flush:()=>Promise<void>;onDirty:(dirty:boolean)=>void;locked:boolean};
export default function MaterialDatabase({entries,path,changed,browse,flush,onDirty,locked}:Props){
 const confirm=useConfirm();
 const [category,setCategory]=usePreference('material_category'),[selected,setSelected]=usePreference('material_selected'),[search,setSearch]=usePreference('material_search');
 const [created,setCreated]=useState<Entry|null>(null),[draft,setDraft]=useState<Entry|null>(null),[editorEpoch,setEditorEpoch]=useState(0),[exchange,setExchange]=useState<'import'|'export'|null>(null),[error,setError]=useState(''),[entryExchange,setEntryExchange]=useState<'import'|'export'|null>(null);const dirty=useRef(false);
 const items=entries.filter(e=>e.category===category).sort((a,b)=>a.name.localeCompare(b.name,undefined,{numeric:true}));
 const visible=items.filter(e=>`${e.name} ${e.id}`.toLowerCase().includes(search.toLowerCase()));
 const entry=created??items.find(e=>e.id===selected)??visible[0];
 const leave=async()=>!dirty.current||await confirm('Discard unsaved material changes?');

 const changeCategory=async(value:MaterialCategory)=>{if(!await leave())return;dirty.current=false;setCreated(null);setCategory(value);setSearch('');setSelected(entries.find(e=>e.category===value)?.id??'');setError('');};
 const save=async(value:Entry)=>{const result=await api<Result>('/materials',{method:'POST',body:JSON.stringify({entry:value,...(!created?{expected_revision:entry?.revision}:{})})});dirty.current=false;changed(result);setCreated(null);setSelected(value.id);};
 const remove=async()=>{if(!entry||!await confirm(`Delete “${entry.name}” from the database? M1 files that refer to this ID will require this entry.`))return;try{await flush();const result=await api<Result>(`/materials/${encodeURIComponent(entry.id)}?expected_revision=${entry.revision}`,{method:'DELETE'});dirty.current=false;changed(result);setSelected('');}catch(e){setError((e as Error).message);}};
 return <main className={`material-database ${category==='digitizer'?'digitizer-catalogue':''}`}>
  <aside className="database-categories"><header><Database size={18}/><strong>Database</strong></header><nav aria-label="Material categories">{Object.entries(categories).filter(([key])=>key!=='window').map(([key,label])=><button key={key} className={category===key?'active':''} title={categoryHelp[key as MaterialCategory]} onClick={()=>changeCategory(key as MaterialCategory)}><span>{label}</span><small>{entries.filter(e=>e.category===key).length}</small></button>)}</nav><div className="database-exchange"><button disabled={locked} title="Import an entire database export" onClick={async()=>{if(await leave()){dirty.current=false;setCreated(null);setEditorEpoch(n=>n+1);setExchange('import');}}}><Upload size={13}/>Import</button><button disabled={locked} title="Export all categories, entries, curves and references" onClick={()=>setExchange('export')}><Download size={13}/>Export</button></div><div className="database-location" title={path}><span>Database file</span><code>{path.split(/[\\/]/).at(-1)}</code></div></aside>
  <section className="database-list"><header><h2>{categories[category]}</h2><button disabled={locked} title={`Import a single entry into ${categories[category].toLowerCase()}`} aria-label="Import material entry" onClick={async()=>{if(await leave()){dirty.current=false;setCreated(null);setEditorEpoch(n=>n+1);setEntryExchange('import');}}}><Upload size={14}/></button><button disabled={locked} className="primary" title={`New ${categories[category].toLowerCase()} entry`} onClick={async()=>{if(!await leave())return;dirty.current=false;setDraft(null);setCreated(newEntry(category));setError('');}}><Plus size={14}/>New</button></header><label className="database-search"><Search size={14}/><input aria-label="Search materials" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search name or ID"/></label><div className="database-items" role="list">{created&&<button className="active draft-entry" aria-current="true"><strong>{(draft??created).name}</strong><span className="list-formula" title={(draft??created).category==='pmt'?qePlane(draft??created):compositionText(draft??created)}>{(draft??created).category==='pmt'?qePlane(draft??created):compositionText(draft??created)}</span><MaterialStatus entry={draft??created} draft/></button>}{visible.map(e=><button key={e.id} className={!created&&entry?.id===e.id?'active':''} onClick={async()=>{if(!await leave())return;dirty.current=false;setCreated(null);setSelected(e.id);setError('');}}><strong>{e.name}</strong><span className="list-formula" title={e.category==='pmt'?qePlane(e):e.category==='digitizer'?deviceSummary(e.properties as unknown as Digitizer):compositionText(e)}>{e.category==='pmt'?qePlane(e):e.category==='digitizer'?deviceSummary(e.properties as unknown as Digitizer):compositionText(e)}</span><span className="material-badges"><MaterialStatus entry={e}/>{['sample','foil'].includes(e.category)&&!(e.properties.positron_lifetimes as unknown[])?.length&&<span className="missing-lifetime">Missing lifetime</span>}</span></button>)}{!visible.length&&<p className="empty">No entries found.</p>}</div></section>
  <section className="database-detail">{error&&<div className="inline-error" role="alert">{error}<button onClick={()=>setError('')}>Dismiss</button></div>}{entry?<EntryEditor key={`${entry.id}:${entry.revision}:${editorEpoch}:${created?"draft":"saved"}`} entry={entry} isNew={!!created} onExport={()=>setEntryExchange('export')} exchangeLocked={locked} onSave={save} onDraft={setDraft} onDirty={value=>{dirty.current=value;onDirty(value);}} onDelete={()=>void remove()} onDuplicate={async()=>{if(!await leave())return;dirty.current=false;setDraft(null);setCreated({...structuredClone(entry),id:newEntry(category).id,name:entry.name+' (copy)',revision:1,builtin:false});}} onCancel={()=>{dirty.current=false;setCreated(null);}} browse={browse}/>:<div className="database-empty"><Database size={32}/><h2>{categories[category]}</h2><p>{categoryHelp[category]}</p><button onClick={()=>setCreated(newEntry(category))}><Plus size={14}/>Add entry</button></div>}</section>
 {entryExchange&&<MaterialExchange category={category} entry={entryExchange==='export'?entry:undefined} close={()=>setEntryExchange(null)} browse={browse} flush={flush} changed={result=>{changed(result);setEditorEpoch(n=>n+1);if(result.imported_id){setSearch('');setSelected(result.imported_id);}}}/>}
 {exchange&&<DatabaseExchange mode={exchange} close={()=>setExchange(null)} changed={changed} browse={browse} flush={flush}/>}
 </main>;
}

function qePlane(e:Entry){return e.properties.qe_reference_plane==='external_tube'?'QE measured at PMT window':'QE measured at cathode';}
