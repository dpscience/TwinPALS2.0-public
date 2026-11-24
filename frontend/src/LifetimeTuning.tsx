// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {Fragment,useEffect,useRef,useState,type ReactNode} from 'react';
import {Crosshair,RotateCcw,SlidersHorizontal,ScanLine,ChartNoAxesCombined} from 'lucide-react';
import {MeasurementIllustration,ProcessingPath,TimingDiagram,timingExplanations,type TimingDiagramKind} from './MeasurementIllustration';
import {Help} from './Fields';
import {percent} from './api';
import {Modal} from './Modal';
import {LifetimePlot} from './LifetimePlot';
import {baselineRegions,defaultAreaFit,defaultShapeFit,type ShapeFit,type ShapeFitCount,type LifetimeChannel,type MeasurementGrid,type MonitorView,type DensityView,type Axes} from './m3types';
import type {WindowRole} from './lifetimeEditing';

export const roles=['start','stop'] as const;
export const detectors=[0,1] as const;
const label=(s:string)=>s[0].toUpperCase()+s.slice(1);
export const plotKey=(kind:string,ch:number,role:WindowRole)=>[kind,'AB'[ch],role].join('-');
const defaults:DensityView={nx:256,ny:256,axes:null};
export function measurementSpecs(section:string,channels:LifetimeChannel[],m:MonitorView){
 if(section==='PHS')return detectors.map(channel=>({kind:'phs',channel,nx:m.phs_bins[channel],windows:roles.map(r=>channels[channel][r].phs)}));
 if(section==='Filters')return roles.flatMap(role=>detectors.map(channel=>({kind:m.filter_kind,channel,role,...(m.plots[plotKey(m.filter_kind,channel,role)]??defaults)})));
 return [];
}
export function LiveNumber({value,change,name,min,max,step='any',disabledReason,confirmEdit=false}:{value:number;change:(v:number)=>void;name:string;min?:number;max?:number;step?:number|'any';disabledReason?:string;confirmEdit?:boolean}){
 const format=(n:number)=>String(Number(n.toPrecision(7)));
 const [draft,setDraft]=useState<string|null>(null),input=useRef<HTMLInputElement>(null);
 const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),callback=useRef(change),dirty=useRef(false);
 callback.current=change;
 useEffect(()=>{if(!dirty.current||document.activeElement!==input.current)setDraft(null);},[value]);
 useEffect(()=>()=>clearTimeout(timer.current),[]);
 const commit=()=>{clearTimeout(timer.current);const e=input.current;
  if(!dirty.current||!e?.value||e.disabled||!e.validity.valid)return;
  dirty.current=false;if(e.valueAsNumber!==value)callback.current(e.valueAsNumber);
 };
 return <input aria-label={name} ref={input} type="number" min={min} max={max} step={step}
  disabled={!!disabledReason} title={disabledReason} aria-description={disabledReason}
  value={draft??format(value)}
  onFocus={()=>{dirty.current=false;}}
  onChange={e=>{dirty.current=true;setDraft(e.target.value);clearTimeout(timer.current);if(!confirmEdit)timer.current=setTimeout(commit,220);}}
  onBlur={()=>{commit();dirty.current=false;setDraft(null);}}
  onKeyDown={e=>{if(e.key==='Enter')e.currentTarget.blur();}}/>;
}
export function ResetButton({name,disabled,onClick}:{name:string;disabled:boolean;onClick:()=>void}){
 return <button aria-label={'Reset '+name} title={'Clear '+name+' counts and continue from here'} disabled={disabled} onClick={onClick}><RotateCcw size={14}/></button>;
}
export function PulseSelection({value,change}:{value:'first'|'highest';change:(r:'first'|'highest')=>void}){
 return <label className="m3-selection-rule"><span className="m3-row-label">Both channels <Help text="One rule applies to both channels. Highest uses the largest baseline-relative excursion after median filtering. First searches after the baseline samples for the first upward crossing of the greater of the minimum height and five times the noise. It follows the running maximum until the signal falls by at least the greater of 10% of that maximum and five times the noise, or the readout ends. Equal maxima use the earliest sample. PHS, CF and flank levels refer to that peak. A failed cut rejects the channel."><div className="m3-diagram-pair"><MeasurementIllustration first/><MeasurementIllustration first={false}/></div></Help></span>
 <select aria-label="Pulse selection for A and B" value={value} onChange={e=>change(e.target.value as 'first'|'highest')}><option value="highest">Highest pulse</option><option value="first">First pulse</option></select></label>;
}
export type EditorProps={channels:LifetimeChannel[];edit:(ch:number,c:LifetimeChannel,preview?:boolean)=>void};
function Matrix({title,unit,help,diagram,children}:{title:string;unit?:string;help?:string;diagram?:TimingDiagramKind;children:ReactNode}){
 return <div className="m3-setting-row"><span className="m3-row-label"><span>{title}{unit&&<small className="m3-setting-unit">{unit}</small>}</span>{help&&<Help text={help}>{diagram&&<TimingDiagram kind={diagram}/>}</Help>}</span>{children}</div>;
}
function ChannelColumns(){return <><span/>{detectors.map(i=><b key={i} className={'m3-channel '+(i?'b':'a')}>Channel {'AB'[i]}</b>)}</>;}
function PulseFields({children}:{children:ReactNode}){
 return <div className="m3-filter-matrix m3-pulse-fields"><ChannelColumns/><span className="m3-matrix-divider" aria-hidden="true"/>{children}</div>;
}
function ToggleCell({name,value,change}:{name:string;value:boolean;change:(v:boolean)=>void}){return <label className="m3-check"><input type="checkbox" aria-label={name} checked={value} onChange={e=>change(e.target.checked)}/></label>;}
export function TimingSettings({channels,edit,m,patch,rule,selectRule}:{m:MonitorView;patch:(m:MonitorView)=>void;rule:'first'|'highest';selectRule:(r:'first'|'highest')=>void}&EditorProps){
 return <><ProcessingPath selection={rule}/>
 <section className="m3-settings-section"><h3>Pulse selection</h3><PulseSelection value={rule} change={selectRule}/><PulseFields>
 <Matrix title="Median filter" diagram="median" help={timingExplanations.median.text}>{channels.map((c,i)=><select key={i} aria-label={'AB'[i]+' median filter'} value={c.median_samples} onChange={e=>edit(i,{...c,median_samples:+e.target.value})}>{[1,3,5,7,9,11,13,15,17,19,21,...(c.median_samples>21?[c.median_samples]:[])].map(n=><option key={n} value={n} disabled={n>21}>{n===1?'Off':n>21?n+' (imported)':n}</option>)}</select>)}</Matrix>
 <Matrix title="Min. height" unit="mV" diagram="height" help={timingExplanations.height.text}>{channels.map((c,i)=><LiveNumber key={i} name={'AB'[i]+' minimum height'} value={c.minimum_height_mV} min={.0001} change={v=>edit(i,{...c,minimum_height_mV:v})}/>)}</Matrix>
 <Matrix title="Reject clipping" diagram="clip" help={timingExplanations.clip.text}>{channels.map((c,i)=><ToggleCell key={i} name={'AB'[i]+' reject clipped pulses'} value={c.reject_clipped} change={v=>edit(i,{...c,reject_clipped:v})}/>)}</Matrix>
 </PulseFields></section>
 <section className="m3-settings-section"><h3>Baseline</h3><PulseFields>
 <Matrix title="Reference" diagram="baseline" help={timingExplanations.baseline.text}>{detectors.map(i=><select key={i} aria-label={'AB'[i]+' baseline mode'} value={channels[i].baseline_mode??'readout'} onChange={e=>edit(i,{...channels[i],baseline_mode:e.target.value as LifetimeChannel['baseline_mode']})}><option value="readout">Readout start</option><option value="pre_pulse">Before pulse</option></select>)}</Matrix>
 <Matrix title="Length" unit="samples" diagram="baseline" help="The median of these raw ADC samples sets the voltage reference. Both modes use their median absolute deviation to estimate noise.">{channels.map((c,i)=><LiveNumber key={i} name={'AB'[i]+' baseline length'} value={c.baseline_samples} min={4} max={4096} step={1} change={n=>{
   const offset=c.baseline_samples+(c.baseline_gap??4);
   edit(i,{...c,baseline_samples:n,baseline_gap:c.baseline_mode==='pre_pulse'?Math.min(4096,Math.max(0,offset-n)):c.baseline_gap});
  }}/>) }</Matrix>
 <Matrix title="Start offset" unit="samples" diagram="pre_pulse" help={timingExplanations.pre_pulse.text}>{channels.map((c,i)=><LiveNumber key={i} name={'AB'[i]+' baseline start before onset'} value={c.baseline_samples+(c.baseline_gap??4)} min={c.baseline_samples} max={c.baseline_samples+4096} step={1} disabledReason={c.baseline_mode!=='pre_pulse'?'Choose Before pulse to set the distance from onset.':undefined} change={offset=>edit(i,{...c,baseline_gap:offset-c.baseline_samples})}/>)}</Matrix>
 <Matrix title="Show region" help="Shade the ADC samples used for the baseline in the selected channel’s waveform.">{detectors.map(i=><ToggleCell key={i} name={'AB'[i]+' show baseline region'} value={baselineRegions(m.show_baseline)[i]} change={v=>{const regions=baselineRegions(m.show_baseline);regions[i]=v;patch({...m,show_baseline:regions});}}/>)}</Matrix>
 </PulseFields></section>
 <section className="m3-settings-section"><h3>Constant-fraction timing</h3><PulseFields>
 <Matrix title="CF level · %" diagram="CF" help={timingExplanations.CF.text}>{channels.map((c,i)=><LiveNumber key={i} name={'AB'[i]+' CF level'} value={c.cfd_percent} min={.001} max={99.999} change={v=>edit(i,{...c,cfd_percent:v})}/>)}</Matrix>
 <Matrix title="Interpolation" diagram="interpolation" help={timingExplanations.interpolation.text}>{detectors.map(i=><select key={i} aria-label={'AB'[i]+' interpolation'} value={channels[i].interpolation??'linear'} onChange={e=>edit(i,{...channels[i],interpolation:e.target.value as LifetimeChannel['interpolation']})}>{['linear','cubic','akima'].map(k=><option key={k} value={k}>{label(k)}</option>)}</select>)}</Matrix>
 <Matrix title="Intra-steps" diagram="interpolation" help={timingExplanations.interpolation.text}>{channels.map((c,i)=><LiveNumber key={i} name={'AB'[i]+' interpolation subdivisions'} value={c.intra_steps??8} min={1} max={64} step={1}
  disabledReason={(c.interpolation??'linear')==='linear'?'Linear locates the crossing directly. Choose Cubic or Akima to set intra-steps.':undefined}
  change={v=>edit(i,{...c,intra_steps:v})}/>)}</Matrix>
 <Matrix title="Show curve" help="Overlay the interpolated pulse used to locate the crossing times on each channel.">{detectors.map(i=><ToggleCell key={i} name={'AB'[i]+' show interpolated trace'} value={m.traces[i]} change={v=>{const traces:[boolean,boolean]=[...m.traces];traces[i]=v;patch({...m,traces});}}/>)}</Matrix>
 </PulseFields></section></>;
}
export function WindowSettings({channels,edit,m,patch}:EditorProps & {m:MonitorView;patch:(m:MonitorView)=>void}){
 const columns=detectors.flatMap(i=>roles.map(r=>({i,r,id:'AB'[i]+'-'+r})));
 return <section className="m3-settings-section"><h3>Pulse-height windows <Help text="Each selected peak with a measurable CF time contributes to its channel. The shaded intervals and counts use the current Start and Stop windows."><MeasurementIllustration mode="phs"/></Help></h3>
  <div className="m3-filter-matrix m3-phs-matrix"><ChannelColumns/>
   <span className="m3-row-label">Bins <Help text="Choose 8–2048 bins across the ADC range for each channel. Press Enter or leave the field. Every timed pulse since the last PHS reset is rebinned. Window counts use measured heights."/></span>
   {detectors.map(i=><div className="m3-channel-field" key={i}><LiveNumber name={'PHS bins '+'AB'[i]} value={m.phs_bins[i]} min={8} max={2048} step={1} confirmEdit change={v=>{const phs_bins:[number,number]=[...m.phs_bins];phs_bins[i]=v;patch({...m,phs_bins});}}/></div>)}
   <span className="m3-matrix-divider" aria-hidden="true"/><WindowRoles/>
   {(['low','high'] as const).map(key=><Fragment key={key}><span className="m3-row-label">{key==='low'?'Lower':'Upper'} · mV <Help text={key==='low'?'Includes the lower edge. Drag the handle on the plot or enter a voltage.':'Excludes the upper edge. Start and Stop may touch at one edge.'}/></span>
    {columns.map(({i,r,id})=><LiveNumber key={id} name={'AB'[i]+' '+r+' '+key} value={channels[i][r].phs[key]} min={0} change={v=>{const c=channels[i];edit(i,{...c,[r]:{...c[r],phs:{...c[r].phs,[key]:v}}});}}/>)}</Fragment>)}
  </div></section>;
}
function WindowRoles(){
 return <><span className="m3-row-label">PHS window</span>{detectors.flatMap(i=>roles.map(r=><span key={i+r} className={'m3-pill '+r}>{label(r)}</span>))}</>;
}
function WindowColumns(){
 return <><ChannelColumns/><WindowRoles/><span className="m3-matrix-divider" aria-hidden="true"/></>;
}
type FilterKind='area'|'shape';
type FilterProps={m:MonitorView;patch:(m:MonitorView)=>void;place:string;setPlace:(s:string)=>void;fit:(kind:FilterKind,ch:number,role:WindowRole)=>void;ready:boolean;fitting?:string}&EditorProps;
const areaFields={slope:'Slope · ns',intercept:'Intercept · mV ns',below:'Lower width · mV ns',above:'Upper width · mV ns'};
const shapeFields={rise:'Rise centre · ns',fall:'Fall centre · ns',radius_rise:'First radius · ns',radius_fall:'Second radius · ns',angle_deg:'Rotation · °'};
const fitHelp={
 area:'Fit a least-squares line to every measured height and full-readout area in this PHS window since the channel’s last area reset. The selected percentiles of the residuals set the lower and upper widths around the line. Fit enables this band.',
 shape:'For each axis, measure the selected percentiles in this PHS window. Extend both ends by the fence multiplier times their separation. Fit the mean and covariance of the pulses inside both fences. Those pulses set the centre and orientation. The radii expand to enclose the requested share of all complete measurements in this PHS window, including its tails. Choose a coverage above 0% and up to 100%, then Fit.'
};
function FitOptions({kind,m,patch,close}:{kind:FilterKind;m:MonitorView;patch:(m:MonitorView)=>void;close:()=>void}){
 const cols=detectors.flatMap(i=>roles.map(r=>({key:'AB'[i]+'-'+r,r})));
 const shape=kind==='shape';
 const fields:(keyof ShapeFit)[]=shape?['low','high','fence','coverage']:['low','high'];
 const names={low:'Lower percentile',high:'Upper percentile',fence:'Fence multiplier',coverage:'Ellipse coverage · %'};
 return <Modal title={(shape?'Rise / fall':'Area')+' fit options'} close={close}><p className="m3-fit-description">{fitHelp[kind]}</p>
  <div className="m3-filter-matrix m3-fit-options"><WindowColumns/>
   {fields.map(field=><Fragment key={field}><span className="m3-row-label">{names[field]}</span>{cols.map(({key})=>{
    const values=shape?(m.shape_fit?.[key]??defaultShapeFit):(m.area_fit?.[key]??defaultAreaFit);
    return <LiveNumber key={key} name={key+' '+names[field]} value={(values as ShapeFit)[field]} confirmEdit
      min={field==='high'?values.low+.000001:field==='coverage'?.000001:0}
      max={field==='low'?values.high-.000001:field==='high'?100:field==='coverage'?100:undefined}
      change={v=>shape?patch({...m,shape_fit:{...m.shape_fit,[key]:{...(values as ShapeFit),[field]:v}}}):patch({...m,area_fit:{...m.area_fit,[key]:{...values,[field]:v}}})}/>;
   })}</Fragment>)}</div><p className="m3-fit-note">Choose Fit in the window you want to update.</p></Modal>;
}
export function FilterSettings({channels,edit,m,patch,place,setPlace,fit,ready,fitting}:FilterProps){
 const k=m.filter_kind;
 const [options,setOptions]=useState(false);
 const change=(i:number,r:WindowRole,field:string,value:number|boolean)=>{const c=channels[i];edit(i,{...c,[r]:{...c[r],[k]:{...c[r][k],[field]:value}}});};
 const columns=detectors.flatMap(i=>roles.map(r=>({i,r,id:plotKey(k,i,r)})));
 const area=k==='area';
 const measurement=area
  ?'Subtract the baseline and apply the selected median filter. For each pair of adjacent samples, multiply their mean baseline-relative voltage by their calibrated time separation. Sum the absolute trapezoid areas across the entire readout, in mV ns. Later pulses and baseline noise contribute. The horizontal coordinate is the selected peak height.'
  :'Rise spans the leading 10% to 90% of the selected peak. Follow the trailing signal until three consecutive samples lie within ±max(3 × baseline noise, 0.5% of peak height). Measure between the last downward 10% crossing and its preceding downward 90% crossing. A valley followed by another rise belongs to the same tail until the signal settles. An unfinished fall is counted separately. It fails an enabled ellipse cut.';
 const acceptance=area?'The centre line spans the ADC range. Only pulses in this PHS window use the shaded band. Its lower and upper widths are independent.':'The ellipse applies to pulses in its PHS window. Both maps of a channel show every complete rise/fall measurement from that channel.';
 return <><nav className="inspector-tabs m3-inner-tabs" aria-label="Filter type">{(['area','shape'] as const).map(v=><button key={v} className={k===v?'active':''} onClick={()=>{setPlace('');patch({...m,filter_kind:v});}}>{v==='area'?'Area':'Rise / fall time'}</button>)}</nav>
  <h3>{area?'Window area':'Rise and fall times'} <Help text={measurement}><MeasurementIllustration mode={area?'area':'fall'}/></Help><button className="m3-fit-preferences" onClick={()=>setOptions(true)}><SlidersHorizontal size={13}/>Fit options</button></h3>
  {options&&<FitOptions kind={k} m={m} patch={patch} close={()=>setOptions(false)}/>}
  <div className="m3-filter-matrix"><WindowColumns/>
   {(['nx','ny'] as const).map((key,j)=><Fragment key={key}><span className="m3-row-label">{j?'Y bins':'X bins'}{j===0&&<Help text="Choose 8–512 bins on each axis. Press Enter or leave the field to rebin every measured pulse since this channel’s last filter reset."/>}</span>
    {columns.map(({id})=>{const option=m.plots[id]??defaults;return <LiveNumber key={id} name={id+' '+key} value={option[key]} min={8} max={512} step={1} confirmEdit change={v=>patch({...m,plots:{...m.plots,[id]:{...option,[key]:v}}})}/>;})}
   </Fragment>)}
   <span className="m3-row-label">Use filter <Help text={acceptance}><MeasurementIllustration mode={area?'band':'ellipse'}/></Help></span>
   {columns.map(({i,r,id})=><ToggleCell key={id} name={'AB'[i]+' '+r+' '+k+' enabled'} value={channels[i][r][k].enabled} change={v=>change(i,r,'enabled',v)}/>)}
   {Object.entries(area?areaFields:shapeFields).map(([field,title])=><Fragment key={field}><span className="m3-row-label">{title}</span>{columns.map(({i,r,id})=><LiveNumber key={id} name={'AB'[i]+' '+r+' '+field} value={Number((channels[i][r][k] as unknown as Record<string,number>)[field])} min={field.startsWith('radius')?.00001:['rise','fall','below','above'].includes(field)?0:undefined} change={v=>change(i,r,field,v)}/>)}</Fragment>)}
   <span className="m3-row-label">Fit to window <Help text={fitHelp[k]}/></span>
   {columns.map(({i,r,id})=><button key={id} disabled={!ready||!!fitting} aria-busy={fitting===id} onClick={()=>fit(k,i,r)} aria-label={'Fit '+k+' '+r+' '+'AB'[i]} title={'Fit '+(area?'area band':'rise/fall ellipse')+' · '+label(r)+' '+'AB'[i]}><ScanLine size={12}/>{fitting===id?'Fitting…':'Fit'}</button>)}
   {!area&&<><span className="m3-row-label">Ellipse centre</span>{columns.map(({i,r,id})=><button key={id} aria-label={'Place centre '+r+' '+'AB'[i]} aria-pressed={place===id} onClick={()=>setPlace(place===id?'':id)}><Crosshair size={12}/>{place===id?'Cancel':'Place'}</button>)}</>}
  </div></>;
}
function ShapeAxes({id,option,grid,change}:{id:string;option:DensityView;grid?:MeasurementGrid;change:(v:DensityView)=>void}){
 return <details className="m3-grid-options"><summary title={'Axis limits · '+id} aria-label={'Axis limits '+id}><SlidersHorizontal size={14}/></summary><div className="m3-grid-menu">
  <label>Axis range<select aria-label={id+' axis range'} value={option.axes?'fixed':'auto'} onChange={e=>change({...option,axes:e.target.value==='auto'?null:[...(grid?.axes??[0,4,0,8])] as Axes})}><option value="auto">Auto · expand to data</option><option value="fixed">Fixed limits</option></select></label>
  {option.axes&&<div className="lifetime-fields">{['Rise from','Rise to','Fall from','Fall to'].map((k,i)=><label key={k}>{k} · ns<LiveNumber name={id+' '+k} min={0} value={option.axes![i]} change={v=>{const axes:Axes=[...option.axes!];axes[i]=v;if(axes[0]<axes[1]&&axes[2]<axes[3])change({...option,axes});}}/></label>)}</div>}
 </div></details>;
}
function focusedAxes(kind:'area'|'shape',g:LifetimeChannel['start']):Axes{
 if(kind==='area'){
  const {low,high}=g.phs,a=g.area,margin=(high-low)*.12;
  const lo=Math.max(0,low-margin),hi=high+margin,ends=[a.slope*lo+a.intercept,a.slope*hi+a.intercept];
  const bottom=Math.min(...ends)-a.below,top=Math.max(...ends)+a.above,pad=Math.max(1,(top-bottom)*.12);
  return [lo,hi,Math.max(0,bottom-pad),Math.max(1,top+pad)];
 }
 const s=g.shape,t=s.angle_deg*Math.PI/180,c=Math.cos(t),sn=Math.sin(t);
 const dx=Math.max(.005,1.5*Math.hypot(s.radius_rise*c,s.radius_fall*sn)),dy=Math.max(.005,1.5*Math.hypot(s.radius_rise*sn,s.radius_fall*c));
 return [Math.max(0,s.rise-dx),s.rise+dx,Math.max(0,s.fall-dy),s.fall+dy];
}
export function MeasurementPlots({section,grids,fitCounts,channels,edit,m,patch,place,setPlace,reset,ready,headrooms,stalePlots}:{section:string;grids:MeasurementGrid[];fitCounts:Record<string,ShapeFitCount>;headrooms:number[];reset:(kind:string,target:string)=>void;stalePlots:Set<string>}&Omit<FilterProps,'fit'>){
 const phs=section==='PHS',kind=phs?'phs':m.filter_kind;
 return <div className={'m3-measure-grid '+(phs?'m3-phs':'m3-filters')}>{(phs?['start' as const]:roles).flatMap(r=>detectors.map(i=>{
 const id=plotKey(kind,i,r),g=grids.find(x=>x.channel===i&&x.kind===kind&&(phs||x.role===r)),c=channels[i],opt=m.plots[id]??defaults;
 const waiting=stalePlots.has(id);
 const domain:[number,number]=[0,g?.axes[1]??headrooms[i]],total=g?.total??0,window=c[r];
 const count=fitCounts['AB'[i]+'-'+r];
 const showCount=kind==='shape'&&count&&count.first===g?.first&&count.signature===JSON.stringify([window.phs,window.shape]);
 const hist:[number,number][]=[];if(phs&&g?.visible){const cells=new Map(g.cells);for(let x=0;x<g.nx;x++)hist.push([domain[1]*x/g.nx,cells.get(x)??0]);hist.push([domain[1],hist.at(-1)![1]]);}
 const axes:Axes=opt.axes??(kind==='shape'?[0,4,0,8]:[0,headrooms[i],0,4*headrooms[i]]);
 const empty:MeasurementGrid={kind,channel:i,role:r,nx:phs?m.phs_bins[i]:opt.nx,ny:phs?1:opt.ny,axes,cells:[],total:0,visible:0,first:1,windows:[0,0]};
 const title=(phs?'Pulse height':kind==='area'?'Pulse area':'Rise / fall time')+' · '+'AB'[i]+(phs?'':' · '+label(r));
 return <LifetimePlot key={id} activityKey={id} title={title} role={r} points={hist} grid={g??empty} domain={domain} locked histogram={phs} density={!phs} color={i?'#6388c7':'#138d91'}
 kind={kind==='phs'?undefined:kind} gate={phs?undefined:window} onGate={phs?undefined:(gate,preview)=>edit(i,{...c,[r]:gate},preview)} xLabel={kind==='shape'?'Rise 10–90% (ns)':'Pulse height (mV)'} yLabel={phs?'Pulses / bin':kind==='area'?'Pulse area (mV ns)':'Fall 90–10% (ns)'}
 help={phs?'Every measurable CF pulse in this channel, before pairing and quality cuts. The last ADC bin includes excursions above nominal headroom after baseline subtraction. Window counts use the exact measured heights.':('All CF-valid pulses in this channel since its '+(kind==='area'?'area':'rise/fall')+' reset. Both window views share these pulses. The overlay applies to the '+r+' PHS window. '+(kind==='area'?'Choose PHS window for a closer view. Drag the centre line to move it, the end diamond to change its slope, or an edge to change that width.':'Choose Ellipse for a closer view. Drag the centre, either radius handle, or the outline to scale both radii.'))}
 busy={waiting} empty="No measured pulses"
 windows={phs?{channel:c,onEdge:(role,edge,v)=>edit(i,{...c,[role]:{...c[role],phs:{...c[role].phs,[edge]:Math.min(domain[1],v)}}})}:undefined}
 onCenter={place===id?(rise,fall)=>{edit(i,{...c,[r]:{...window,shape:{...window.shape,rise,fall}}});setPlace('');}:undefined}
 tools={<>{kind==='shape'&&<ShapeAxes id={id} option={opt} grid={g} change={v=>patch({...m,plots:{...m.plots,[id]:v}})}/>}
 {!phs&&<button className="m3-diagonal-view" aria-label={'Focus '+(kind==='area'?'PHS window ':'ellipse ')+id} title={kind==='area'?'Centre this view on the PHS interval and its area band. Drag the centre line, slope grip or band edges.':'Centre this view on the ellipse. Drag its centre, either axis handle, or its outline.'} onClick={()=>patch({...m,plots:{...m.plots,[id]:{...opt,axes:focusedAxes(kind as FilterKind,window)}}})}><Crosshair size={13}/>{kind==='area'?'PHS window':'Ellipse'}</button>}
 {kind==='area'&&<button className="m3-diagonal-view" aria-pressed={!!opt.axes} disabled={!opt.axes&&(!g?.diagonal_axes||waiting)} title={opt.axes?'Restore the full measured range':'Keep the full height axis and focus the area axis on the 95th percentile in populated height bands. The view stays fixed until you restore the full range.'}
 onClick={()=>patch({...m,plots:{...m.plots,[id]:{...opt,axes:opt.axes?null:g?.diagonal_axes??null}}})}><ChartNoAxesCombined size={14}/>{opt.axes?'Full range':'Fit to diagonal'}</button>}
 <ResetButton name={(phs?'PHS':kind==='area'?'area':'rise/fall')+' '+'AB'[i]+(phs?'':' · both windows')} disabled={!ready} onClick={()=>reset(kind,'AB'[i])}/></>}
 footer={<>{place===id&&<button className="m3-placement" onClick={()=>setPlace('')}><Crosshair size={13}/>Click the new ellipse centre · Cancel</button>}<span className="m3-pill">{g?total.toLocaleString():ready?'…':'0'} total
 {!!g?.incomplete&&<Help text={g.incomplete.toLocaleString()+' timed pulses have no complete rise/fall measurement. A leading 10–90% crossing can be missing, or the tail can reach the end of the readout before settling to baseline. These pulses count toward the total and have no point on this map. An enabled rise/fall filter rejects them.'}/>}</span>
 {phs?roles.map((w,j)=><span key={w} className={'m3-pill '+w}>{label(w)} · {waiting?'…':(g?.windows[j]??0).toLocaleString()}</span>):<><span className={'m3-pill '+r}>PHS: {window.phs.low}–{window.phs.high} mV</span><span className={'m3-pill '+(window[kind as FilterKind].enabled?'m3-filter-on':'')}>Filter {window[kind as FilterKind].enabled?'enabled':'disabled'}</span>{showCount&&<span className="m3-fit-count" title={count.inside.toLocaleString()+' of '+count.total.toLocaleString()+' complete pulses inside this PHS window at fit time. The density map includes both windows and all other measured heights.'}>At fit · {percent(100*count.inside/count.total)}</span>}<span className="m3-scale" title="Logarithmic pulses per density cell">1 <i/> {Math.max(1,g?.max_cell??0).toLocaleString()}</span></>}
 {!!g?.above_adc&&<span title="Baseline subtraction can place a measured height above nominal ADC headroom. These entries occupy the last displayed bin. Window cuts use their measured heights.">{g.above_adc.toLocaleString()} above ADC span · last bin</span>}{!!g&&g.visible+(g.incomplete??0)<total&&<span title="These measurements are retained and reappear in the full range.">{(total-g.visible-(g.incomplete??0)).toLocaleString()} outside view</span>}</>}/>;
 }))}</div>;
}

