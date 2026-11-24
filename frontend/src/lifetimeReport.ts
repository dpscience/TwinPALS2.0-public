// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {heightDomain,superimposedBins,spectrumCirclePath,spectrumStepPath,spectrumDisplay,spectrumNames} from './spectrumAnalysis';
import type {SpectrumDirection,SpectrumComparison} from './m3types';
import {subtypeFor,subtypeKeys} from './spectrumSubtypes';
import {contributionExample,contributionName,traceColor,traceColors} from './ContributionGraphic';
import {transportGroups} from './RecordedSetup';
import {categoryHelp,gateReason,type SourceStream,type LifetimeData,type LifetimeViews} from './m3types';
import {chosenClasses,displaySettings,directionNames} from './lifetimeEditing';
import {measurementTime} from './measurementTime';
import {reportIcon,reportCitation,reportHeader,reportMetrics,reportStyle} from './reportLayout';
import {downloadBlob} from './Plot';

export function saveLifetimeReport(data:LifetimeData,view:LifetimeViews,headers:{streams:SourceStream[]}){
 const profile=data.profile;
 const streams=headers.streams.map(stream=>({name:stream.name,source:stream.source,digitizer:stream.digitizer,
  acquisition:stream.acquisition,lifetimes:stream.lifetimes,groups:transportGroups(stream.inputs??[])}));
 const isotope=streams[0]?.source;
 const comparison=(data as LifetimeData & {comparison?:{comparisons:Record<string,SpectrumComparison>;all_paths?:Record<string,SpectrumComparison>}}).comparison;
 const observed=[...Object.values(comparison?.comparisons??{}),...Object.values(comparison?.all_paths??{})].flatMap(c=>Object.keys(c.stages[0].subclasses??{}));
 const subtypes=comparison?subtypeKeys(isotope,observed):[];
 const subtypeGroups=Object.fromEntries(subtypes.map(k=>[k,{parent:subtypeFor(k)?.parent,facet:subtypeFor(k)?.facet}]));
 const guideKeys=[...data.categories,...subtypes];
 const guide=Object.fromEntries((Object.keys(spectrumNames) as SpectrumDirection[]).map(direction=>[direction,
  Object.fromEntries(guideKeys.map(kind=>[kind,contributionExample(kind,direction,isotope).text]))]));
 const rejected=Object.fromEntries(Object.entries(data.rejected).map(([reason,n])=>[gateReason(reason),n]));
 const analysis={direction:view.analysis?.direction??'merged',displays:Object.fromEntries((Object.keys(spectrumNames) as SpectrumDirection[]).map(d=>[d,spectrumDisplay(view,d)]))};
 const {preview: _preview,...aggregate}=data;
 const payload=JSON.stringify({measurementTime:measurementTime(data.measurement_ns),streams,analysis,spectrumNames,guide,traceColors,subtypes,subtypeGroups,data:{...aggregate,rejected},profile,monitor:view.monitor,view:displaySettings(view),headers,categoryNames:Object.fromEntries(guideKeys.map(k=>[k,contributionName(k,isotope)])),categoryHelp,classColors:{...traceColors,...Object.fromEntries(subtypes.map(k=>[k,traceColor(k)]))},directionNames,selected:chosenClasses(view).filter(k=>data.categories.includes(k)),exported_at:new Date().toISOString()}).replace(/</g,'\\u003c');
 const html=`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${reportIcon}<title>TwinPALS · Lifetime analysis</title><style>${reportStyle}</style></head><body>
 ${reportHeader(3)}
 ${reportMetrics([['read','Pairs read'],['accepted','Accepted pairs'],['measurement','Measurement time'],['status','Acquisition at export']])}
 <main><div class="section-head"><h2>Spectrum comparison</h2><label id="direction-label">Direction <select id="direction"></select></label></div><p class="meta" id="summary"></p>
 <div class="comparison"><div id="spectra" class="grid"></div><aside><div class="rail-head"><h3>Contributions</h3><div><button id="all">All</button><button id="none">None</button></div></div>
 <label id="report-total"><input type="checkbox" id="total">Total spectrum</label><label id="report-superimposed" title="Sum of checked classes and subtypes. Each pair contributes once."><input type="checkbox" id="superimposed">Superimposed spectrum</label><label id="path-label" hidden>Class paths <select id="report-paths"><option value="display">Display selection</option><option value="all">All recorded paths</option></select></label>
 <label id="report-individual"><input type="checkbox" id="individual">Show individual contributions</label><div id="classes"></div><p class="meta" id="selection"></p></aside></div>
 <details class="report-section"><summary>Channel pulse-height spectra</summary><div id="heights" class="grid"></div></details>
 <details class="report-section" id="filter-section"><summary>Filter diagnostics</summary><div class="section-head"><p class="meta">CF-valid pulses since the channel’s last filter reset</p><label>Filter <select id="filter"><option value="area">Area</option><option value="shape">Rise / fall time</option></select></label></div><div id="diagnostics" class="grid"></div></details>
 <details class="report-section"><summary>Recorded setup and processing history</summary><div id="acquisition"></div></details>${reportCitation}</main>
 <script id="payload" type="application/json">${payload}</script><script>const sumBins=${superimposedBins.toString()};const circlePath=${spectrumCirclePath.toString()};const stepPath=${spectrumStepPath.toString()};const phsDomain=${heightDomain.toString()};`+offlineScript+'</script></body></html>';
 downloadBlob(new Blob([html],{type:'text/html'}),'TwinPALS-lifetime-report.html');
}

