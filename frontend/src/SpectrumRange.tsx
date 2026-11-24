// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect,useId,useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {ScanLine} from 'lucide-react';
import type {HeightViewport,SpectrumDisplay} from './m3types';

type Props={title:string;channel?:number;domain:[number,number];adc?:number;view:SpectrumDisplay;patch:(v:Partial<SpectrumDisplay>)=>void};
export function SpectrumRange({title,channel,domain,adc,view,patch}:Props){
 const trigger=useRef<HTMLButtonElement>(null),panel=useRef<HTMLDivElement>(null),id=useId();
 const [open,setOpen]=useState(false),[position,setPosition]=useState({left:0,top:0});
 const [limits,setLimits]=useState(['','']),[error,setError]=useState('');
 const height=channel!==undefined,unit=height?'mV':'ns';
 const mode=height?view.phs_views?.[channel]?.mode??'full':null;
 function close(){setOpen(false);trigger.current?.focus();}
 useLayoutEffect(()=>{
  if(!open)return;
  const place=()=>{const b=trigger.current?.getBoundingClientRect(),p=panel.current?.getBoundingClientRect();if(b&&p)setPosition({left:Math.max(8,Math.min(b.right-p.width,window.innerWidth-p.width-8)),top:b.bottom+p.height+12<=innerHeight?b.bottom+5:Math.max(8,b.top-p.height-5)});};
  place();window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
  panel.current?.querySelector<HTMLElement>(height?'button':'input')?.focus();
  return()=>{window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);};
 },[open,height]);
 useEffect(()=>{
  if(!open)return;
  const outside=(e:PointerEvent)=>{if(e.target instanceof Node&&!panel.current?.contains(e.target)&&!trigger.current?.contains(e.target))setOpen(false);};
  const escape=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();e.stopImmediatePropagation();close();}};
  document.addEventListener('pointerdown',outside);window.addEventListener('keydown',escape,true);
  return()=>{document.removeEventListener('pointerdown',outside);window.removeEventListener('keydown',escape,true);};
 },[open]);
 function heightView(next:HeightViewport){
  const phs_views:[HeightViewport,HeightViewport]=[...(view.phs_views??[{mode:'full'},{mode:'full'}] as const)];
  phs_views[channel!]=next;patch({phs_views});close();
 }
 function apply(){
  const [lo,hi]=limits.map(Number);
  if(limits.some(v=>!v.trim())||!Number.isFinite(lo)||!Number.isFinite(hi)||lo>=hi){
   setError('Enter increasing, finite limits.');return;
  }
  if(height){
   if(lo<0||hi>adc!){setError('Choose a range within 0–'+adc+' mV.');return;}
   heightView({mode:'custom',limits:[lo,hi]});
  }else{
   if(lo<view.low_ns||hi>view.high_ns){setError(`Choose limits within the configured range of ${view.low_ns} to ${view.high_ns} ns.`);return;}
   patch({time_view:lo===view.low_ns&&hi===view.high_ns?null:[lo,hi]});close();
  }
 }
 const caption=height?({full:'Full ADC',start:'Start window',stop:'Stop window',custom:'Custom range'} as const)[mode!]:'Time range';
 return <><button type="button" ref={trigger} className="m3-range-trigger" aria-label={'Plot range · '+title} aria-expanded={open} aria-controls={open?id:undefined}
  title={'Set the '+(height?'pulse-height':'lifetime')+' range for both filter stages'} onClick={()=>{if(!open){setLimits(domain.map(String));setError('');}setOpen(!open);}}><ScanLine size={13}/><span>{caption}</span></button>
 {open&&createPortal(<div ref={panel} id={id} role="dialog" aria-label={'Plot range · '+title} className="m3-spectrum-range" style={position}>
  <strong>{height?'Pulse height · '+'AB'[channel!]:'Lifetime range'}</strong>
  {height&&<div className="m3-range-presets">{([['full','Full ADC'],['start','Focus Start'],['stop','Focus Stop']] as const).map(([key,label])=><button key={key} aria-pressed={mode===key} onClick={()=>heightView({mode:key})}>{label}</button>)}</div>}
  <form onSubmit={e=>{e.preventDefault();apply();}}><div>{['From','To'].map((label,i)=><label key={label}>{label} · {unit}<input type="number" step="any" required aria-label={label+' · '+unit} value={limits[i]} onChange={e=>{setLimits(limits.map((v,j)=>i===j?e.target.value:v));setError('');}}/></label>)}</div>
  {error&&<small role="alert">{error}</small>}<button className="primary">Set custom range</button></form>
 </div>,document.body)}</>;
}
