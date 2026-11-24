// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect, useId, useRef, useState} from 'react';
import {createPortal} from 'react-dom';
import {BookOpen, ExternalLink, Scale, Search, X} from 'lucide-react';
import './legal.css';

type Document = {label: string; file: string; sha256: string; format?: string};
type Component = {id: string; name: string; version: string; group: string; license: string; note: string; url: string | null; documents: Document[]};
type Catalog = {reviewed: string; version: string; components: Component[]};

async function readLocal(url: string, signal: AbortSignal) {
  const response = await fetch(url, {signal, credentials: 'same-origin'});
  if (!response.ok) throw Error('The local license file could not be opened.');
  return response;
}

export default function LegalNotices() {
  const [open, setOpen] = useState(false);
  return <><button type="button" className="legal-trigger" onClick={()=>setOpen(true)}><Scale size={13} aria-hidden/><span>Third-party licenses</span></button>
    {open && createPortal(<NoticeDialog onClose={()=>setOpen(false)}/>, document.body)}</>;
}

function NoticeDialog({onClose}: {onClose: ()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null);
  const title=useId();
  const [catalog,setCatalog]=useState<Catalog>();
  const [error,setError]=useState('');
  const [query,setQuery]=useState('');
  const [choice,setChoice]=useState('twinpals');
  const [docIndex,setDocIndex]=useState(0);
  useEffect(()=>{
    const node=dialog.current!;
    const trigger=document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node.showModal();
    return ()=>{node.close();trigger?.focus();};
  },[]);
  useEffect(()=>{
    const controller=new AbortController();
    readLocal('/legal/index.json',controller.signal).then(r=>r.json()).then(setCatalog).catch(e=>{
      if(!controller.signal.aborted) setError(String(e.message));
    });
    return ()=>controller.abort();
  },[]);
  const terms=query.trim().toLowerCase();
  const matching=(catalog?.components??[]).filter(c=>[c.name,c.group,c.license,c.version].join(' ').toLowerCase().includes(terms));
  const selected=matching.find(c=>c.id===choice)??matching[0];
  const doc=selected?.documents[docIndex]??selected?.documents[0];
  return <dialog ref={dialog} aria-labelledby={title} className="legal-dialog" onCancel={e=>{e.preventDefault();onClose();}}>
    <div className="legal-head"><Scale size={21}/><div><h2 id={title}>Third-party licenses</h2><small>{catalog ? <>Version {catalog.version} · Reviewed <time dateTime={catalog.reviewed}>{catalog.reviewed}</time></> : 'TwinPALS 2.0'}</small></div>
      <button className="legal-close" aria-label="Close licenses" onClick={onClose}><X size={17}/></button></div>
    <div className="legal-body"><nav aria-label="License components" className="legal-nav">
      <label className="legal-search"><Search size={15}/><input type="search" aria-label="Find a component or license" placeholder="Find a component or license" value={query} onChange={e=>{setQuery(e.target.value);setDocIndex(0);}}/></label>
      <div className="legal-components">{Array.from(new Set(matching.map(c=>c.group))).map(group=><section key={group}><h3>{group}</h3>
        {matching.filter(c=>c.group===group).map(c=><button key={c.id} aria-current={selected?.id===c.id?'true':undefined} onClick={()=>{setChoice(c.id);setDocIndex(0);}}>{c.name}</button>)}</section>)}
      {!matching.length&&<p role="status">{error || (catalog?'No matching components.':'Loading local notices…')}</p>}</div></nav>
      <article className="legal-reading" aria-label="Selected license">{selected && <>
        <h3>{selected.name}</h3><p className="legal-meta">{selected.version && <span>{selected.version}</span>}<span>{selected.license}</span></p>
        <p>{selected.note}</p>
        {selected.group==='Project' && <p className="legal-contact"><strong>TwinPALS contact</strong> <a href="mailto:twinpals@proton.me">twinpals@proton.me</a></p>}
        {selected.id==='twinpals' && <div className="legal-basis"><BookOpen size={16}/><div><strong>Conceptual foundation</strong><br/>Dominik Boras · Doctoral dissertation · Universität Würzburg · 2024<br/>
          <a href="https://doi.org/10.25972/OPUS-37663" target="_blank" rel="noreferrer">10.25972/OPUS-37663</a></div></div>}
        {selected.url && <a href={selected.url} target="_blank" rel="noreferrer" className="legal-upstream">{selected.id==='twinpals-mcp'?'Protocol specification':selected.id==='twinpals'?'MIT license':'Upstream reference'} <ExternalLink size={12}/></a>}
        {doc && <><div className="legal-doc-choice">{selected.documents.length>1?<><label htmlFor={title+'-document'}>Document</label><select id={title+'-document'} value={selected.documents.indexOf(doc)} onChange={e=>setDocIndex(Number(e.target.value))}>{selected.documents.map((d,i)=><option key={d.file} value={i}>{d.label}</option>)}</select></>:<strong>{doc.label}</strong>}
          <a href={'/legal/'+doc.file} download>Save original</a></div><DocumentText key={doc.file} doc={doc.file.endsWith('.rtf') ? selected.documents[0] : doc}/></>}
      </>}</article></div>
  </dialog>;
}

function DocumentText({doc}:{doc:Document}) {
  const [value,setValue]=useState('Loading document…');
  useEffect(()=>{
    const controller=new AbortController();
    readLocal('/legal/'+doc.file,controller.signal).then(r=>r.text()).then(setValue).catch(e=>{
      if(!controller.signal.aborted) setValue(e.message);
    });
    return ()=>controller.abort();
  },[doc.file]);
  return <pre className="legal-text" tabIndex={0} aria-label={doc.label}>{value}</pre>;
}
