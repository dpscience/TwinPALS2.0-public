// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect,useRef,useState} from 'react';
import type {PointerEvent,WheelEvent} from 'react';
import {wheelRange} from './plotRange';
import type {Range} from './plotRange';

export function useDensityZoom(key:string,expanded:boolean,x:Range,y:Range,box:{left:number;top:number;pw:number;ph:number}){
 const [view,setView]=useState<{x:Range;y:Range}|null>(null),[band,setBand]=useState<number[]|null>(null);
 const drag=useRef<number[]|null>(null);
 useEffect(()=>{setView(null);setBand(null);drag.current=null;},[key,expanded]);
 const xr=view?.x??x,yr=view?.y??y,{left,top,pw,ph}=box;
 const point=(e:PointerEvent<SVGSVGElement>|WheelEvent<SVGSVGElement>)=>{
  const p=new DOMPoint(e.clientX,e.clientY).matrixTransform(e.currentTarget.getScreenCTM()!.inverse());
  return [Math.max(0,Math.min(1,(p.x-left)/pw)),Math.max(0,Math.min(1,(p.y-top)/ph))];
 };
 const handlers={onDoubleClick:()=>setView(null),onWheel:(e:WheelEvent<SVGSVGElement>)=>{if(!expanded)return;const [px,py]=point(e);setView(e.shiftKey?{x:xr,y:wheelRange(yr,1-py,e.deltaY)}:{x:wheelRange(xr,px,e.deltaY),y:yr});},
  onPointerDown:(e:PointerEvent<SVGSVGElement>)=>{if(!expanded||e.button!==0)return;drag.current=point(e);setBand([...drag.current,...drag.current]);e.currentTarget.setPointerCapture(e.pointerId);},
  onPointerMove:(e:PointerEvent<SVGSVGElement>)=>{if(drag.current)setBand([...drag.current,...point(e)]);},
  onPointerUp:(e:PointerEvent<SVGSVGElement>)=>{if(band&&Math.abs(band[2]-band[0])*pw>4&&Math.abs(band[3]-band[1])*ph>4){const [a,b,c,d]=band;setView({x:[xr[0]+Math.min(a,c)*(xr[1]-xr[0]),xr[0]+Math.max(a,c)*(xr[1]-xr[0])],y:[yr[1]-Math.max(b,d)*(yr[1]-yr[0]),yr[1]-Math.min(b,d)*(yr[1]-yr[0])]});}drag.current=null;setBand(null);if(e.currentTarget.hasPointerCapture(e.pointerId))e.currentTarget.releasePointerCapture(e.pointerId);},
  onPointerCancel:()=>{drag.current=null;setBand(null);}};
 return {x:xr,y:yr,handlers,reset:()=>setView(null),band:band?{x:left+Math.min(band[0],band[2])*pw,y:top+Math.min(band[1],band[3])*ph,width:Math.abs(band[2]-band[0])*pw,height:Math.abs(band[3]-band[1])*ph}:null};
}
