// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useRef,type KeyboardEvent,type PointerEvent, type ReactNode} from 'react';
import type {Axes,LifetimeGate} from './m3types';

type Point=[number,number];
type Handle='line'|'slope'|'below'|'above'|'centre'|'radius1'|'radius2'|'outline';
type Drag={handle:Handle;gate:LifetimeGate;start:Point;pointer:number};
type Props={gate:LifetimeGate;kind:'area'|'shape';role:'start'|'stop';axes:Axes;
 sx:(v:number)=>number;sy:(v:number)=>number;position:(e:PointerEvent)=>Point;
 change:(g:LifetimeGate,preview:boolean)=>void;freeze:(range:Axes|null)=>void;placing:boolean};
const names:Record<Handle,string>={line:'Move centre line',slope:'Change slope',below:'Lower width',above:'Upper width',centre:'Move ellipse centre',radius1:'First radius',radius2:'Second radius',outline:'Scale ellipse'};
const limit=(v:number)=>Math.max(.00001,v);
function adjusted(g:LifetimeGate,handle:Handle,start:Point,now:Point):LifetimeGate{
 const [dx,dy]=[now[0]-start[0],now[1]-start[1]],a=g.area,s=g.shape;
 const delta=dy-a.slope*dx;
 if(handle==='below'||handle==='above')return {...g,area:{...a,[handle]:Math.max(0,a[handle]+(handle==='above'?delta:-delta))}};
 if(handle==='line')return {...g,area:{...a,intercept:a.intercept+delta}};
 if(handle==='slope'){
  const anchor=g.phs.low,lever=now[0]-anchor;
  if(Math.abs(lever)<Math.max(.00001,(g.phs.high-anchor)*.02))return g;
  const slope=a.slope+(dy-a.slope*dx)/lever;
  return {...g,area:{...a,slope,intercept:a.intercept+(a.slope-slope)*anchor}};
 }
 if(handle==='centre')return {...g,shape:{...s,rise:Math.max(0,s.rise+dx),fall:Math.max(0,s.fall+dy)}};
 const theta=s.angle_deg*Math.PI/180,c=Math.cos(theta),sn=Math.sin(theta);
 if(handle==='radius1')return {...g,shape:{...s,radius_rise:limit(s.radius_rise+dx*c+dy*sn)}};
 if(handle==='radius2')return {...g,shape:{...s,radius_fall:limit(s.radius_fall-dx*sn+dy*c)}};
 const distance=([x,y]:Point)=>Math.hypot(((x-s.rise)*c+(y-s.fall)*sn)/s.radius_rise,((y-s.fall)*c-(x-s.rise)*sn)/s.radius_fall);
 const scale=distance(now)/Math.max(.00001,distance(start));
 return {...g,shape:{...s,radius_rise:limit(s.radius_rise*scale),radius_fall:limit(s.radius_fall*scale)}};
}
export function LifetimeGateOverlay(p:Props){
 const active=useRef<Drag|null>(null);
 const {gate:g,sx,sy,axes}=p,[x0,x1,y0,y1]=axes;
 const a=g.area,s=g.shape,ink=p.role==='start'?'#075b64':'#653786',enabled=g[p.kind].enabled;
 function begin(e:PointerEvent<SVGElement>,handle:Handle){
  if(p.placing||e.button!==0||active.current)return;
  e.stopPropagation();e.currentTarget.setPointerCapture(e.pointerId);
  active.current={handle,gate:g,start:p.position(e),pointer:e.pointerId};p.freeze([...axes]);
 }
 function move(e:PointerEvent<SVGGElement>,end=false){
  const d=active.current;if(!d||e.pointerId!==d.pointer)return;e.stopPropagation();
  p.change(adjusted(d.gate,d.handle,d.start,p.position(e)),!end);
  if(end){active.current=null;p.freeze(null);}
 }
 function cancel(){
  if(!active.current)return;
  const original=active.current.gate;active.current=null;p.change(original,true);p.freeze(null);
 }
 function arrow(e:KeyboardEvent<SVGElement>,handle:Handle,point:Point){
  if(e.key==='Escape'){cancel();return;}
  const i=['ArrowLeft','ArrowRight','ArrowDown','ArrowUp'].indexOf(e.key);if(i<0)return;
  e.preventDefault();e.stopPropagation();const f=e.shiftKey?.025:.0025;
  const dest:Point=[point[0]+(i===0?-1:i===1?1:0)*(x1-x0)*f,point[1]+(i===2?-1:i===3?1:0)*(y1-y0)*f];
  p.change(adjusted(g,handle,point,dest),false);
 }
 const grip=(handle:Handle,pt:Point,diamond=false)=><g key={handle} className={'m3-gate-grip '+handle} role="button" tabIndex={p.placing?-1:0} aria-label={names[handle]} transform={`translate(${sx(pt[0])} ${sy(pt[1])})`}
  onPointerDown={e=>begin(e,handle)} onKeyDown={e=>arrow(e,handle,pt)}><title>{names[handle]} · drag or use the arrow keys</title>
  <circle r="9" fill="transparent" stroke="none"/>{diamond?<path d="M0 -4.5L4.5 0 0 4.5 -4.5 0Z" fill="white" stroke={ink} strokeWidth="2"/>:<circle r="3.8" fill={ink} stroke="white" strokeWidth="1.7"/>}</g>;
 const stroke=(d:string,handle:Handle,dashed=false)=><g className={'m3-gate-edge '+handle} key={handle}><path d={d} fill="none" stroke="white" strokeWidth="4" opacity=".94"/>
  <path d={d} fill="none" stroke={ink} strokeWidth="1.8" strokeDasharray={dashed?'6 3':undefined}/>
  <path d={d} className="m3-gate-hit" fill="none" stroke="transparent" strokeWidth="10" onPointerDown={e=>begin(e,handle)}><title>{names[handle]}</title></path></g>;
 const pt=(x:number,y:number)=>sx(x)+' '+sy(y);
 let body:ReactNode;
 if(p.kind==='area'){
  const {low,high}=g.phs,span=high-low,line=(x:number)=>a.slope*x+a.intercept,offset=(f:number,v:number):Point=>{const x=low+span*f;return [x,line(x)+v];};
  const band=(v:number)=>'M'+pt(low,line(low)+v)+' L'+pt(high,line(high)+v);
  const d=band(a.above)+' L'+pt(high,line(high)-a.below)+' L'+pt(low,line(low)-a.below)+' Z';
  body=<><path d={d} fill={ink} fillOpacity={enabled?.14:.055} stroke={ink} strokeWidth="1"/>
   {stroke('M'+pt(x0,line(x0))+' L'+pt(x1,line(x1)),'line',true)}
   {stroke(band(-a.below),'below',!enabled)}{stroke(band(a.above),'above',!enabled)}
   {grip('below',offset(.25,-a.below),true)}{grip('line',offset(.49,0))}{grip('above',offset(.7,a.above),true)}{grip('slope',offset(.94,0),true)}</>;
 }else{
  const theta=s.angle_deg*Math.PI/180,c=Math.cos(theta),sn=Math.sin(theta);
  const at=(t:number):Point=>{const u=s.radius_rise*Math.cos(t),v=s.radius_fall*Math.sin(t);return [s.rise+u*c-v*sn,s.fall+u*sn+v*c];};
  const outline=Array.from({length:97},(_,i)=>(i?'L':'M')+pt(...at(i*Math.PI/48))).join(' ')+' Z';
  body=<><path d={outline} fill={ink} fillOpacity={enabled?.12:.045}/>{stroke(outline,'outline',!enabled)}
   <path d={'M'+pt(...at(0))+' L'+pt(s.rise,s.fall)+' L'+pt(...at(Math.PI/2))} fill="none" stroke={ink} strokeDasharray="2 3" pointerEvents="none"/>
   {grip('radius1',at(0),true)}{grip('radius2',at(Math.PI/2),true)}{grip('centre',[s.rise,s.fall])}</>;
 }
 return <g className="m3-gate" pointerEvents={p.placing?'none':undefined} onPointerMove={e=>move(e)} onPointerUp={e=>move(e,true)} onPointerCancel={cancel} onLostPointerCapture={cancel}>{body}</g>;
}