const offlineScript=String.raw`
const p=JSON.parse(document.getElementById('payload').textContent),D=p.data,sel=new Set(p.selected);
const $=id=>document.getElementById(id),el=(tag,txt)=>{const n=document.createElement(tag);if(txt!==undefined)n.textContent=txt;return n;};
const maps=(D.plots||[]).map(g=>g.cells_from===undefined?g:{...g,cells:D.plots[g.cells_from].cells});
const fmt=n=>n.toLocaleString(undefined,{maximumFractionDigits:4}),teal='#00868b',slate='#58778f',purple='#8462b0';
function download(name,body,type='text/plain'){const a=el('a'),url=URL.createObjectURL(body instanceof Blob?body:new Blob([body],{type}));a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
$('stream-name').textContent=[...p.streams.map(s=>s.name),new Date(p.exported_at).toLocaleString()].join(' · ');
$('read').textContent=fmt(D.total_processed);$('accepted').textContent=fmt(D.accepted);
$('measurement').textContent=p.measurementTime;$('status').textContent=D.status;
$('summary').textContent=fmt(p.view.bin_ps)+' ps bins · zero shift '+fmt(p.view.zero_ps)+' ps';
function selectedView(){const categories=[...sel].filter(k=>!p.subtypes.includes(k));return {...p.view,category:'all',categories,subtype_overlays:[...sel].filter(k=>p.subtypes.includes(k)),individual:$('individual').checked&&categories.length>0};}
$('settings').onclick=()=>download('analysis.tpm3',JSON.stringify({format:'twinpals-lifetime-settings',version:1,processing:p.profile,display:D.comparison?p.view:selectedView(),analysis:p.analysis,monitor:p.monitor},null,2),'application/json');
$('snapshot').onclick=()=>download('lifetime-analysis.json',JSON.stringify({...p,data:{...D,plots:maps},view:selectedView(),selected:[...sel]}),'application/json');
function table(parent,title,head,rows){
 if(!rows.length)return;
 const box=el('section'),t=el('table'),tr=el('tr');box.append(el('h3',title),t);parent.append(box);
 for(const field of head)tr.append(el('th',field));t.createTHead().append(tr);
 const body=t.createTBody();for(const values of rows){const row=body.insertRow();for(const value of values)row.insertCell().textContent=value??'—';}
}
const setup=$('acquisition');
for(const stream of p.streams){
 const detector=stream.digitizer,source=stream.source==='na22'?'Na-22':stream.source==='co60'?'Co-60':stream.source;
 table(setup,'Recording',['Property','Recorded value'],[['Stream',stream.name],['Source',source],['Digitizer',detector?.name],['Samples',detector?.samples],['Sampling rate',detector?.rate_GSps==null?null:fmt(detector.rate_GSps)+' GS/s']]);
 if(stream.source==='co60')setup.append(el('p','Co-60 prompt cascade · 1173 and 1332 keV'));
 table(setup,'Simulated lifetime components',['Component','Lifetime','Intensity','Distribution'],(stream.lifetimes??[]).map(c=>[c.name,fmt(c.tau_ns*1000)+' ps',fmt(100*c.intensity)+'%',c.distribution]));
 for(const group of stream.groups){const a=group.apparatus;if(!a)continue;
  table(setup,'Source and samples · '+group.roles.join(' / '),['Property','Recorded value'],Object.entries(a.source||{}));
  const A=a.detectors?.A||{},B=a.detectors?.B||{};
  table(setup,'Detector assembly · '+group.roles.join(' / '),['Property','Channel A','Channel B'],[...new Set([...Object.keys(A),...Object.keys(B)])].map(k=>[k,A[k],B[k]]));
 }
}
const channelRows=[
 ['Pulse selection',()=>p.profile.pulse_selection==='first'?'First pulse':'Highest pulse'],
 ['CF level',c=>fmt(c.cfd_percent)+'%'],
 ['Baseline',c=>fmt(c.baseline_samples)+' samples · '+(c.baseline_mode==='pre_pulse'?fmt(c.baseline_gap)+' samples before onset':'readout start')],
 ['Median filter',c=>c.median_samples>1?fmt(c.median_samples)+' samples':'Off'],
 ['Interpolation',c=>!c.interpolation||c.interpolation==='linear'?'Linear':c.interpolation+' · '+fmt(c.intra_steps)+' intra-steps'],
 ['Minimum height',c=>fmt(c.minimum_height_mV)+' mV'],
 ['Clipped pulses',c=>c.reject_clipped?'Reject':'Include']
];
table(setup,'Pulse measurements at export',['Parameter','Channel A','Channel B'],channelRows.map(([name,value])=>[name,...p.profile.channels.map(value)]));
table(setup,'Selection windows at export',['Window','Pulse height','Area filter','Rise / fall filter'],p.profile.channels.flatMap((c,i)=>['start','stop'].map(role=>{
 const g=c[role];return ['AB'[i]+' · '+role,fmt(g.phs.low)+'–'+fmt(g.phs.high)+' mV',g.area.enabled?'On':'Off',g.shape.enabled?'On':'Off'];
})));
table(setup,'Processing intervals',['Revision','First pair','Last pair','Processed','Accepted'],(D.history||[]).map(h=>[h.revision,h.first,h.last,h.processed,h.accepted].map(v=>v==null?'—':fmt(v))));
function plot(parent,title,series,xLabel,yLabel,options={}){
 const card=el('section');card.className='plot-card';card.append(el('h3',title));$(parent).append(card);const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 620 272');card.append(svg);
 const log=options.log,points=series.flatMap(t=>t.pts);let low=Infinity,high=-Infinity,top=log?10:1;
 for(const [x,y] of points){low=Math.min(low,x);high=Math.max(high,x);top=Math.max(top,y*1.1);}
 if(options.domain)[low,high]=options.domain;if(!isFinite(low)){low=0;high=1;}if(high===low)high+=1;
 const initial=options.axes||[low,high,log?(options.binWidth ? 0.75 : 1):0,options.top??top];
 const full=options.circles&&options.analysisRange?[...options.analysisRange,initial[2],options.topInRange(...options.analysisRange)]:initial;
 let view=initial,anchor=null,box,rangeInputs;
 const mark=(tag,attrs,txt)=>{const n=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))n.setAttribute(k,v);if(txt!==undefined)n.textContent=txt;svg.append(n);return n;};
 const L=53,R=603,T=22,B=232,fy=y=>log?Math.log10(Math.max(.75,y)):y,X=x=>L+(x-view[0])/(view[1]-view[0])*(R-L),Y=y=>B-(fy(y)-fy(view[2]))/(fy(view[3])-fy(view[2]))*(B-T);
 function draw(){svg.replaceChildren();mark('rect',{width:620,height:272,fill:'white'});
 const fractions=[0,.25,.5,.75,1],decades=[];
 if(log)for(let e=Math.ceil(fy(view[2]));e<=Math.floor(fy(view[3]));e++)decades.push(10**e);
 let ticks=fractions.map(f=>view[2]+f*(view[3]-view[2]));
 if(log){
  const rounded=fractions.map(f=>Math.round(10**(fy(view[2])+f*(fy(view[3])-fy(view[2])))));
  ticks=decades.length>=2?decades:[...new Set(rounded)].filter(y=>y>=view[2]&&y<=view[3]);
 }
 for(const y of ticks){mark('line',{x1:L,x2:R,y1:Y(y),y2:Y(y),stroke:'#e1eaf1'});mark('text',{x:L-7,y:Y(y)+3,'font-size':10,'text-anchor':'end',fill:slate},fmt(Number(y.toPrecision(3))));}
 for(const f of fractions){const x=view[0]+f*(view[1]-view[0]);mark('text',{x:X(x),y:251,'font-size':10,'text-anchor':'middle',fill:slate},fmt(Number(x.toPrecision(4))));}
 const clipId='clip-'+parent+'-'+Array.from($(parent).children).indexOf(card);const defs=mark('defs',{}),clip=document.createElementNS(ns,'clipPath'),rect=document.createElementNS(ns,'rect');clip.id=clipId;for(const[k,v]of Object.entries({x:L,y:T,width:R-L,height:B-T}))rect.setAttribute(k,v);clip.append(rect);defs.append(clip);
 const cut={'clip-path':'url(#'+clipId+')'},poly=(coords)=>coords.map(([x,y])=>X(x)+','+Y(y)).join(' ');
 for(const [i,w] of (options.windows||[]).entries()){
  mark('rect',{...cut,x:X(w.lo),y:T,width:X(w.hi)-X(w.lo),height:B-T,fill:w.color,opacity:.09});
  for(const v of [w.lo,w.hi])mark('line',{...cut,x1:X(v),x2:X(v),y1:T,y2:B,stroke:w.color,'stroke-dasharray':'3 3'});
  const left=Math.max(L,X(w.lo)),right=Math.min(R,X(w.hi));
  if(right>left){mark('line',{x1:left,x2:right,y1:T,y2:T,stroke:w.color,'stroke-width':1.6});if(right-left>=30)mark('text',{x:(left+right)/2,y:T+13,'text-anchor':'middle','font-size':10,fill:w.color},i?'Stop':'Start');}
 }
 if(options.grid){const g=options.grid,c=el('canvas');c.width=g.nx;c.height=g.ny;const ctx=c.getContext('2d'),img=ctx.createImageData(c.width,c.height),max=g.cells.reduce((m,a)=>Math.max(m,a[1]),1),palette=[[222,240,249],[127,196,218],[47,145,170],[252,215,113],[238,128,53],[191,47,38],[129,18,38]];for(const [i,n] of g.cells){const p=Math.log1p(n)/Math.log1p(max)*6,k=Math.min(5,Math.floor(p)),at=4*((g.ny-1-Math.floor(i/g.nx))*g.nx+i%g.nx);img.data.set([...palette[k].map((v,j)=>Math.round(v+(palette[k+1][j]-v)*(p-k))),255],at);}ctx.putImageData(img,0,0);mark('image',{...cut,x:L,y:T,width:R-L,height:B-T,preserveAspectRatio:'none',style:'image-rendering:pixelated',href:c.toDataURL()});}
 if(options.fit){const f=options.fit;mark('line',{...cut,x1:L,x2:R,y1:Y(f.slope*view[0]+f.intercept),y2:Y(f.slope*view[1]+f.intercept),stroke:f.color||slate,'stroke-dasharray':'5 3'});}
 const traceGroup=mark('g',{'data-traces':''});for(const [order,trace] of series.entries()){{let path='';if(options.circles)path=circlePath(trace.pts,X,Y,view[0],view[1],trace.key==='total'?2.9:trace.key==='superimposed'?3.7:2.15);else if(options.binWidth)path=stepPath(trace.pts,X,Y,view[0],view[1],view[2],options.binWidth);else for(const[x,y]of trace.pts){if(log&&y<=0)continue;const px=X(x).toFixed(2),py=Y(y).toFixed(2);path+=options.line?(path?'H'+px+'V'+py:'M'+px+' '+py):'M'+px+' '+py+'h.01';}traceGroup.append(mark('path',{'data-order':order,...cut,d:path,stroke:trace.col,fill:'none',...(trace.key?{'data-series':trace.key}:{}),'stroke-width':options.circles?1.35:options.line?1.7:2.5,'stroke-linecap':'round','stroke-dasharray':trace.dashed?'4 2':'none'}));}}
 if(options.polygon)mark('polygon',{...cut,points:poly(options.polygon),stroke:options.role==='stop'?purple:teal,fill:options.role==='stop'?purple:teal,'fill-opacity':options.enabled?.13:.035,'stroke-dasharray':options.enabled?'none':'3 3'});
 mark('text',{x:L,y:13,'font-size':11,fill:slate},yLabel+(log?' · log scale':''));mark('text',{x:(L+R)/2,y:270,'text-anchor':'middle','font-size':11,fill:slate},xLabel);
 if(rangeInputs)rangeInputs.forEach((input,i)=>input.value=view[i]);}
 const pos=e=>{const r=svg.getBoundingClientRect();return [Math.max(L,Math.min(R,(e.clientX-r.left)*620/r.width)),Math.max(T,Math.min(B,(e.clientY-r.top)*272/r.height))];};
 const coords=([x,y])=>[view[0]+(x-L)/(R-L)*(view[1]-view[0]),log?10**(fy(view[3])-(y-T)/(B-T)*(fy(view[3])-fy(view[2]))):view[3]-(y-T)/(B-T)*(view[3]-view[2])];
 svg.onpointerdown=e=>{if(options.locked)return;anchor=pos(e);svg.setPointerCapture(e.pointerId);box=mark('rect',{fill:'#159c9d','fill-opacity':.12,stroke:teal});};
 svg.onpointermove=e=>{if(!anchor)return;const at=pos(e);for(const[k,v]of Object.entries({x:Math.min(at[0],anchor[0]),y:Math.min(at[1],anchor[1]),width:Math.abs(at[0]-anchor[0]),height:Math.abs(at[1]-anchor[1])}))box.setAttribute(k,v);};
 svg.onpointerup=e=>{if(!anchor)return;const at=pos(e);if(Math.abs(at[0]-anchor[0])>4&&Math.abs(at[1]-anchor[1])>4){const a=coords(at),b=coords(anchor);view=[Math.min(a[0],b[0]),Math.max(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[1],b[1])];}anchor=null;draw();};svg.ondblclick=()=>{view=full;draw();};draw();
 if(options.badges){const badges=el('div');for(const [label,style,help] of options.badges){const b=el('span',label);b.className='badge '+style;if(help)b.title=help;badges.append(b);}card.append(badges);}
 if(options.analysisRange){
  const controls=el('details'),body=el('form');body.className='report-range';controls.append(el('summary',options.circles?'Time range':'Pulse-height range'),body);card.append(controls);
  const numbers=['From','To'].map((name,i)=>{const label=el('label',name),input=el('input');input.type='number';input.step='any';input.required=true;input.value=view[i];label.append(input);body.append(label);return input;});
  rangeInputs=numbers;
  const bounds=options.analysisRange,unit=options.circles?'ns':'mV',apply=el('button','Set range · '+unit);body.append(apply);
  const setRange=(lo,hi)=>{view=[lo,hi,full[2],options.topInRange?.(lo,hi)??full[3]];numbers[0].value=lo;numbers[1].value=hi;controls.open=false;draw();};
  body.onsubmit=e=>{e.preventDefault();const lo=numbers[0].valueAsNumber,hi=numbers[1].valueAsNumber;
   if(!(lo>=bounds[0]&&hi<=bounds[1]&&lo<hi)){numbers[0].setCustomValidity('Choose increasing limits inside the exported range.');numbers[0].reportValidity();return;}setRange(lo,hi);};
  numbers.forEach(i=>i.oninput=()=>numbers[0].setCustomValidity(''));const preset=(name,limits)=>{const b=el('button',name);b.type='button';b.onclick=()=>setRange(...limits);body.append(b);};
  if(!options.circles)preset('Full ADC',bounds);if(options.channel)for(const r of ['start','stop'])preset('Focus '+r,phsDomain({mode:r},options.channel,bounds[1]));
 }
 if(options.fitInfo){const details=el('details');details.append(el('summary','Fit options at export'),el('small',options.fitInfo));card.append(details);}
 if(options.legend)card.append(el('p',options.legend));const tools=el('div');tools.className='plot-actions';card.append(tools);const btn=(t,fn)=>{const b=el('button',t);b.onclick=fn;tools.append(b);};if(!options.locked)btn(options.circles?'Reset to configured time range':'Fit all',svg.ondblclick);if(options.changeView)btn(options.grid.fixed?'Full range':options.focusLabel,options.changeView);
 for(const ext of ['csv','txt'])btn(ext.toUpperCase(),()=>{const sep=ext==='csv'?',':'\t';if(options.grid){const g=options.grid,[a,b,c,d]=g.axes,dx=(b-a)/g.nx,dy=(d-c)/g.ny;download(title+'.'+ext,[['x_low','x_high','y_low','y_high','pulses'],...g.cells.map(([i,n])=>{const x=a+i%g.nx*dx,y=c+Math.floor(i/g.nx)*dy;return [x,x+dx,y,y+dy,n];})].map(r=>r.join(sep)).join('\n'));return;}download(title+'.'+ext,[['Series',xLabel,yLabel].join(sep),...series.flatMap(t=>t.pts.map(q=>[t.name,...q].join(sep)))].join('\n'));});
 btn('SVG',()=>download(title+'.svg',new XMLSerializer().serializeToString(svg),'image/svg+xml'));
 btn('PNG',()=>{const src=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml'})),img=new Image();img.onload=()=>{const c=el('canvas');c.width=1240;c.height=544;c.getContext('2d').drawImage(img,0,0,1240,544);URL.revokeObjectURL(src);c.toBlob(b=>download(title+'.png',b));};img.src=src;});
}
function drawComparison(){
 const direction=$('direction').value,v=p.analysis.displays[direction],all=D.comparison.all_paths?.[direction];
 const result=$('report-paths').value==='all'&&all?all:D.comparison.comparisons[direction];$('path-label').hidden=!all;
 v.show_total=$('total').checked;v.show_superimposed=$('superimposed').checked;
 p.analysis.direction=direction;v.categories=[...sel].filter(k=>!p.subtypes.includes(k));v.subtype_overlays=[...sel].filter(k=>p.subtypes.includes(k));v.category='all';v.individual=v.categories.length>0;
 $('summary').textContent=fmt(v.bin_ps)+' ps bins · zero shift '+fmt(v.zero_ps)+' ps';
 for(const box of $('classes').querySelectorAll('input')){
  box.parentElement.title=p.guide[direction]?.[box.value]??'';
  const span=box.parentElement.querySelector('span');span.replaceChildren(document.createTextNode(p.categoryNames[box.value]));
  result.stages.slice(0,result.filter_active?2:1).forEach((s,i)=>{const n=s.classes[box.value]??s.subclasses?.[box.value]??0,den=s.phs[0].counts;
   span.append(el('small',(i?'After':'Before')+' '+fmt(n)+' · '+(den?(100*n/den).toFixed(2)+'%':'—')));});
 }
 for(const [row,title] of ['Lifetime','Pulse height A','Pulse height B'].entries())for(const [stage,cohort] of result.stages.entries()){
  const caption=title+' · '+(stage?'After filters':'Before filters');
  if(stage&&!result.filter_active){const card=el('section');card.className='plot-card inactive';card.append(el('h3',caption),el('p','Optional filters off'));$('spectra').append(card);continue;}
  const h=row?cohort.phs[row-1]:cohort.lifetime,lo=row?0:v.low_ns,hi=row?D.comparison.adc_heights[row-1]:v.high_ns;
  const width=row?hi/v.phs_bins[row-1]:v.bin_ps/1000,pts=bins=>bins.map(([i,y])=>[lo+(i+.5)*width,y]);
  const series=v.show_total?[{key:'total',name:'Total spectrum',col:p.traceColors.total,pts:pts(h.bins)}]:[];
  if($('individual').checked)for(const key of sel){const bins=h.layers[key]??h.sublayers?.[key];if(bins)series.push({key,name:p.categoryNames[key],col:p.classColors[key],pts:pts(bins),dashed:!!row});}
  if(v.show_superimposed)series.push({key:'superimposed',name:'Superimposed spectrum',col:p.traceColors.superimposed,pts:pts(sumBins(h,sel,k=>p.subtypeGroups[k]?.parent))});
  const windows=row?['start','stop'].map(r=>({lo:D.profile.channels[row-1][r].phs.low,hi:D.profile.channels[row-1][r].phs.high,color:r==='start'?teal:purple})):[];
  const channel=row?D.profile.channels[row-1]:null,domain=row?phsDomain(v.phs_views?.[row-1],channel,hi):(v.time_view??[lo,hi]);
  const raw=row?result.stages[0].phs[row-1]:result.stages[0].lifetime;
  const topInRange=(a,b)=>Math.max(row?1:10,raw.bins.reduce((m,[i,n])=>lo+(i+1)*width>=a&&lo+i*width<=b?Math.max(m,n):m,0)*(row?1.06:1.35));
  plot('spectra',caption,series,row?'Pulse height (mV)':'Time difference (ns)',row?'Pulses / bin':'Pairs / bin',{windows,domain,circles:!row,log:!row,binWidth:width,top:topInRange(...domain),topInRange,channel,analysisRange:[lo,hi],legend:fmt(h.counts)+(row?' pulses':' pairs')+(row?'':' · '+fmt(cohort.phs[0].counts-h.counts)+' outside time range')});
 }
 const cables=D.comparison.cable_delays_ns;
 $('selection').textContent=p.spectrumNames[direction]+' · '+fmt(result.stages[0].phs[0].counts)+' directional pairs · '+(cables.every(v=>v!=null)?'Cable A '+fmt(cables[0])+' ns · Cable B '+fmt(cables[1])+' ns':'Recorded CF times · cable delays unavailable');
}
function drawSpectra(){$('spectra').replaceChildren();if(D.comparison){drawComparison();return;}let total=0;for(const s of D.spectra){
 const n=Math.ceil((p.view.high_ns-p.view.low_ns)*1000/p.view.bin_ps),sum=new Float64Array(n),series=[];
 for(const c of s.contributions){if(!sel.has(c.category))continue;for(const [x,y] of c.points){const i=Math.round((x-p.view.low_ns)*1000/p.view.bin_ps-.5);sum[i]+=y;total+=y;}
 if($('individual').checked)series.push({name:p.categoryNames[c.category],col:p.classColors[c.category],pts:c.points});}
 const pts=Array.from(sum,(y,i)=>[p.view.low_ns+(i+.5)*p.view.bin_ps/1000,y]);series.unshift({name:'Selected sum',col:series.length?'#344e65':teal,pts});
 plot('spectra',p.directionNames[s.direction],series,'Time difference − zero shift (ns)','Counts / bin',{log:true,domain:[p.view.low_ns,p.view.high_ns],legend:fmt(sum.reduce((a,b)=>a+b,0))+' selected counts · from pair '+fmt(D.spectrum_first[['AB','BA','SS'].indexOf(s.direction)])});}
 $('selection').textContent=fmt(total)+' selected counts · light origin '+p.view.origin+' · scattering '+p.view.scatter;}
function emphasize(key){for(const path of $('spectra').querySelectorAll('[data-series]'))path.setAttribute('opacity',key&&path.dataset.series!==key?'.18':'1');
 for(const group of $('spectra').querySelectorAll('g[data-traces]')){
  const traces=[...group.children].sort((a,b)=>Number(a.dataset.series===key)-Number(b.dataset.series===key)||a.dataset.order-b.dataset.order);
  for(const t of traces)group.append(t);
 }}
function bindHighlight(label,input,key){label.onmouseenter=()=>emphasize(input.checked&&key);label.onmouseleave=()=>emphasize(null);
 input.onfocus=label.onmouseenter;input.onblur=label.onmouseleave;}
function classOption(k){
 const label=el('label'),box=el('input');box.type='checkbox';box.value=k;box.checked=sel.has(k);
 box.onchange=()=>{if(box.checked)sel.add(k);else sel.delete(k);if(D.comparison)$('individual').checked=sel.size>0;drawSpectra();};
 label.className='report-class';label.style.borderColor=p.classColors[k];label.append(box,el('span',p.categoryNames[k]+' · '+fmt(D.category_counts[k]??0)));
 label.title=p.guide[p.analysis.direction]?.[k]??p.categoryHelp[k]??'';bindHighlight(label,box,k);return label;
}
for(const k of D.categories){
 const branch=el('div');branch.className='report-branch';branch.append(classOption(k));$('classes').append(branch);
 const keys=p.subtypes.filter(s=>p.subtypeGroups[s].parent===k);
 if(!keys.length)continue;
 const details=el('details'),group=el('div');group.className='report-subtypes';group.dataset.parent=k;details.append(el('summary','Subtypes ('+keys.length+')'),group);branch.append(details);
 let facet;
 for(const s of keys){const next=p.subtypeGroups[s].facet;if(next&&next!==facet)group.append(el('h5',next));facet=next;group.append(classOption(s));}
}
for(const id of ['all','none'])$(id).onclick=()=>{sel.clear();for(const box of $('classes').querySelectorAll('input')){if(id==='none'||!p.subtypes.includes(box.value))box.checked=id==='all';if(box.checked)sel.add(box.value);}if(D.comparison)$('individual').checked=sel.size>0;drawSpectra();};
function loadDirection(){
 const v=p.analysis.displays[$('direction').value];sel.clear();
 const selected=[...(v.individual?(v.categories??(v.category==='all'?D.categories:[v.category])):[]),...(v.subtype_overlays??[])];
 for(const box of $('classes').querySelectorAll('input')){box.checked=selected.includes(box.value);if(box.checked)sel.add(box.value);}
 $('individual').checked=selected.length>0;$('total').checked=v.show_total!==false;$('superimposed').checked=!!v.show_superimposed;$('report-paths').value='display';drawSpectra();
}
if(D.comparison){$('report-individual').hidden=true;for(const [k,name] of Object.entries(p.spectrumNames)){$('direction').append(new Option(name,k));}
 $('direction').value=p.analysis.direction;$('direction').onchange=loadDirection;loadDirection();}
else{$('report-total').hidden=true;$('report-superimposed').hidden=true;$('direction-label').hidden=true;$('individual').checked=p.view.individual;drawSpectra();}
$('individual').onchange=$('total').onchange=$('superimposed').onchange=$('report-paths').onchange=drawSpectra;bindHighlight($('report-total'),$('total'),'total');bindHighlight($('report-superimposed'),$('superimposed'),'superimposed');
for(const g of maps.filter(g=>g.kind==='phs')){const c=p.profile.channels[g.channel],m=new Map(g.cells),width=g.axes[1]/g.nx,pts=Array.from({length:g.nx},(_,i)=>[i*width,m.get(i)||0]);pts.push([g.axes[1],pts.at(-1)[1]]);const windows=['start','stop'].map(r=>({lo:c[r].phs.low,hi:c[r].phs.high,color:r==='start'?teal:purple}));
 plot('heights','Pulse height · '+'AB'[g.channel],[{name:'Measured CF pulses',col:g.channel?slate:teal,pts}],'Pulse height (mV)','Pulses / bin',{line:true,locked:true,windows,domain:g.axes.slice(0,2),legend:fmt(g.total)+' total · '+g.nx+' bins · Start '+fmt(g.windows[0])+' · Stop '+fmt(g.windows[1])+(g.above_adc?' · '+fmt(g.above_adc)+' above ADC span included in the last bin':'')});}
const areaView=new Map();
function diagnostics(){$('diagnostics').replaceChildren();for(const r of ['start','stop'])for(const i of [0,1]){
 const kind=$('filter').value,key='AB'[i]+'-'+r,available=maps.filter(g=>g.kind===kind&&g.role===r&&g.channel===i);
 const g=available.find(v=>!!v.fixed===areaView.get(key))||available[0];if(!g)continue;
 const opt=p.profile.channels[i][r],w=opt.phs,b=opt.area,s=opt.shape,a=s.angle_deg*Math.PI/180,area=kind==='area';
 const fitOpts=area?(p.monitor?.area_fit?.[key]||{low:2.5,high:97.5}):(p.monitor?.shape_fit?.[key]||{low:25,high:75,fence:1.5,coverage:95});
 const fitInfo=area?'Residual percentiles '+fmt(fitOpts.low)+' and '+fmt(fitOpts.high):'Flank percentiles '+fmt(fitOpts.low)+' and '+fmt(fitOpts.high)+' · fence × '+fmt(fitOpts.fence)+' · target measured ellipse coverage '+fmt(fitOpts.coverage)+'%';
 const polygon=area?[[w.low,-1],[w.high,-1],[w.high,1],[w.low,1]].map(([x,k])=>[x,b.slope*x+b.intercept+(k<0?-b.below:b.above)]):Array.from({length:91},(_,j)=>{const theta=2*Math.PI*j/90,u=s.radius_rise*Math.cos(theta),v=s.radius_fall*Math.sin(theta);return [s.rise+u*Math.cos(a)-v*Math.sin(a),s.fall+u*Math.sin(a)+v*Math.cos(a)];});
 plot('diagnostics',(area?'Pulse area':'Rise / fall time')+' · '+'AB'[i]+' · '+r,[],area?'Pulse height (mV)':'Rise 10–90% (ns)',area?'Window area (mV ns)':'Fall 90–10% (ns)',{grid:g,locked:true,axes:g.axes,fit:area?b:null,polygon,enabled:opt[kind].enabled,role:r,fitInfo,badges:[[fmt(g.total)+' total','',g.incomplete?fmt(g.incomplete)+' timed pulses lack a complete rise or fall.':''],['PHS: '+fmt(w.low)+'–'+fmt(w.high)+' mV',r],['Filter '+(opt[kind].enabled?'enabled':'disabled'),'']],focusLabel:available.some(v=>v.fixed&&(v.axes[0]!==available.find(x=>!x.fixed)?.axes[0]||v.axes[1]!==available.find(x=>!x.fixed)?.axes[1]))?'PHS window':'Fit to diagonal',changeView:area&&available.length>1?()=>{areaView.set(key,!g.fixed);diagnostics();}:null,legend:fmt(g.visible)+' in view · '+g.nx+' × '+g.ny+' bins · from CF pulse '+fmt(g.first)});}}
 const diagnosticsSection=$('filter-section');
diagnosticsSection.ontoggle=()=>{if(diagnosticsSection.open&&!$('diagnostics').childElementCount)diagnostics();};
$('filter').onchange=diagnostics;
`;

