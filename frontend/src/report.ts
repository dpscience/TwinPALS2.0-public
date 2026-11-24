// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {reportOutcomes} from './reportOutcomes';
import {intervalAnnotation,channelColors} from './plotStyle';
import {plotRanges,plotPanels} from './plotRange';
import {reportDensity} from './reportDensity';
import type {ReportPlot} from './reportDensity';
import { downloadBlob } from './Plot';
import {reportIcon,reportCitation,reportHeader,reportMetrics,reportStyle} from './reportLayout';

type ReportFigure={title:string;alt:string;src:string};

// This function is embedded verbatim. Keep it dependency-free so reports work offline.
function reportClient(compute:typeof plotRanges,panelLayout:typeof plotPanels,densityRender:typeof reportDensity,omission:typeof intervalAnnotation,channelPalette:readonly string[],renderOutcomes:typeof reportOutcomes){
 const data=JSON.parse(document.getElementById('report-data')!.textContent!) as {figure?:ReportFigure;profile:unknown;plots:ReportPlot[];metadata:Record<string,unknown>};
 const save=(text:string,name:string,type='text/plain')=>{const url=URL.createObjectURL(new Blob([text],{type})),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
 const byId=(id:string)=>document.getElementById(id)!;
 const isAcquisition=data.metadata.module===2;
 byId('settings').onclick=()=>save(JSON.stringify(data.profile,null,2),isAcquisition?'report.tpm2':'report.tpm1','application/json');
 byId('snapshot').onclick=()=>save(JSON.stringify({profile:data.profile,metadata:data.metadata,plots:data.plots}),isAcquisition?'digitizer-acquisition.json':'detector-response.json','application/json');
 const roles:Record<string,string>={na22_prompt:'Na-22 · 1275 keV',na22_annihilation:'Na-22 · 511 keV pairs',co60_1173:'Co-60 · 1173 keV',co60_1332:'Co-60 · 1332 keV',waveforms:'Pulse stream'};
 const colors:Record<string,string>={na22_prompt:'#198f8c',na22_annihilation:'#9870ca',co60_1173:'#227bb0',co60_1332:'#c58a32'};
 const streams=(data.metadata.streams??[]) as {path:string;header:Record<string,unknown>;completion:{events?:number;status?:string}}[];
 const fileName=(s:typeof streams[number])=>s.path.split(/[\\/]/).at(-1)??s.path;
 const streamCount=(s:typeof streams[number])=>Number(s.completion?.events??s.header.events??0);
 const stamp=(value:unknown)=>value?new Date(String(value)).toLocaleString():'—';
 byId('stream-name').textContent=[...streams.map(fileName),stamp(data.metadata.created_at)].join(' · ');
 const selection=data.metadata.selection as {bins?:number;basis?:'crystal'|'anode';origin?:string}|undefined;
 const total=data.metadata.total_events??streams.reduce((sum,s)=>sum+streamCount(s),0);
 byId('read').textContent=Number(total).toLocaleString();
 byId('instrument').textContent=isAcquisition?(data.metadata.sampling_rate!=null?Number(data.metadata.sampling_rate).toLocaleString()+' GS/s':'—'):String(streams.length);
 byId('bins').textContent=selection?.bins?.toLocaleString()??'—';
 byId('status').textContent=data.metadata.complete?'Complete':'Partial';
 for(const s of streams){
  const row=document.createElement('tr'),role=String(s.header.role),time=s.header.created_at??s.header.created_utc;
  for(const value of [fileName(s),roles[role]??role,streamCount(s).toLocaleString(),stamp(time)])row.insertCell().textContent=value;
  row.title=s.path;byId('streams').append(row);
 }
 const originLabels:Record<string,string>={all:'All pulse origins',none:'No pulse',scintillation:'Scintillation',cherenkov:'Cherenkov',mixed:'Mixed'};
 const physics=(data.profile as {physics?:{include_cherenkov:boolean;minimum_energy_keV:number}})?.physics??data.metadata.input_physics as {include_cherenkov:boolean;minimum_energy_keV:number}|undefined;
 if(physics)byId('physics').textContent=`Cherenkov ${physics.include_cherenkov?'on':'off'} · Minimum crystal energy ${physics.minimum_energy_keV} keV`+(isAcquisition?'':` · ${originLabels[selection?.origin??'all']}. Pulse origins use QE-accepted photoelectrons.`);
 for(const stream of streams){const outcomes=(stream as unknown as {outcomes?:Parameters<typeof reportOutcomes>[1]}).outcomes;if(outcomes){byId('outcomes-section').hidden=false;renderOutcomes(byId('origin-summary'),outcomes,roles[String(stream.header.role)]??String(stream.header.role),colors[String(stream.header.role)]??'#267c82');}}

 if(data.figure){
  const figure=document.createElement('figure'),heading=document.createElement('h2'),image=document.createElement('img');
  heading.textContent=data.figure.title;image.alt=data.figure.alt;image.src=data.figure.src;
  figure.className='plot-card setup-figure';figure.append(image);byId('setup-view').append(heading,figure);
 }
 const NS='http://www.w3.org/2000/svg';
 data.plots.forEach((plot,index)=>{
  const card=document.createElement('section');card.className='plot-card';const heading=document.createElement('div');heading.className='report-plot-heading';const title=document.createElement('h3');title.textContent=plot.title;heading.append(title);card.append(heading);
  if(plot.title.startsWith('Crystal · '))card.dataset.basis='crystal';
  if(plot.title.startsWith('Anode · '))card.dataset.basis='anode';
  if(plot.explanation){
   const help=document.createElement('details');help.className='report-plot-help';const summary=document.createElement('summary');summary.textContent='ⓘ';summary.setAttribute('aria-label',`About ${plot.title}`);summary.title='Quantity and selection explained';help.append(summary);
   const body=document.createElement('div');body.className='report-help-body';
   for(const section of plot.explanation.text.split('\n\n')){const lines=section.split('\n'),p=document.createElement('p');p.textContent=lines.filter(l=>!l.startsWith('- ')).join(' ');body.append(p);const bullets=lines.filter(l=>l.startsWith('- '));if(bullets.length){const ul=document.createElement('ul');for(const line of bullets){const li=document.createElement('li');li.textContent=line.slice(2);ul.append(li);}body.append(ul);}}
   help.append(body);heading.append(help);
  }
  if(plot.density){document.getElementById('density-section')!.hidden=false;document.getElementById('density-plots')!.append(card);densityRender(card,plot);return;}
  const tools=document.createElement('div');tools.className='plot-actions';const svg=document.createElementNS(NS,'svg');svg.setAttribute('viewBox','0 0 800 300');svg.setAttribute('font-family','system-ui, sans-serif');card.append(svg);
  const legend=document.createElement('div');legend.className='legend';card.append(legend);if(plot.note){const note=document.createElement('p');note.textContent=plot.note;card.append(note);}card.append(tools);byId('plots').append(card);
  const xs=[...plot.series.flatMap(s=>s.points.map(p=>p[0])),...(plot.extent??[]),...(plot.markers??[]).map(m=>m.x),...(plot.bands??[]).flatMap(b=>[b.low,b.high])];let extent:[number,number]=xs.length?[Math.min(...xs),Math.max(...xs)]:[0,1];if(extent[0]===extent[1])extent=[extent[0],extent[0]+1];extent=plot.focusX??extent;const right=plot.omittedTail?650:782,pw=right-65;let range=[...extent],hidden:string[]=[],yrange:number[]|null=null,axisY=[0,1],drag:{x:number;y:number}|null=null;
  const el=(tag:string,attributes:Record<string,string|number>,text?:string)=>{const n=document.createElementNS(NS,tag);Object.entries(attributes).forEach(([k,v])=>n.setAttribute(k,String(v)));if(text)n.textContent=text;svg.append(n);return n;};
  const lockedY=!!(plot.fixedY||plot.panelY?.length);
  const render=()=>{svg.replaceChildren();el('rect',{width:800,height:300,fill:'white'});const active=plot.series.filter(s=>!hidden.includes(s.legendGroup??s.name));axisY=plot.fixedY??compute(active,plot.markers??[],{x:range as [number,number],y:yrange as [number,number]|null}).y;
   const rows=panelLayout(plot.panels,plot.panelY,axisY as [number,number],22,234,plot.panelGap);
   const xp=(x:number)=>65+(x-range[0])/(range[1]-range[0])*pw,yp=(y:number,panel=0)=>{const row=rows[panel]??rows[0];return row.top+row.height-(y-row.range[0])/(row.range[1]-row.range[0])*row.height;};
   (plot.bands??[]).filter(b=>b.high>range[0]&&b.low<range[1]).forEach(b=>rows.forEach(row=>el('rect',{x:xp(Math.max(range[0],b.low)),y:row.top,width:xp(Math.min(range[1],b.high))-xp(Math.max(range[0],b.low)),height:row.height,fill:b.color,'fill-opacity':.12})));
   rows.forEach((row,panel)=>{const ticks=plot.panelY?row.ticks:[0,.25,.5,.75,1].map(f=>row.range[0]+(row.range[1]-row.range[0])*f);for(const v of ticks){el('line',{x1:65,x2:right,y1:yp(v,panel),y2:yp(v,panel),stroke:'#e4e9ef'});el('text',{x:56,y:plot.panels?Math.max(row.top+10,Math.min(row.top+row.height-3,yp(v,panel)+4)):yp(v,panel)+4,'text-anchor':'end',fill:'#64748b','font-size':11},Number(v.toPrecision(4)).toLocaleString());}if(row.label)el('text',{x:70,y:row.top+13,fill:channelPalette[panel%channelPalette.length],'font-size':11,'font-weight':600},row.label);});
   for(let i=0;i<=5;i++)el('text',{x:65+i/5*pw,y:275,'text-anchor':'middle',fill:'#64748b','font-size':11},plot.preciseX?(range[0]+i/5*(range[1]-range[0])).toLocaleString('en-GB',{maximumFractionDigits:Math.max(0,Math.min(9,2-Math.floor(Math.log10(range[1]-range[0]))))}):Number((range[0]+i/5*(range[1]-range[0])).toPrecision(4)).toLocaleString());
   el('text',{x:65,y:13,fill:'#64748b','font-size':11},plot.yLabel);el('text',{x:65+pw/2,y:296,'text-anchor':'middle',fill:'#64748b','font-size':12},plot.xLabel);
   const defs=el('defs',{}),clip=document.createElementNS(NS,'clipPath');clip.id=`plot-${index}`;rows.forEach((row,i)=>{const rect=document.createElementNS(NS,'rect');Object.entries({x:65,y:row.top,width:pw,height:row.height}).forEach(([k,v])=>rect.setAttribute(k,String(v)));clip.append(rect);const c=document.createElementNS(NS,'clipPath');c.id=`plot-${index}-p${i}`;c.append(rect.cloneNode(true));defs.append(c);});defs.append(clip);
   (plot.levels??[]).filter(v=>v.y>=rows[v.panel??0].range[0]&&v.y<=rows[v.panel??0].range[1]).forEach(v=>{el('line',{x1:65,x2:right,y1:yp(v.y,v.panel??0),y2:yp(v.y,v.panel??0),stroke:v.color,'stroke-dasharray':'3 4'});el('text',{x:right-4,y:Math.max(rows[v.panel??0].top+26,Math.min(rows[v.panel??0].top+rows[v.panel??0].height-5,yp(v.y,v.panel??0)-4)),'text-anchor':'end',fill:v.color,'font-size':10},v.label);});
   active.forEach(s=>el('path',{d:s.points.map(([x,y],i)=>`${i&&(!s.stems||i%3)?'L':'M'}${xp(x)} ${yp(y,s.panel??0)}`).join(' '),fill:'none',stroke:s.color,'stroke-width':1.8,'stroke-dasharray':s.dashed?'5 3':'','clip-path':`url(#plot-${index}-p${s.panel??0})`}));
   (plot.markers??[]).filter(m=>m.x>=range[0]&&m.x<=range[1]).forEach((m,i)=>{rows.filter((_,i)=>m.panel===undefined||i===m.panel).forEach(row=>el('line',{x1:xp(m.x),x2:xp(m.x),y1:row.top,y2:row.top+row.height,stroke:'#94a3b8','stroke-dasharray':'4 4'}));if(!plot.markerLabelsOutside)el('text',{x:xp(m.x)+(xp(m.x)>65+pw*.7?-4:4),'text-anchor':xp(m.x)>65+pw*.7?'end':'start',y:rows[m.panel??0].top+13+(m.labelRow??i%2)*14,fill:m.color??'#64748b','font-size':10},m.label);if(m.span&&rows[m.panel??0].height>=64&&xp(m.span.end)-xp(m.x)>100){const y=rows[m.panel??0].top+rows[m.panel??0].height-20;el('path',{d:`M${xp(m.x)} ${y+4} v-8 m0 4 H${xp(m.span.end)} m0 -4 v8`,stroke:'#64748b',fill:'none','clip-path':`url(#plot-${index}-p${m.panel??0})`});el('text',{x:(xp(m.x)+xp(m.span.end))/2,y:y-7,'text-anchor':'middle',fill:'#64748b','font-size':10,'clip-path':`url(#plot-${index}-p${m.panel??0})`},m.span.label);}});
   if(plot.omittedTail)omission(plot.omittedTail,right+18,22,114,234).forEach(n=>el(n.tag,n.attrs,n.text));
  };
  const button=(label:string,fn:()=>void)=>{const b=document.createElement('button');b.textContent=label;b.onclick=fn;tools.append(b);};
  button('Fit all data',()=>{range=[...extent];yrange=null;render();});
  ['CSV','TXT','SVG','PNG'].forEach(kind=>button(kind,()=>{const name=plot.title.replace(/[^a-z0-9]+/gi,'-').toLowerCase();if(kind==='CSV'||kind==='TXT'){const sep=kind==='CSV'?',':'\t';save([`# ${plot.note??''}`,(plot.series.every(s=>s.bins)?['series','bin_low','bin_high','count']:['series',plot.xLabel,plot.yLabel]).join(sep),...plot.series.flatMap(s=>s.bins?s.bins.map(p=>[JSON.stringify(s.name),p.low,p.high,p.count].join(sep)):s.points.map(p=>[JSON.stringify(s.name),...p].join(sep)))].join('\n'),`${name}.${kind.toLowerCase()}`);return;}const clone=svg.cloneNode(true) as SVGSVGElement;clone.setAttribute('xmlns',NS);clone.setAttribute('width','1600');clone.setAttribute('height','600');const text=new XMLSerializer().serializeToString(clone);if(kind==='SVG'){save(text,`${name}.svg`,'image/svg+xml');return;}const url=URL.createObjectURL(new Blob([text],{type:'image/svg+xml'})),image=new Image();image.onload=()=>{const canvas=document.createElement('canvas');canvas.width=1600;canvas.height=600;const context=canvas.getContext('2d');if(context){context.drawImage(image,0,0);canvas.toBlob(blob=>{if(blob){const u=URL.createObjectURL(blob),a=document.createElement('a');a.href=u;a.download=`${name}.png`;a.click();setTimeout(()=>URL.revokeObjectURL(u),1000);}});}URL.revokeObjectURL(url);};image.src=url;}));
  if(plot.markerLabelsOutside)(plot.markers??[]).forEach(m=>{const item=document.createElement('span');item.textContent=`${m.label.replace('Accepted crossing','Crossing')}: ${m.x.toPrecision(7)} ${plot.xOrigin!==undefined?'µs':'ns'}`;item.style.color=m.color??'#607f94';legend.append(item);});
  (plot.bands??[]).forEach(b=>{const text=document.createElement('span');text.textContent=b.label;text.style.color=b.color;legend.append(text);});
  if(plot.series.some(s=>s.legendGroup)){const key=document.createElement('span');key.textContent='A: solid / B: dashed';legend.append(key);}
  plot.series.filter((s,i,all)=>all.findIndex(v=>(v.legendGroup??v.name)===(s.legendGroup??s.name))===i).forEach(s=>{const b=document.createElement('button');const key=s.legendGroup??s.name;b.textContent=key;const sample=document.createElementNS(NS,'svg');sample.setAttribute('width','25');sample.setAttribute('height','8');sample.setAttribute('viewBox','0 0 25 8');sample.classList.add('line-swatch');const line=document.createElementNS(NS,'line');Object.entries({x1:'0',x2:'25',y1:'4',y2:'4',stroke:s.color,'stroke-width':'1.8','stroke-dasharray':s.dashed?'5 3':''}).forEach(([k,v])=>line.setAttribute(k,v));sample.append(line);b.prepend(sample);b.onclick=()=>{hidden=hidden.includes(key)?hidden.filter(n=>n!==key):[...hidden,key];b.style.opacity=hidden.includes(key)?'.4':'1';render();};legend.append(b);});
  const at=(e:MouseEvent|WheelEvent)=>{const r=svg.getBoundingClientRect();return (e.clientX-r.left)/r.width*800;};
  svg.addEventListener('wheel',e=>{e.preventDefault();const x=(at(e)-65)/pw,c=range[0]+x*(range[1]-range[0]),span=(range[1]-range[0])*(e.deltaY>0?1.2:.8);range=[c-x*span,c+(1-x)*span];render();},{passive:false});
  const point=(e:PointerEvent)=>{const r=svg.getBoundingClientRect();return {x:Math.max(65,Math.min(right,at(e))),y:Math.max(22,Math.min(256,(e.clientY-r.top)/r.height*300))};};
  let moved=false;
  svg.onpointerdown=e=>{if(e.button!==0)return;drag=point(e);moved=false;svg.setPointerCapture(e.pointerId);};
  svg.onpointermove=e=>{if(!drag)return;const p=point(e);if(!moved&&Math.abs(p.x-drag.x)<=4&&Math.abs(p.y-drag.y)<=4)return;moved=true;render();el('rect',{class:'rubber-band',x:Math.min(p.x,drag.x),y:lockedY?22:Math.min(p.y,drag.y),width:Math.abs(p.x-drag.x),height:lockedY?234:Math.abs(p.y-drag.y),'clip-path':`url(#plot-${index})`,fill:'#269b9b26',stroke:'#198f8c','stroke-dasharray':'4 2','pointer-events':'none'});};
  svg.onpointerup=e=>{const p=point(e);if(drag&&Math.abs(p.x-drag.x)>4&&(lockedY||Math.abs(p.y-drag.y)>4)){const toX=(x:number)=>range[0]+(x-65)/pw*(range[1]-range[0]),toY=(y:number)=>axisY[0]+(256-y)/234*(axisY[1]-axisY[0]);yrange=lockedY?null:[toY(Math.max(p.y,drag.y)),toY(Math.min(p.y,drag.y))];range=[toX(Math.min(p.x,drag.x)),toX(Math.max(p.x,drag.x))];}drag=null;if(svg.hasPointerCapture(e.pointerId))svg.releasePointerCapture(e.pointerId);if(moved)render();};
  svg.onpointercancel=()=>{drag=null;if(moved)render();};
  svg.ondblclick=e=>{e.preventDefault();drag=null;range=[...extent];yrange=null;render();};render();
 });
 const basis=document.getElementById('response-basis') as HTMLSelectElement|null;
 if(basis){
  const cards=byId('plots').querySelectorAll<HTMLElement>('[data-basis]');
  basis.parentElement!.hidden=!cards.length;
  basis.value=selection?.basis??'both';
  const show=()=>cards.forEach(card=>{card.hidden=basis.value!=='both'&&card.dataset.basis!==basis.value;});
  basis.onchange=show;show();
 }
}

export function reportHTML(profile:unknown,plots:ReportPlot[],metadata:Record<string,unknown>,figure?:ReportFigure){
 const module=metadata.module===2?2:1;
 const encoded=JSON.stringify({profile,plots,metadata,figure}).replace(/</g,'\\u003c');
 const acquisition=module===2;
 const title=acquisition?'Digitizer acquisition':'Detector response';
 const fields:[string,string][]=[['read',acquisition?'Waveform pairs':'Events processed'],['instrument',acquisition?'Sampling rate':'Input streams'],['bins','Histogram bins'],['status','Data at export']];
 return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${reportIcon}<title>TwinPALS · ${title}</title><style>${reportStyle}</style></head><body>
 ${reportHeader(module)}${reportMetrics(fields)}
 <main><section id="setup-view"></section>
 <div class="section-head"><h2>${acquisition?'Pulse distributions':'Detector distributions'}</h2>${acquisition?'':'<label>Response <select id="response-basis"><option value="both">Crystal and anode</option><option value="crystal">Crystal</option><option value="anode">Anode</option></select></label>'}</div>
 <div id="plots" class="grid histograms"></div>
 <details id="density-section" class="report-section" hidden><summary>${acquisition?'Pulse persistence':'Cathode maps and pulse persistence'}</summary><div id="density-plots" class="grid"></div></details>
 <details id="outcomes-section" class="report-section" hidden><summary>Event outcomes</summary><div id="origin-summary"></div></details>
 <details class="report-section"><summary>Recorded streams</summary><p class="meta" id="physics"></p><table><thead><tr><th>File</th><th>Stream</th><th>${acquisition?'Pairs':'Events'}</th><th>Recorded</th></tr></thead><tbody id="streams"></tbody></table></details>${reportCitation}</main>
 <script type="application/json" id="report-data">${encoded}</script><script>(${reportClient.toString()})(${plotRanges.toString()},${plotPanels.toString()},${reportDensity.toString()},${intervalAnnotation.toString()},${JSON.stringify(channelColors)},${reportOutcomes.toString()});</script></body></html>`;

}



export function exportReport(profile:unknown,plots:ReportPlot[],metadata:Record<string,unknown>,figure?:ReportFigure){downloadBlob(new Blob([reportHTML(profile,plots,metadata,figure)],{type:'text/html;charset=utf-8'}),'TwinPALS.tpreport.html');}
