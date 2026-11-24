// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {createPortal} from 'react-dom';
import {createContext,useContext,useEffect,useId,useLayoutEffect,useMemo,useRef,useState} from 'react';
import type {PointerEvent as ReactPointer,WheelEvent as ReactWheel,ReactNode} from 'react';
import {Expand,Maximize,Download,X} from 'lucide-react';
import {Help} from './Fields';
import {ProcessingActivity,type Activity} from './ProcessingActivity';
import {lockBackground} from './modalInert';
import {exportPlot} from './Plot';
import type {LifetimeGate,LifetimeChannel,MeasurementGrid} from './m3types';
import {SpectrumHover} from './SpectrumLegend';
import {spectrumCirclePath,spectrumStepPath} from './spectrumAnalysis';
import {LifetimeGateOverlay} from './LifetimeGateOverlay';
import {moveEdge,type WindowRole} from './lifetimeEditing';
import './module3.css';

type Point=[number,number];type Range=[number,number,number,number];
type Trace={key?:string;name:string;color:string;points:Point[];dashed?:boolean};
type Edge={role:WindowRole;edge:'low'|'high'};
type Windows={channel:LifetimeChannel;onEdge?:(role:WindowRole,edge:'low'|'high',value:number)=>void};
type Props={activityKey?:string;title:string;xLabel:string;yLabel:string;points:Point[];color?:string;log?:boolean;binWidth?:number;yMax?:number;disabled?:boolean;density?:boolean;
 gate?:LifetimeGate;onGate?:(gate:LifetimeGate,preview:boolean)=>void;kind?:'area'|'shape';onCenter?:(x:number,y:number)=>void;help:string;busy?:boolean;grid?:MeasurementGrid;locked?:boolean;tools?:ReactNode;role?:WindowRole;
 traces?:Trace[];circles?:boolean;expandedLegend?:ReactNode;histogram?:boolean;windows?:Windows;domain?:Point;timeViewport?:{limits:Point;change:(x:Point|null)=>void};footer?:ReactNode;empty?:string};
const palette=[[222,240,249],[127,196,218],[47,145,170],[252,215,113],[238,128,53],[191,47,38],[129,18,38]];
export function heatColor(n:number,max:number){
 const at=Math.log1p(n)/Math.log1p(Math.max(1,max))*(palette.length-1),i=Math.min(palette.length-2,Math.floor(at));
 return palette[i].map((v,k)=>Math.round(v+(palette[i+1][k]-v)*(at-i)));
}
const renderedHeat=new WeakMap<MeasurementGrid['cells'],string>();
function heatImage(g:MeasurementGrid){
 const cached=renderedHeat.get(g.cells);if(cached)return cached;
 const canvas=document.createElement('canvas');canvas.width=g.nx;canvas.height=g.ny;
 const ctx=canvas.getContext('2d');if(!ctx)return null;
 const pixels=ctx.createImageData(g.nx,g.ny),max=g.max_cell??g.cells.reduce((m,c)=>Math.max(m,c[1]),0);
 const colors=new Map<number,number[]>();
 for(const [index,n] of g.cells){const at=4*((g.ny-1-Math.floor(index/g.nx))*g.nx+index%g.nx);
  let rgba=colors.get(n);if(!rgba){rgba=[...heatColor(n,max),255];colors.set(n,rgba);}pixels.data.set(rgba,at);}
 ctx.putImageData(pixels,0,0);const url=canvas.toDataURL();renderedHeat.set(g.cells,url);return url;
}
function densityTable(g:MeasurementGrid,kind:'csv'|'txt'){
 const sep=kind==='csv'?',':'\t',[a,b,c,d]=g.axes,dx=(b-a)/g.nx,dy=(d-c)/g.ny;
 return [['x_low','x_high','y_low','y_high','pulses'],...g.cells.map(([i,n])=>{const x=a+(i%g.nx)*dx,y=c+Math.floor(i/g.nx)*dy;return [x,x+dx,y,y+dy,n];})].map(r=>r.join(sep)).join('\n');
}
const labels={start:'Start',stop:'Stop'},colors={start:'#168782',stop:'#8462b0'};
const short=(n:number)=>Number(n.toPrecision(4)).toLocaleString(undefined,{maximumFractionDigits:4});
function TraceLayer({traces,paths,circles,histogram}:{traces:Trace[];paths:string[];circles?:boolean;histogram?:boolean}){
 const {active}=useContext(SpectrumHover);
 const index=active?traces.findIndex(t=>t.key===active):-1;
 const draw=(t:Trace,i:number)=><path key={t.key??t.name} data-series={t.key} d={paths[i]} stroke={t.color} opacity={index>=0&&i!==index?0.18:1}
  strokeDasharray={!circles&&histogram&&t.dashed?'4 2':undefined} strokeWidth={circles?1.35:histogram?1.65:2.7} strokeLinecap={histogram?'butt':'round'} fill="none"/>;
 return <>{traces.map((t,i)=>i===index?null:draw(t,i))}{index>=0&&draw(traces[index],index)}</>;
}

