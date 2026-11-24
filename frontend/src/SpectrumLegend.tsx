// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {createContext,useContext,useEffect,useState,type CSSProperties,type ReactNode} from 'react';
import {contributionName,traceColor,traceLabel} from './ContributionGraphic';

export const SpectrumHover=createContext<{active:string|null}>({active:null});
export function SpectrumHoverProvider({children,scope}:{children:ReactNode;scope:string}){
 const [active,set]=useState<string|null>(null);
 useEffect(()=>{
  set(null);
  if(!scope)return;
  let position:{x:number;y:number}|null=null,frame=0;
  const trace=(target:EventTarget|null)=>target instanceof Element?target.closest<HTMLElement>('[data-spectrum-trace]')?.dataset.spectrumTrace??null:null;
  const sync=()=>{frame=0;if(position)set(trace(document.elementFromPoint(position.x,position.y)));};
  const pointer=(e:PointerEvent)=>{if(e.pointerType==='touch')return;position={x:e.clientX,y:e.clientY};set(trace(e.target));};
  const leave=(e:PointerEvent)=>{if(!e.relatedTarget){position=null;set(null);}};
  const keyboard=()=>{position=null;};
  const focus=(e:FocusEvent)=>set(trace(e.target));
  const wheel=(e:WheelEvent)=>{position={x:e.clientX,y:e.clientY};};
  const blur=()=>{position=null;set(null);};
  const scroll=()=>{if(!frame&&position)frame=requestAnimationFrame(sync);};
  document.addEventListener('keydown',keyboard,true);
  document.addEventListener('wheel',wheel,{capture:true,passive:true});
  document.addEventListener('pointerover',pointer);
  document.addEventListener('pointermove',pointer);
  document.addEventListener('pointerout',leave);
  document.addEventListener('focusin',focus);
  document.addEventListener('scroll',scroll,true);
  window.addEventListener('blur',blur);
  return ()=>{cancelAnimationFrame(frame);document.removeEventListener('keydown',keyboard,true);document.removeEventListener('wheel',wheel,true);document.removeEventListener('pointerover',pointer);document.removeEventListener('pointermove',pointer);
   document.removeEventListener('pointerout',leave);document.removeEventListener('focusin',focus);document.removeEventListener('scroll',scroll,true);window.removeEventListener('blur',blur);};
 },[scope]);
 return <SpectrumHover.Provider value={{active}}>{children}</SpectrumHover.Provider>;
}
const compactLabels:Record<string,string>={total:'Total',superimposed:'Selected sum',correlated:'Correlated γ',annihilation_pair:'Two 511 γ',same_primary:'Shared γ',accidental:'Accidentals',pileup_same_decay:'1-decay pile-up',pileup_multiple_decays:'Multi-decay pile-up',unresolved:'Unresolved'};
export function SpectrumLegend({available,visible,toggle,source='Legend'}:{available:string[];visible:string[];toggle:(key:string)=>void;source?:string}){
 const {active}=useContext(SpectrumHover);
 return <div className="m3-spectrum-legend" role="group" aria-label={source==='Legend'?'Spectrum trace legend':'Expanded trace legend'}>
 {['total','superimposed',...available].map(key=>{
  const on=visible.includes(key);
  return <button key={key} aria-label={key==='total'?'Total spectrum':contributionName(key)} aria-pressed={on} title={key==='total'?'Total spectrum · all classes and all paths':traceLabel(key)}
   className="legend-badge" style={{'--m3-trace-color':traceColor(key)} as CSSProperties} data-spectrum-trace={key} data-lit={active===key}
   onClick={()=>toggle(key)}><svg aria-hidden="true" width="24" height="12" viewBox="0 0 24 12">
    <path d="M1 6h6m10 0h6" stroke={traceColor(key)} strokeWidth="1.6"/><circle cx="12" cy="6" r={key==='total'?3.4:2.8} stroke={traceColor(key)} strokeWidth="1.5" fill="none"/>
   </svg><span className="m3-legend-long">{traceLabel(key)}</span><span className="m3-legend-short">{compactLabels[key]??traceLabel(key)}</span></button>;
 })}</div>;
}
