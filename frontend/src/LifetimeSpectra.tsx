// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useContext,useMemo,useState} from 'react';
import {ArrowLeftRight,Layers3,ListRestart,ScanLine} from 'lucide-react';
import {Field,Help} from './Fields';
import {Modal} from './Modal';
import {ResetButton,LiveNumber} from './LifetimeTuning';
import {LifetimePlot} from './LifetimePlot';
import {subtypeKeys,subtypeFor} from './spectrumSubtypes';
import {ContributionGraphic,ContributionSketch,contributionExample,contributionName,traceColors,traceColor,traceLabel} from './ContributionGraphic';
import {SpectrumRange} from './SpectrumRange';
import {SpectrumHover,SpectrumLegend} from './SpectrumLegend';
import {type AnalysisData,type LifetimeChannel,type SpectrumComparison,type SpectrumDirection,type SpectrumDisplay,type SpectrumHistogram} from './m3types';
import {classKeys,chosenClasses,originNames,scatterNames} from './lifetimeEditing';
import {fitTimeRange,superimposedBins,heightDomain,spectrumHelp,spectrumNames,spectrumRoles} from './spectrumAnalysis';

type Patch=(v:Partial<SpectrumDisplay>)=>void;
const fmt=(n:number)=>n.toLocaleString();
const ns=(n:number|null|undefined)=>n==null?'Unrecorded':n.toLocaleString(undefined,{maximumFractionDigits:6})+' ns';
const emptyPoints:[number,number][]=[];
const headings=['Before filters','After filters'];
const spectrumChoices=[
 {key:'total',label:'Total spectrum',scope:'All pairs',help:'All pairs in this direction, independent of the selected class overlays.'},
 {key:'superimposed',label:'Superimposed spectrum',scope:'Selected classes',help:'Sum of the checked classes and subtypes in each bin. A selected parent includes its subtypes once. Light and scattering choices apply.'},
] as const;
const roles:Record<SpectrumDirection,('start'|'stop')[][]>={merged:[['start','stop'],['stop','start']],AB:[['start','stop']],BA:[['stop','start']],SS:[['stop','stop']]};

export function SpectrumSettings({direction,view,patch,delays,comparison}:{direction:SpectrumDirection;view:SpectrumDisplay;patch:Patch;delays:(number|null|undefined)[];comparison?:SpectrumComparison}){
 const fields=[['bin_ps','Bin width · ps'],['zero_ps','Zero shift · ps'],['low_ns','Range from · ns'],['high_ns','Range to · ns']] as const;
 const known=delays.length===2&&delays.every(d=>d!=null);
 return <><section className="m3-settings-section"><div className="m3-analysis-heading"><h3>Spectrum display</h3><span className="m3-pill">{spectrumNames[direction]}</span></div>
 <div className="lifetime-fields">{fields.map(([key,label])=><Field key={key} label={label} help={key==='zero_ps'?'Subtract this offset after cable compensation and direction assignment.':'Time bins and limits apply to both lifetime plots in this tab. The underlying pairs remain available for rebinning.'}><LiveNumber name={label} value={view[key]} min={key==='bin_ps'?1:undefined} max={key==='zero_ps'?1e9:undefined} confirmEdit change={v=>patch({[key]:v})}/></Field>)}</div>
 <div className="m3-range-actions"><button disabled={!comparison?.extent} onClick={()=>comparison?.extent&&patch(fitTimeRange(comparison.extent,view.bin_ps))}><ScanLine size={13}/>Full time range</button></div></section>
 {comparison&&comparison.gated_pairs>0&&comparison.gated_pairs<comparison.stages[0].phs[0].counts&&<span className="m3-pill" title="Each pair retains the gate decisions at acquisition time. Pairs acquired with both optional gates off pass through.">{fmt(comparison.gated_pairs)} of {fmt(comparison.stages[0].phs[0].counts)} pairs had active filters</span>}
 <section className="m3-settings-section"><h3>Pulse-height display</h3><div className="lifetime-fields">{[0,1].map(i=><Field key={i} label={'Channel '+'AB'[i]+' bins'} help="Both pulse-height plots for this channel use the recorded ADC headroom. The final bin includes excursions above that range."><LiveNumber name={'Analysis PHS bins '+'AB'[i]} value={view.phs_bins[i]} min={8} max={2048} step={1} confirmEdit change={v=>{const bins:[number,number]=[...view.phs_bins];bins[i]=v;patch({phs_bins:bins});}}/></Field>)}</div></section>
 <section className="m3-settings-section"><h3>Recorded cable delays <Help text="Each digitized channel includes its Module 2 cable transit time. Module 3 subtracts the corresponding delay from each CF timestamp before forming a time difference. If either delay was omitted from an older stream, the comparison uses the original digitizer CF time difference."/></h3>
 <dl className="m3-source-list">{delays.map((d,i)=><div key={i}><dt>Channel {'AB'[i]}</dt><dd>{ns(d)}</dd></div>)}<div><dt>B − A</dt><dd>{known?ns(delays[1]!-delays[0]!):'—'}</dd></div></dl></section></>;
}