export const LifetimePlotActivity=createContext<Record<string,Activity>>({});
export function LifetimePlot(p:Props){
 const activity=useContext(LifetimePlotActivity)[p.activityKey??''];
 const [full,setFull]=useState(false),[range,setRange]=useState<Range|null>(null);

 const [box,setBox]=useState<[Point,Point]|null>(null),[hover,setHover]=useState<Point|null>(null);
 const [drag,setDrag]=useState<(Edge&{value:number;bounds:Range})|null>(null);
 const clip=useId(),svg=useRef<SVGSVGElement>(null),canvas=useRef<HTMLDivElement>(null);
 const [size,setSize]=useState({width:620,height:265});
 useLayoutEffect(()=>{const el=canvas.current;if(!el)return;const observer=new ResizeObserver(([entry])=>{
  const width=Math.max(220,Math.round(entry.contentRect.width)),height=Math.max(140,Math.round(entry.contentRect.height));
  setSize(old=>old.width===width&&old.height===height?old:{width,height});});observer.observe(el);return ()=>observer.disconnect();},[full]);
 useEffect(()=>{if(!full)return;const close=(e:KeyboardEvent)=>{if(e.key==='Escape')setFull(false)};window.addEventListener('keydown',close);return ()=>window.removeEventListener('keydown',close);},[full]);
 const traces=useMemo(()=>p.traces??[{name:p.title,color:p.color??'#168e91',points:p.points}],[p.traces,p.title,p.color,p.points]);
 const bounds=useMemo<Range>(()=>{let x0=Infinity,x1=-Infinity,y1=0;
  for(const trace of traces)for(const [x,y] of trace.points){x0=Math.min(x0,x);x1=Math.max(x1,x);y1=Math.max(y1,y);}
  if(p.domain)[x0,x1]=p.domain;
  if(!Number.isFinite(x0)){x0=0;x1=1;}if(x0===x1){x0-=.5;x1+=.5;}
  return [x0,x1,p.log ? 0.75 : 0,Math.max(p.log?10:1,(p.yMax??y1)*(p.log?1.35:1.06))];
 },[traces,p.log,p.domain,p.yMax]);
 const [gateBounds,freezeGate]=useState<Range|null>(null);
 const axes:Range=p.grid&&p.density?p.grid.axes:bounds;
 const timeViewport=p.timeViewport;
 const localRange=range&&(!timeViewport||(range[0]===axes[0]&&range[1]===axes[1]))?range:null;
 const [x0,x1,y0,y1]=drag?.bounds??gateBounds??(p.locked?axes:localRange??axes);
 const analysisPlot=!!p.expandedLegend;
 useEffect(()=>{if(analysisPlot)setRange(old=>old&&timeViewport&&old[0]===p.domain?.[0]&&old[1]===p.domain?.[1]?old:null);},[analysisPlot,p.domain?.[0],p.domain?.[1],p.binWidth]);
 function zoom(next:Range,keepVerticalZoom=true){
  if(timeViewport){
   const [lo,hi]=timeViewport.limits;
   next[0]=Math.max(lo,next[0]);next[1]=Math.min(hi,next[1]);
   if(next[0]>=next[1])return;
   if(next[0]!==x0||next[1]!==x1)timeViewport.change(next[0]===lo&&next[1]===hi?null:[next[0],next[1]]);
  }
  setRange(timeViewport&&!keepVerticalZoom?null:next);
 }
 const fitAll=()=>{setRange(null);if(timeViewport)timeViewport.change(null);};
 const W=size.width,H=size.height,L=W<390?45:58,R=18,T=p.windows?(p.windows.onEdge?56:40):21,B=40;
 const w=W-L-R,h=H-T-B,fy=(v:number)=>p.log?Math.log10(Math.max(.75,v)):v;
 const axisFractions=[0,.25,.5,.75,1];
 const decadeTicks=p.log?Array.from({length:Math.max(0,Math.floor(fy(y1))-Math.ceil(fy(y0))+1)},(_,i)=>10**(Math.ceil(fy(y0))+i)):[];
 const withinDecade=axisFractions.map(f=>Math.round(10**(fy(y0)+f*(fy(y1)-fy(y0)))));
 const logTicks=decadeTicks.length>=2?decadeTicks:[...new Set(withinDecade)].filter(y=>y>=y0&&y<=y1);
 const yTicks=p.log?logTicks:axisFractions.map(f=>y0+f*(y1-y0));
 const sx=(x:number)=>L+(x-x0)/(x1-x0)*w,sy=(y:number)=>T+(1-(fy(y)-fy(y0))/(fy(y1)-fy(y0)))*h;
 const pos=(e:ReactPointer|ReactWheel):Point=>{const r=svg.current!.getBoundingClientRect();return [Math.max(L,Math.min(W-R,(e.clientX-r.left)/r.width*W)),Math.max(T,Math.min(H-B,(e.clientY-r.top)/r.height*H))];};
 const coord=([x,y]:Point):Point=>[x0+(x-L)/w*(x1-x0),p.log?10**(fy(y1)-(y-T)/h*(fy(y1)-fy(y0))):y1-(y-T)/h*(y1-y0)];
 const heat=useMemo(()=>p.density&&p.grid?.visible?heatImage(p.grid):null,[p.grid,p.density]);
 const path=(trace:Trace)=>{
  if(p.circles)return spectrumCirclePath(trace.points,sx,sy,x0,x1,trace.key==='total'?2.9:trace.key==='superimposed'?3.7:2.15);
  if(p.binWidth)return spectrumStepPath(trace.points,sx,sy,x0,x1,y0,p.binWidth);
  let line='';let first=true;for(const [x,y] of trace.points){if(p.log&&y<=0)continue;
  const xx=sx(x).toFixed(2),yy=sy(y).toFixed(2);
  if(p.histogram){line+=first?'M'+xx+' '+yy:'H'+xx+'V'+yy;}else if(x>=x0&&x<=x1){line+='M'+xx+' '+yy+'h.01';}first=false;}return line;};
 const paths=useMemo(()=>traces.map(path),[traces,x0,x1,y0,y1,W,H,T,p.log,p.histogram,p.binWidth,p.circles]);
 const cancel=()=>{setDrag(null);setBox(null);};
 const beginEdge=(e:ReactPointer,role:WindowRole,edge:'low'|'high')=>{if(e.button!==0||!p.windows)return;e.stopPropagation();
  svg.current!.setPointerCapture(e.pointerId);setDrag({role,edge,value:p.windows.channel[role].phs[edge],bounds:range??bounds});setBox(null);};
 const edgeValue=(role:WindowRole,edge:'low'|'high')=>drag?.role===role&&drag.edge===edge?drag.value:p.windows!.channel[role].phs[edge];

 const exportData={numericTable:p.density&&p.grid?(k:'csv'|'txt')=>densityTable(p.grid!,k):undefined,title:p.title,xLabel:p.xLabel,yLabel:p.yLabel,series:traces};
 const expandButton=useRef<HTMLButtonElement>(null);
 useEffect(()=>{
  if(!full||!analysisPlot)return;
  const release=lockBackground(document.getElementById('root'));
  expandButton.current?.focus();
  return ()=>{release();expandButton.current?.focus();};
 },[full,analysisPlot]);
 const chart=<section className={'lifetime-plot'+(full?' lifetime-expanded':'')+(full&&p.expandedLegend?' m3-expanded-spectrum':'')+(p.disabled?' m3-inactive-plot':'' )} aria-disabled={p.disabled||undefined} aria-label={p.title}>
  <div className="lifetime-plot-head"><span>{p.title}<Help text={p.help}/></span><div>
   {p.tools}
   {!p.locked&&<button title={timeViewport?'Reset to configured time range':'Fit all data'} onClick={fitAll}><Maximize size={13}/></button>}
   <button ref={expandButton} title={full?'Close expanded plot':'Expand plot'} onClick={()=>setFull(!full)}>{full?<X size={14}/>:<Expand size={13}/>}</button>
   <details><summary title="Export plot or data"><Download size={13}/></summary><div className="lifetime-export">{(['svg','png','csv','txt'] as const).map(k=><button key={k} onClick={()=>{if(svg.current)void exportPlot(svg.current,exportData,k);}}>{k.toUpperCase()}</button>)}</div></details>
  </div></div>
  <div className="lifetime-canvas" ref={canvas}><svg ref={svg} viewBox={`0 0 ${W} ${H}`} className={p.onCenter?'m3-placing':undefined} onDoubleClick={p.locked?undefined:fitAll}
   onWheel={e=>{if(p.locked||(!full&&!e.ctrlKey))return;const [x]=coord(pos(e)),f=e.deltaY>0?1.25:.8;zoom([x+(x0-x)*f,x+(x1-x)*f,y0,y1],!!localRange);}}
   onPointerDown={e=>{if(e.button!==0||p.locked&&!p.onCenter)return;svg.current!.setPointerCapture(e.pointerId);setBox([pos(e),pos(e)]);}}
   onPointerMove={e=>{const at=pos(e),xy=coord(at);setHover(xy);if(drag&&p.windows)setDrag({...drag,value:moveEdge(p.windows.channel,drag.role,drag.edge,xy[0])});else if(box)setBox([box[0],at]);}}
   onPointerCancel={cancel} onPointerLeave={()=>setHover(null)} onPointerUp={e=>{if(drag&&p.windows){
    p.windows.onEdge?.(drag.role,drag.edge,moveEdge(p.windows.channel,drag.role,drag.edge,coord(pos(e))[0]));
   }else if(box){const [a,b]=box;if(!p.locked&&Math.abs(b[0]-a[0])>5&&Math.abs(b[1]-a[1])>5){const lo=coord(a),hi=coord(b);zoom([Math.min(lo[0],hi[0]),Math.max(lo[0],hi[0]),Math.min(lo[1],hi[1]),Math.max(lo[1],hi[1])]);}
    else if(p.onCenter){const [x,y]=coord(pos(e));p.onCenter(x,y);}}cancel();}}>
   <defs><clipPath id={clip}><rect x={L} y={T} width={w} height={h}/></clipPath></defs>
   <text x={L} y="12">{p.yLabel}{p.log?' · log scale':''}</text>
   {yTicks.map(y=><g key={y}><line x1={L} x2={W-R} y1={sy(y)} y2={sy(y)} stroke="#e1e9f0"/><text x={L-7} y={sy(y)+3} textAnchor="end">{short(y)}</text></g>)}
   {axisFractions.map(f=>{const x=x0+f*(x1-x0);return <text key={f} x={sx(x)} y={H-B+15} textAnchor="middle">{short(x)}</text>;})}
   <g clipPath={`url(#${clip})`}>
   {p.log&&x0<0&&x1>0&&<line x1={sx(0)} x2={sx(0)} y1={T} y2={T+h} stroke="#9cabb7" strokeDasharray="3 4"><title>Display time zero</title></line>}
   {p.windows&&(['start','stop'] as const).map(role=><rect key={role} x={sx(edgeValue(role,'low'))} y={T} width={Math.max(0,sx(edgeValue(role,'high'))-sx(edgeValue(role,'low')))} height={h} fill={colors[role]} opacity=".085"/>)}
   {p.density?(heat&&<image href={heat} x={sx(axes[0])} y={sy(axes[3])} width={sx(axes[1])-sx(axes[0])} height={sy(axes[2])-sy(axes[3])} preserveAspectRatio="none" style={{imageRendering:'pixelated'}}/>):
    <TraceLayer traces={traces} paths={paths} circles={p.circles} histogram={p.histogram}/>}
   {p.kind&&p.gate&&p.onGate&&<LifetimeGateOverlay kind={p.kind} gate={p.gate} role={p.role??'start'} axes={[x0,x1,y0,y1]} sx={sx} sy={sy}
    position={e=>coord(pos(e))} change={p.onGate} freeze={freezeGate} placing={!!p.onCenter}/>}
   {box&&<rect x={Math.min(box[0][0],box[1][0])} y={Math.min(box[0][1],box[1][1])} width={Math.abs(box[1][0]-box[0][0])} height={Math.abs(box[1][1]-box[0][1])} fill="#159c9d" fillOpacity=".12" stroke="#159c9d"/>}</g>
   {p.windows&&(['start','stop'] as const).map((role,i)=>{
    const {start,stop}=p.windows!.channel;
    const nearby=Math.abs(sx((start.phs.low+start.phs.high)/2)-sx((stop.phs.low+stop.phs.high)/2))<55;
    const y=p.windows!.onEdge?23+i*20:nearby?16+i*16:23,lo=sx(edgeValue(role,'low')),hi=sx(edgeValue(role,'high'));
    const left=Math.max(L,lo),right=Math.min(W-R,hi),color=colors[role];
    if(right<left)return null;
    const badge=role==='start'?34:32;
    const labelX=right-left>=badge+14?(left+right)/2:right+badge+8<=W-R?right+badge/2+7:Math.max(L+badge/2,left-badge/2-7);
    return <g key={role} className="m3-phs-window" data-window={role}>
     <rect x={left} y={y-3} width={right-left} height="6" rx="3" fill={color} opacity=".22"/>
     <line x1={left} x2={right} y1={y} y2={y} stroke={color} strokeWidth="1.4"/>
     <g pointerEvents="none"><rect x={labelX-badge/2} y={y-8} width={badge} height="16" rx="8" fill={role==='start'?'#e4f2ef':'#f0eaf7'}/>
      <text x={labelX} y={y+3.3} textAnchor="middle" style={{fill:role==='start'?'#126e6c':'#6a448c',fontWeight:600}}>{labels[role]}</text></g>
     {(['low','high'] as const).map(edge=>{
      const v=edgeValue(role,edge),x=sx(v);if(x<L-1||x>W-R+1)return null;
      if(!p.windows?.onEdge)return <line key={edge} x1={x} x2={x} y1={y+5} y2={T+h} stroke={color} strokeDasharray="3 4" opacity=".55"/>;
      return <g key={edge} className="lifetime-edge" role="slider" tabIndex={0} aria-label={p.title+' '+labels[role]+' '+edge} aria-valuenow={v} aria-valuetext={v+' mV'}
       aria-valuemin={moveEdge(p.windows!.channel,role,edge,0)} aria-valuemax={Math.max(v,moveEdge(p.windows!.channel,role,edge,x1))}
       onPointerDown={e=>beginEdge(e,role,edge)} onKeyDown={e=>{if(e.key!=='ArrowLeft'&&e.key!=='ArrowRight')return;e.preventDefault();const delta=(e.key==='ArrowLeft'?-1:1)*(e.shiftKey?10:1);p.windows!.onEdge?.(role,edge,moveEdge(p.windows!.channel,role,edge,v+delta));}}>
       <title>{labels[role]} {edge} · {short(v)} mV · drag or use arrow keys</title>
       <line x1={x} x2={x} y1={y+7} y2={T+h} stroke={color} strokeDasharray="3 4" opacity=".56" pointerEvents="none"/>
       <line x1={x} x2={x} y1={T} y2={T+h} stroke="transparent" strokeWidth="8" pointerEvents="stroke"/>
       <rect className="m3-edge-hit" x={x-7} y={y-10} width="14" height="20" fill="transparent"/>
       <rect className="m3-edge-cap" x={x-3.6} y={y-6.5} width="7.2" height="13" rx="2.5" stroke={color} strokeWidth="1.5" fill="white"/>
       <line x1={x} x2={x} y1={y-3} y2={y+3} stroke={color} strokeLinecap="round"/>
      </g>;
     })}</g>;
   })}
   <text x={L+w/2} y={H-6} textAnchor="middle">{p.xLabel}</text>
   {hover&&<text x={W-R} y={12} textAnchor="end">{drag?labels[drag.role]+' '+drag.edge+' · '+short(drag.value)+' mV':'x '+short(hover[0])+' · y '+short(hover[1])}</text>}
   {!p.busy&&!p.grid?.visible&&!traces.some(t=>t.points.length)&&<text className="m3-plot-empty" x={L+w/2} y={T+h/2} textAnchor="middle">{p.empty??'No measured pulses'}</text>}
  </svg></div>{p.footer&&<div className="lifetime-plot-foot">{p.footer}<span className="m3-plot-progress">{!p.disabled&&<ProcessingActivity activity={activity}/>}</span></div>}
  {full&&p.expandedLegend}
 </section>;
 return full&&p.expandedLegend?<><div aria-hidden="true" className="m3-expanded-slot"/>{createPortal(<div className="m3-spectrum-backdrop" role="dialog" aria-modal="true" aria-label={p.title+' · expanded'} onMouseDown={e=>{if(e.target===e.currentTarget)setFull(false);}}>{chart}</div>,document.body)}</>:chart;
}

