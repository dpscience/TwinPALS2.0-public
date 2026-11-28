// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import { useEffect, useLayoutEffect, useId, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { Info } from 'lucide-react';

export function HelpContent({text}:{text:string}){
 return <>{text.split('\n\n').map((section,i)=>{const lines=section.split('\n'),bullets=lines.filter(s=>s.startsWith('- ')),heading=lines.filter(s=>!s.startsWith('- ')).join(' ');return <div className="help-section" key={i}>{heading&&<p>{heading}</p>}{bullets.length>0&&<ul>{bullets.map((line,j)=><li key={j}>{line.slice(2)}</li>)}</ul>}</div>;})}</>;
}
export function Help({text,label,ariaLabel,children,scrollWithin}:{text:string;label?:string;ariaLabel?:string;children?:ReactNode;scrollWithin?:string}){
 const anchor=useRef<HTMLSpanElement>(null),tooltip=useRef<HTMLDivElement>(null),id=useId(),[open,setOpen]=useState(false),[position,setPosition]=useState({left:0,top:0});
 useLayoutEffect(()=>{
  if(!open)return;
  const close=()=>setOpen(false);
  const place=()=>{
   const r=anchor.current?.getBoundingClientRect(),tip=tooltip.current?.getBoundingClientRect();
   if(!r||!tip)return;
   const container=scrollWithin?anchor.current?.closest(scrollWithin)?.getBoundingClientRect():null;
   if(container&&(r.bottom<=container.top||r.top>=container.bottom)){close();return;}
   const top=r.top-tip.height-10>=8?r.top-tip.height-10:r.bottom+10;
   setPosition({left:Math.max(8,Math.min(innerWidth-tip.width-8,r.left-130)),top:Math.max(8,Math.min(innerHeight-tip.height-8,top))});
  };
  place();const onScroll=scrollWithin?place:close;
  window.addEventListener('scroll',onScroll,true);window.addEventListener('resize',close);
  return ()=>{window.removeEventListener('scroll',onScroll,true);window.removeEventListener('resize',close);};
 },[open,scrollWithin]);
 return <span ref={anchor} className={`help ${label?'help-action':''}`} tabIndex={0} role="button" aria-label={ariaLabel??label??text} aria-expanded={open} aria-describedby={open?id:undefined} onClick={e=>{e.preventDefault();setOpen(true);}} onMouseEnter={()=>setOpen(true)} onMouseLeave={()=>setOpen(false)} onFocus={()=>setOpen(true)} onBlur={()=>setOpen(false)} onKeyDown={e=>{if(e.key==='Escape')setOpen(false);if(e.key==='Enter'||e.key===' '){e.preventDefault();setOpen(true);}}}><Info size={label?14:12}/>{label}{open&&createPortal(<div ref={tooltip} id={id} role="tooltip" className={`help-portal ${children?'illustrated-help':''}`} style={{left:position.left,top:position.top}}>{children}<HelpContent text={text}/></div>,document.body)}</span>;
}
export function Field({label,help,children,wide=false,references,diagram}:{label:string;help:string;children:ReactNode;wide?:boolean;references?:ReactNode;diagram?:ReactNode}){return <label className={`field ${wide?'wide':''}`}><span className="field-title">{label}<Help text={help}>{diagram}</Help>{references}</span>{children}</label>;}
function CommittedNumber({value,onChange,...props}:{value:number;onChange:(n:number)=>void;min?:number;max?:number;step?:number|'any';disabled?:boolean}){
 const [draft,setDraft]=useState(String(value)),[invalid,setInvalid]=useState(false),input=useRef<HTMLInputElement>(null);
 useEffect(()=>{setDraft(String(value));setInvalid(false);},[value]);
 const commit=()=>{const el=input.current;if(!el)return;const valid=el.value!==''&&el.checkValidity();setInvalid(!valid);if(valid){const n=el.valueAsNumber;if(n!==value)onChange(n);}else el.reportValidity();};
 return <input {...props} ref={input} type="number" required value={draft} aria-invalid={invalid||undefined} title="Press Enter or leave this field to apply. Escape restores the current value." onChange={e=>{setDraft(e.target.value);setInvalid(false);}} onBlur={commit} onKeyDown={e=>{if(e.key==='Enter'){e.preventDefault();commit();}if(e.key==='Escape'){setDraft(String(value));setInvalid(false);}}}/>;
}
export function NumberField({label,help,value,onChange,min,max,step='any',wide=false,disabled=false,references,diagram,commitOnBlur=false}:{label:string;help:string;value:number;onChange:(n:number)=>void;min?:number;max?:number;step?:number|'any';wide?:boolean;disabled?:boolean;references?:ReactNode;diagram?:ReactNode;commitOnBlur?:boolean}){return <Field label={label} help={help} wide={wide} references={references} diagram={diagram}>{commitOnBlur?<CommittedNumber value={value} onChange={onChange} min={min} max={max} step={step} disabled={disabled}/>:<input type="number" value={Number.isFinite(value)?value:''} min={min} max={max} step={step} disabled={disabled} onChange={e=>onChange(e.target.value===''?0:Number(e.target.value))}/>}</Field>;}
export function Toggle({label,help,value,onChange,diagram,disabled=false,describedBy}:{label:string;help:string;value:boolean;onChange:(v:boolean)=>void;diagram?:ReactNode;disabled?:boolean;describedBy?:string}){return <label className="toggle"><input type="checkbox" checked={value} disabled={disabled} aria-describedby={describedBy} onChange={e=>onChange(e.target.checked)}/><span>{label}</span><Help text={help}>{diagram}</Help></label>;}