type ContributionProps={
 available:string[];comparison?:SpectrumComparison;view:SpectrumDisplay;patch:Patch;visible:string[];
 toggle:(key:string)=>void;select:(keys:string[])=>void;direction:SpectrumDirection;isotope?:string;
};

function StageCounts({stages,kind,filtered}:{stages?:SpectrumComparison['stages'];kind:string;filtered:boolean}){
 return <div className="m3-class-counts">{headings.slice(0,filtered?2:1).map((heading,index)=>{
  const stage=stages?.[index],count=stage?.classes[kind]??stage?.subclasses?.[kind]??0,total=stage?.phs[0].counts??0;
  return <span key={index} title={heading+' · '+fmt(count)+' of '+fmt(total)+' directional pairs'}><small>{index?'After':'Before'}</small><b>{fmt(count)}</b><em>{total?(100*count/total).toFixed(2)+'%':'—'}</em></span>;
 })}</div>;
}

function Contributions({available,comparison,view,patch,visible,toggle,select,direction,isotope}:ContributionProps){
 const {active}=useContext(SpectrumHover);
 const subtypes=subtypeKeys(isotope,Object.keys(comparison?.stages[0].subclasses??{}));
 return <><header><h3><Layers3 size={15}/>Contributions <Help text="Each pair belongs to one ancestry class. Percentages use all directional pairs in the corresponding Before or After stage, over all time differences since its reset. Light and scattering selections restrict the class numerators. Each pair in a subdivided class has one energy subtype. Its subtypes sum to that class. Total spectrum counts each pair once."/></h3></header>
 <div className="m3-contrib-scroll">
 <div className="m3-spectrum-choices" role="group" aria-label="Spectrum traces">
 {spectrumChoices.map(({key,label,scope,help})=><label key={key} className="m3-total-choice" data-spectrum-trace={key} data-lit={active===key} title={help}>
  <input type="checkbox" aria-label={label} checked={visible.includes(key)} onChange={()=>toggle(key)}/>
  <i aria-hidden="true" style={{background:traceColors[key]}}/><span>{label}</span><small>{scope}</small>
 </label>)}
 </div>
 <div className="m3-contrib-tools"><span>Class overlays</span><button onClick={()=>select(available)}>All</button><button onClick={()=>select([])}>None</button></div>
 {available.map(k=>{const help=contributionExample(k,direction,isotope),on=visible.includes(k);
  const children=subtypes.filter(sub=>subtypeFor(sub)?.parent===k);
  return <div key={k} className="m3-class-row" data-spectrum-trace={k}>
   <div className="m3-class-title" data-lit={active===k}><label><input type="checkbox" aria-label={contributionName(k,isotope)} checked={on} onChange={()=>toggle(k)}/>
    <i style={{background:traceColors[k]}}/><span>{contributionName(k,isotope)}</span></label>
    <Help scrollWithin=".m3-contrib-scroll" text={help.text} ariaLabel={'Explain '+contributionName(k,isotope)}><ContributionSketch kind={k} direction={direction} isotope={isotope}/></Help></div>
   <div className="m3-class-summary"><ContributionGraphic kind={k}/><StageCounts stages={comparison?.stages} kind={k} filtered={!!comparison?.filter_active}/></div>
   {children.length>0&&<div className="m3-subtypes" data-parent={k}><h4>Subtypes <small>Gamma energies (keV)</small></h4>
    {children.map((sub,i)=><div className="m3-subtype" key={sub} data-spectrum-trace={sub} data-lit={active===sub}>
     {subtypeFor(sub)?.facet&&subtypeFor(sub)?.facet!==(i?subtypeFor(children[i-1])?.facet:undefined)&&<h5>{subtypeFor(sub)?.facet}</h5>}
     <div className="m3-class-title"><label><input type="checkbox" checked={visible.includes(sub)} aria-label={contributionName(sub,isotope)} onChange={()=>toggle(sub)}/>
      <i style={{background:traceColor(sub)}}/>{contributionName(sub,isotope)}</label><Help scrollWithin=".m3-contrib-scroll" ariaLabel={'Explain '+contributionName(sub,isotope)} text={contributionExample(sub,direction,isotope).text}><ContributionSketch kind={sub} direction={direction} isotope={isotope}/></Help></div>
     <StageCounts stages={comparison?.stages} kind={sub} filtered={!!comparison?.filter_active}/>
    </div>)}</div>}
  </div>;})}
 <div className="m3-contrib-cuts"><Field label="Light in overlays" help="Restrict the class traces and their percentages to this recorded light origin. Total spectrum includes all light origins."><select value={view.origin} onChange={e=>patch({origin:e.target.value})}>{Object.entries(originNames).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select></Field>
 <Field label="Scattering in overlays" help="Restrict class traces to a recorded scattering history. Percentages still refer to all directional pairs at that stage."><select value={view.scatter} onChange={e=>patch({scatter:e.target.value})}>{Object.entries(scatterNames).map(([key,name])=><option key={key} value={key}>{name}</option>)}</select></Field></div></div></>;
}

function curves(hist:SpectrumHistogram|undefined,low:number,step:number,visible:string[],selected:string[]){
 return visible.map(key=>{
  const bins=key==='superimposed'?(hist?superimposedBins(hist,selected,k=>subtypeFor(k)?.parent):[]):(key==='total'?hist?.bins:hist?.layers[key]??hist?.sublayers?.[key])??[];
  return {key,name:traceLabel(key),color:traceColor(key),dashed:key!=='total'&&key!=='superimposed',
   points:bins.map(([index,count]):[number,number]=>[low+(index+.5)*step,count])};
 });
}

type SpectraProps={data:(AnalysisData&{display:SpectrumDisplay})|null;direction:SpectrumDirection;selectDirection:(d:SpectrumDirection)=>void;view:SpectrumDisplay;patch:Patch;channels:LifetimeChannel[];headrooms:number[];isotope?:string;onReset:()=>void;onResetAll:()=>void;stalePlots:Set<string>};
export function SpectraPlots({data,direction,selectDirection,view,patch,channels,headrooms,isotope,onReset,onResetAll,stalePlots}:SpectraProps){
 const [showClasses,setShowClasses]=useState(false),[phsChannel,setPhsChannel]=useState('A');
 const comparison=data?.comparisons[direction];
 const available=data?.categories??classKeys.filter(c=>c!=='annihilation_pair'||isotope!=='co60');
 const keysForSource=subtypeKeys(isotope,Object.keys(comparison?.stages[0].subclasses??{}));
 const subtypes=(view.subtype_overlays??[]).filter(k=>keysForSource.includes(k));
 const visible=[...(view.show_total===false?[]:['total']),...(view.show_superimposed?['superimposed']:[]),...(view.individual?chosenClasses(view).filter(k=>available.includes(k)):[]),...subtypes];
 const select=(keys:string[])=>patch({categories:keys,category:'all',individual:keys.length>0,...(!keys.length?{subtype_overlays:[]}:{} )});
 const toggle=(key:string)=>{
  if(key==='total')patch({show_total:view.show_total===false});
  else if(key==='superimposed')patch({show_superimposed:!view.show_superimposed});
  else if(keysForSource.includes(key)){
   const saved=view.subtype_overlays??[];
   patch({subtype_overlays:saved.includes(key)?saved.filter(k=>k!==key):[...saved,key]});
  }
  else{const keys=available.filter(k=>k===key?!visible.includes(k):visible.includes(k));patch({categories:keys,category:'all',individual:keys.length>0});}
 };
 const active=comparison?.filter_active??roles[direction].some(pair=>pair.some((role,i)=>channels[i][role].area.enabled||channels[i][role].shape.enabled));
 const adc=data?.adc_heights??headrooms;
 const legend=(expanded:boolean)=><SpectrumLegend source={expanded?'Expanded':'Legend'} available={[...available,...subtypes]} visible={visible} toggle={toggle}/>;
 // The visible histogram keeps its measured bin edges while the replacement is prepared.
 const measured=data?.display??view;
 const plots=['Lifetime','Pulse height A','Pulse height B'].flatMap((title,row)=>{
  const lifetime=row===0,i=row-1,lo=lifetime?measured.low_ns:0,step=lifetime?measured.bin_ps/1000:adc[i]/measured.phs_bins[i];
  const timeLimits:[number,number]=[view.low_ns,view.high_ns];
  const domain:[number,number]=lifetime?(view.time_view??timeLimits):heightDomain(view.phs_views?.[i],channels[i],adc[i]);
  const activityKey=lifetime?'lifetime':'phs-'+'AB'[i],busy=stalePlots.has(activityKey);
  const hist=comparison?.stages.map(s=>lifetime?s.lifetime:s.phs[i]);
  const max=hist?.[0].bins.reduce((largest,[b,n])=>lo+(b+1)*step>=domain[0]&&lo+b*step<=domain[1]?Math.max(largest,n):largest,0);
  return headings.map((heading,col)=>{
   const disabled=col===1&&!active,h=disabled?undefined:hist?.[col],name=title+' · '+heading;
   const outside=lifetime&&comparison?comparison.stages[col].phs[0].counts-comparison.stages[col].lifetime.counts:0;
   const help=lifetime?spectrumHelp[direction]:'Channel '+'AB'[i]+' pulse heights of the same directional pairs over all time differences. Shaded bands show the current Start and Stop windows.';
   return <ComparisonPlot key={row+'-'+col} activityKey={activityKey} hist={h} low={lo} step={step} visible={visible} title={name} help={help+(col?' Each pair retains the area and rise/fall decisions in effect when it was measured.':' CF, clipping policy and Start/Stop height assignments apply before optional area and rise/fall gates.')}
    histogram binWidth={step} circles={lifetime} yMax={max} log={lifetime} domain={domain} locked={disabled||!lifetime}
    timeViewport={lifetime?{limits:timeLimits,change:time_view=>patch({time_view})}:undefined}
    tools={<SpectrumRange title={name} channel={lifetime?undefined:i} adc={adc[i]} domain={domain} view={view} patch={patch}/>}
    xLabel={lifetime?'Time difference (ns)':'Pulse height (mV)'} yLabel={lifetime?'Pairs / bin':'Pulses / bin'} windows={lifetime||disabled?undefined:{channel:channels[i]}}
    disabled={disabled} busy={busy&&!disabled} empty={disabled?'Optional filters off':!visible.length?'No traces selected':lifetime?(comparison?'No pairs in this time range':'No measured pairs'):'No pulse heights'}
    expandedLegend={legend(true)} footer={<><span className={'m3-pill '+(disabled?'':col?'start':'')}>{disabled?'Filters off':fmt(h?.counts??0)+(lifetime?' pairs':' pulses')}</span>{!disabled&&outside>0&&<span>{fmt(outside)} outside time range</span>}</>}/>;
  });
 });
 const list=<Contributions {...{available,comparison,view,patch,visible,toggle,select,direction,isotope}}/>;
 return <div className="m3-analysis"><header className="m3-analysis-bar"><nav className="m3-spectrum-tabs" aria-label="Spectrum direction">{(Object.keys(spectrumNames) as SpectrumDirection[]).map(key=><button key={key} aria-pressed={direction===key} className={direction===key?'active':''} onClick={()=>selectDirection(key)}>{key==='merged'&&<ArrowLeftRight size={13}/>} {spectrumNames[key]}</button>)}</nav>
 <span className="m3-roles-badge" title={spectrumHelp[direction]}>{spectrumRoles[direction]}</span><div className="m3-compact-phs" role="group" aria-label="Pulse-height channel"><span>PHS</span>{['A','B'].map(ch=><button key={ch} aria-label={'Show channel '+ch+' pulse heights'} aria-pressed={phsChannel===ch} onClick={()=>setPhsChannel(ch)}>{ch}</button>)}</div><button className="m3-open-contrib" onClick={()=>setShowClasses(true)}><Layers3 size={13}/>Contributions</button>
 <div className="m3-spectrum-resets"><ResetButton name={spectrumNames[direction]+' comparison'} disabled={!data} onClick={onReset}/><button disabled={!data} onClick={onResetAll}><ListRestart size={14}/>Reset all spectra</button></div></header>
 <div className="m3-comparison-body"><div className="m3-analysis-plots" data-phs={phsChannel}>{plots}</div><aside className="m3-contrib-panel" aria-label="Spectrum contributions">{list}</aside></div>
 {legend(false)}{showClasses&&<Modal title="Spectrum contributions" close={()=>setShowClasses(false)}><div className="m3-contrib-dialog">{list}</div></Modal>}</div>;
}

type ComparisonPlotProps=Omit<React.ComponentProps<typeof LifetimePlot>,'points'|'traces'>&{hist?:SpectrumHistogram;low:number;step:number;visible:string[]};
function ComparisonPlot({hist,low,step,visible,...props}:ComparisonPlotProps){
 const keys=visible.join(',');
 const {active}=useContext(SpectrumHover);
 const preview=active&&!visible.includes(active)?active:null;
 const traces=useMemo(()=>{
  const shown=keys?keys.split(','):[];
  return curves(hist,low,step,preview?[...shown,preview]:shown,shown);
 },[hist,low,step,keys,preview]);
 return <LifetimePlot {...props} traces={traces} points={emptyPoints}/>;
}
