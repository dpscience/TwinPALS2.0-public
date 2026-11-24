// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {PlotData} from './Plot';
import type {CathodeData} from './CathodeMap';
import type {PersistenceData} from './PersistencePlot';

export type DensityLayer={label:string;x:[number,number];y:[number,number];counts:number[][];count:number;log:boolean;outline?:'circle'|'rect'};
export type ReportPlot=PlotData&{density?:DensityLayer[]};
export function cathodeLayer(d:CathodeData,label:string):DensityLayer{return {label,x:[-d.geometry.width_mm/2,d.geometry.width_mm/2],y:[-d.geometry.height_mm/2,d.geometry.height_mm/2],counts:d.counts,count:d.count,log:false,outline:d.geometry.shape};}
export function persistenceLayer(d:PersistenceData,label:string):DensityLayer{return {label,x:d.x_range,y:d.y_range,counts:d.counts,count:d.count,log:true};}

// Embedded into the offline report. No imports or application services at runtime.
export function reportDensity(card:HTMLElement,plot:ReportPlot){
 const layers=plot.density!,NS='http://www.w3.org/2000/svg';
 if(!layers.length){const note=document.createElement('p');note.textContent='No distribution recorded.';card.append(note);return;}
 let layer=layers[0],range=[...layer.x,...layer.y];
 const controls=document.createElement('div');controls.className='plot-actions';
 const select=document.createElement('select');select.className='layer-selector';select.title='Detector and primary stream';select.setAttribute('aria-label',plot.title+' selection');
 layers.forEach((v,i)=>{const option=document.createElement('option');option.value=String(i);option.textContent=v.label;select.append(option);});card.append(select);
 const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 800 350');svg.setAttribute('aria-label',plot.title);svg.setAttribute('font-family','system-ui, sans-serif');card.append(svg);
 const caption=document.createElement('p');card.append(caption,controls);
 const node=(tag:string,attrs:Record<string,string|number>,text?:string)=>{const e=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>e.setAttribute(k,String(v)));if(text)e.textContent=text;svg.append(e);return e;};
 let raster='',maximum=0;
 const prepare=()=>{maximum=Math.max(0,...layer.counts.map(r=>Math.max(...r)));const canvas=document.createElement('canvas'),n=layer.counts.length;canvas.width=n;canvas.height=n;const ctx=canvas.getContext('2d')!,pixels=ctx.createImageData(n,n);for(let y=0;y<n;y++)for(let x=0;x<n;x++){const v=layer.counts[y][x],f=maximum?(layer.log?Math.log1p(v)/Math.log1p(maximum):v/maximum):0;pixels.data.set([Math.round(247-220*f),Math.round(250-115*f),Math.round(252-105*f),255],((n-1-y)*n+x)*4);}ctx.putImageData(pixels,0,0);raster=canvas.toDataURL();};
 const xp=(x:number)=>75+580*(x-range[0])/(range[1]-range[0]),yp=(y:number)=>285-260*(y-range[2])/(range[3]-range[2]);
 const render=()=>{svg.replaceChildren();node('rect',{width:800,height:350,fill:'white'});
  const clipId='density-'+Math.random().toString(36).slice(2);const defs=node('defs',{}),clip=document.createElementNS(NS,'clipPath');clip.id=clipId;const rect=document.createElementNS(NS,'rect');Object.entries({x:75,y:25,width:580,height:260}).forEach(([k,v])=>rect.setAttribute(k,String(v)));clip.append(rect);defs.append(clip);
  node('image',{href:raster,x:xp(layer.x[0]),y:yp(layer.y[1]),width:xp(layer.x[1])-xp(layer.x[0]),height:yp(layer.y[0])-yp(layer.y[1]),preserveAspectRatio:'none','clip-path':`url(#${clipId})`,style:'image-rendering:pixelated'});
  if(layer.outline)node(layer.outline==='circle'?'ellipse':'rect',layer.outline==='circle'?{cx:xp(0),cy:yp(0),rx:(xp(layer.x[1])-xp(layer.x[0]))/2,ry:(yp(layer.y[0])-yp(layer.y[1]))/2,fill:'none',stroke:'#628196','clip-path':`url(#${clipId})`}:{x:xp(layer.x[0]),y:yp(layer.y[1]),width:xp(layer.x[1])-xp(layer.x[0]),height:yp(layer.y[0])-yp(layer.y[1]),fill:'none',stroke:'#628196','clip-path':`url(#${clipId})`});
  for(let i=0;i<=4;i++){const f=i/4;node('text',{x:75+580*f,y:305,'text-anchor':'middle','font-size':11,fill:'#64748b'},Number((range[0]+f*(range[1]-range[0])).toPrecision(4)).toLocaleString());node('text',{x:66,y:289-260*f,'text-anchor':'end','font-size':11,fill:'#64748b'},Number((range[2]+f*(range[3]-range[2])).toPrecision(4)).toLocaleString());}
  node('text',{x:365,y:330,'text-anchor':'middle','font-size':12,fill:'#41546b'},plot.xLabel);node('text',{x:75,y:15,'font-size':11,fill:'#41546b'},plot.yLabel);
  for(let i=0;i<100;i++){const f=i/99;node('rect',{x:680,y:25+(1-f)*258,width:15,height:3,fill:`rgb(${Math.round(247-220*f)},${Math.round(250-115*f)},${Math.round(252-105*f)})`});}node('text',{x:701,y:35,'font-size':11},String(maximum));node('text',{x:701,y:285,'font-size':11},'0');
  caption.textContent=`${layer.label} · ${layer.count.toLocaleString()} ${layer.outline?'accepted photons':'pulses'} · ${layer.counts.length} × ${layer.counts.length} bins. ${layer.log?'Logarithmic':'Linear'} colour scale. ${plot.note??''}`;
 };
 const save=(blob:Blob,name:string)=>{const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);};
 const button=(label:string,fn:()=>void)=>{const b=document.createElement('button');b.textContent=label;b.title=label==='Fit all data'?'Reset zoom':`Export ${label}`;b.onclick=fn;controls.append(b);};
 const fit=()=>{range=[...layer.x,...layer.y];render();};select.onchange=()=>{layer=layers[Number(select.value)];prepare();fit();};button('Fit all data',fit);
 for(const kind of ['CSV','TXT','SVG','PNG'])button(kind,()=>{const name=(plot.title+'-'+layer.label).replace(/[^a-z0-9]+/gi,'-').toLowerCase();if(kind==='CSV'||kind==='TXT'){const sep=kind==='CSV'?',':'\t',n=layer.counts.length,dx=(layer.x[1]-layer.x[0])/n,dy=(layer.y[1]-layer.y[0])/n;const rows=[`# ${plot.title}; ${layer.label}; X: ${plot.xLabel}; Y: ${plot.yLabel}`,['x_low','x_high','y_low','y_high','count'].join(sep),...layer.counts.flatMap((row,y)=>row.map((v,x)=>[layer.x[0]+dx*x,layer.x[0]+dx*(x+1),layer.y[0]+dy*y,layer.y[0]+dy*(y+1),v].join(sep)))];save(new Blob([rows.join('\n')],{type:'text/plain'}),name+'.'+kind.toLowerCase());return;}
  const clone=svg.cloneNode(true) as SVGSVGElement;clone.querySelectorAll('.hover,.rubber-band').forEach(n=>n.remove());clone.setAttribute('xmlns',NS);clone.setAttribute('width','1600');clone.setAttribute('height','700');const blob=new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml'});if(kind==='SVG'){save(blob,name+'.svg');return;}const url=URL.createObjectURL(blob),image=new Image();image.onload=()=>{const c=document.createElement('canvas');c.width=1600;c.height=700;c.getContext('2d')!.drawImage(image,0,0);c.toBlob(b=>{if(b)save(b,name+'.png');});URL.revokeObjectURL(url);};image.src=url;
 });
 const point=(e:PointerEvent|WheelEvent)=>{const r=svg.getBoundingClientRect();return {x:Math.max(75,Math.min(655,(e.clientX-r.left)/r.width*800)),y:Math.max(25,Math.min(285,(e.clientY-r.top)/r.height*350))};};
 const value=(p:{x:number;y:number})=>[range[0]+(p.x-75)/580*(range[1]-range[0]),range[2]+(285-p.y)/260*(range[3]-range[2])];let drag:{x:number;y:number}|null=null;
 svg.onpointerdown=e=>{if(e.button===0){drag=point(e);svg.setPointerCapture(e.pointerId);}};
 svg.onpointermove=e=>{svg.querySelectorAll('.hover,.rubber-band').forEach(v=>v.remove());const p=point(e);if(drag){node('rect',{class:'rubber-band',x:Math.min(p.x,drag.x),y:Math.min(p.y,drag.y),width:Math.abs(p.x-drag.x),height:Math.abs(p.y-drag.y),fill:'#269b9b26',stroke:'#198f8c'});return;}const [x,y]=value(p),n=layer.counts.length,ix=Math.floor((x-layer.x[0])/(layer.x[1]-layer.x[0])*n),iy=Math.floor((y-layer.y[0])/(layer.y[1]-layer.y[0])*n);if(ix>=0&&ix<n&&iy>=0&&iy<n){node('path',{class:'hover',d:`M${p.x} 25 V285 M75 ${p.y} H655`,stroke:'#92a9bd','stroke-dasharray':'3 3','pointer-events':'none'});node('text',{class:'hover',x:400,y:15,'font-size':11,fill:'#41546b'},`x ${x.toPrecision(4)} · y ${y.toPrecision(4)} · ${layer.counts[iy][ix]} counts`);}};
 svg.onpointerup=e=>{const p=point(e);if(drag&&Math.abs(p.x-drag.x)>4&&Math.abs(p.y-drag.y)>4){const a=value(drag),b=value(p);range=[Math.min(a[0],b[0]),Math.max(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[1],b[1])];}drag=null;if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);render();};svg.onpointercancel=()=>{drag=null;render();};svg.onpointerleave=()=>svg.querySelectorAll('.hover').forEach(n=>n.remove());svg.ondblclick=e=>{e.preventDefault();drag=null;fit();};svg.addEventListener('wheel',e=>{e.preventDefault();const v=value(point(e)),f=e.deltaY>0?1.2:.8;range=[v[0]+(range[0]-v[0])*f,v[0]+(range[1]-v[0])*f,v[1]+(range[2]-v[1])*f,v[1]+(range[3]-v[1])*f];render();},{passive:false});prepare();render();
}
