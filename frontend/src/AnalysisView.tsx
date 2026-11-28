// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {processingProgress} from './processingProgress';
import {SharedLegend,useSharedLegend} from './SharedLegend';
import {AnalysisBasis,basisHelp} from './AnalysisBasis';
import {OriginSelect,OriginSplit} from './LightOrigin';
import {useEffect} from 'react';
import {PhaseBadge} from './SessionBadges';
import {SessionEmpty} from './SessionEmpty';
import {Field,NumberField} from './Fields';
import {Plot} from './Plot';
import {analysisMetricsFor,makePlot,emptyHistogram} from './analysisModel';

import {roleNames,roleColors} from './Simulation';
import {number} from './api';
import {OutcomePanel} from './OutcomeSummary';
import type {Analysis,AnalysisSelection,EventOutcomes} from './m1types';

type Props={source:{paths?:string[];run_id?:string};revision:number;analyses:Analysis[];selection:AnalysisSelection;plottedSelection:AnalysisSelection;setSelection:(fn:(s:AnalysisSelection)=>AnalysisSelection)=>void;roles:string[];summaryStreams:{role:string;path:string;completed:number;total?:number;expected_events?:number;status?:string;outcomes?:EventOutcomes}[];progress?:number;sessionPhase:string;loading:boolean;error:string;hasSession:boolean;open:()=>void;locked:boolean};
export default function AnalysisView({analyses,selection,plottedSelection,setSelection,roles,summaryStreams,progress,sessionPhase,loading,error,hasSession,open,locked}:Props){
 const plots=analyses.map(a=>makePlot(a,plottedSelection));
 const legend=useSharedLegend(plots,plottedSelection.basis??"anode",!!plottedSelection.split_origin,roles);
 const processing=processingProgress(summaryStreams,plottedSelection.primary);
 useEffect(()=>{if(analyses[0]?.profile?.physics?.include_cherenkov===false&&['cherenkov','mixed'].includes(selection.origin??'all'))setSelection(s=>({...s,origin:'all'}));},[analyses[0]?.profile?.physics?.include_cherenkov,selection.origin,setSelection]);
 return <main className="analysis-layout">
  <div className="analysis-toolbar">
   <AnalysisBasis selection={selection} onChange={setSelection} disabled={!hasSession||!summaryStreams.some(s=>s.completed>0)}/>
   <Field label="Detector" help="Solid traces: A. Dashed traces: B. Colours identify the primary."><select disabled={!hasSession||!summaryStreams.some(s=>s.completed>0)} value={selection.detector} onChange={e=>setSelection(s=>({...s,detector:e.target.value as AnalysisSelection['detector']}))}><option value="all">A + B</option><option>A</option><option>B</option></select></Field>
   <Field label="Primary" help="Gamma energy or photon pair represented by each stream. Co-60 streams separate the two ancestries of the same cascade."><select disabled={!hasSession||!summaryStreams.some(s=>s.completed>0)} value={selection.primary} onChange={e=>setSelection(s=>({...s,primary:e.target.value}))}><option value="all">All primaries</option>{roles.map(r=><option key={r} value={r}>{roleNames[r]??r}</option>)}</select></Field>
   <Field label="Crystal outcome" help="Filter the same detector whose histogram is plotted. Interaction includes gamma interactions or secondary energy deposition; pass through means entry without either; miss means no entry. Independent of anode pulse origin."><select disabled={!hasSession||!summaryStreams.some(s=>s.completed>0)} value={selection.category} onChange={e=>setSelection(s=>({...s,category:e.target.value}))}><option value="all">All events</option><option value="interaction">Interaction</option><option value="transmission">Pass through</option><option value="miss">Miss</option></select></Field>
   {<Field label={selection.basis==='crystal'?'Crystal light origin':'Anode light origin'} help={basisHelp[selection.basis??'anode']}><OriginSelect basis={selection.basis??'anode'} value={selection.origin??'all'} onChange={origin=>setSelection(s=>({...s,origin}))} disabled={selection.split_origin||!hasSession||!summaryStreams.some(s=>s.completed>0)} cherenkov={analyses[0]?.profile?.physics?.include_cherenkov??true}/></Field>}
   <OriginSplit basis={selection.basis??'anode'} value={selection.split_origin??false} disabled={!hasSession||!summaryStreams.some(s=>s.completed>0)} onChange={split_origin=>setSelection(s=>({...s,split_origin,origin:split_origin?'all':s.origin}))}/>
   <NumberField commitOnBlur disabled={!hasSession||!summaryStreams.some(s=>s.completed>0)} label="Bins" help="Equal-width histogram bins. More bins show finer detail with fewer events in each bin." min={10} max={1000} step={1} value={selection.bins} onChange={v=>setSelection(s=>({...s,bins:v}))}/>
   <div className="analysis-status">
    {sessionPhase&&<PhaseBadge label={sessionPhase} progress={progress}/>}
    <div className="primary-counts" aria-label="Events by primary type">{roles.map(role=>{const s=summaryStreams.find(s=>s.role===role);return <section className="primary-count-badge" key={role} title={s?.path}><strong style={{color:roleColors[role]}}>{roleNames[role]??role}</strong><span>{s?number(s.outcomes?.total??s.completed):'—'} events</span></section>;})}</div>
   </div>
  </div>
  {error&&<div className="inline-error" role="alert">{error}</div>}
  <div className={`analysis-content ${hasSession?"has-session":""}`}><div className="analysis-scroll">{!hasSession?<SessionEmpty kind="analysis" open={open} locked={locked}/>:<div className="analysis-grid">{analysisMetricsFor(selection).map((metric,i)=>{
   const reflection=metric==='reflections'||metric==='cathode_reflections';
   const index=analyses.findIndex(a=>a.metric===metric);
   const plot=plots[index]??emptyHistogram(metric,selection);
   return <div className="analysis-cell" key={i}>

   {<Plot sharedHidden={legend.hidden} hideLegend activity={{active:!!sessionPhase&&["Live","Reading"].includes(sessionPhase)||loading||analyses[index]?.loading===true||(analyses[index]?.total_events??0)<processing.processed,processed:analyses[index]?.total_events??0,total:processing.total}} preferenceKey={`analysis.${selection.basis??'anode'}.${i}.${metric}`} busy={loading} suppressZero={{checked:selection.suppress_zero?.includes(metric)??false,onChange:checked=>setSelection(s=>({...s,suppress_zero:checked?[...(s.suppress_zero??[]).filter(m=>m!==metric),metric]:(s.suppress_zero??[]).filter(m=>m!==metric)}))}} data={reflection?{...plot,title:'Optical reflections',xLabel:'Reflections per event'}:plot} titleAdornment={reflection&&<select className="reflection-scope" aria-label="Reflection surface" value={metric} onChange={e=>{const scope=e.currentTarget.value==='cathode_reflections'?'cathode_reflections':'reflections';setSelection(s=>({...s,reflection_scope:scope}));}}><option value="reflections">Crystal / window</option><option value="cathode_reflections">Photocathode</option></select>}/>}
  </div>;})}</div>}{hasSession&&<SharedLegend legend={legend}/>}</div>{hasSession&&<aside className="analysis-outcomes"><OutcomePanel streams={summaryStreams.map(s=>({...s,label:roleNames[s.role]??s.role,color:roleColors[s.role]}))}/></aside>}</div>
 </main>;
}
