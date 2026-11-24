// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {usePreference} from './Preferences';
import {LineSwatch} from './Plot';
import type {PlotData,PlotSeries} from './Plot';
import {roleNames,roleColors} from './Simulation';
import {originSeriesColor} from './previewSelection';
export function useSharedLegend(plots:PlotData[],basis:string,split:boolean,roles:string[]=[]){
 const [views,setViews]=usePreference('plots'),key=`m1.legend.${basis}.${split?'origins':'primaries'}`;
 const hidden=views[key]?.hidden??[];
 const items=new Map<string,{series:PlotSeries;available:boolean}>();
 const origins=split?(basis==='crystal'?['none','scintillation','cherenkov','mixed']:['scintillation','cherenkov','mixed']):[''];
 for(const primary of roles)for(const detector of ['A','B'])for(const origin of origins){
  const name=`${roleNames[primary]?.split(' · ')[1]??primary} · ${detector}${origin?' · '+({none:'No crystal light',scintillation:'Scintillation',cherenkov:'Cherenkov',mixed:'Mixed'}[origin]??origin):''}`;
  items.set(name,{series:{name,color:origin?originSeriesColor(primary,origin):roleColors[primary],dashed:detector==='B',points:[]},available:false});
 }
 for(const plot of plots)for(const series of plot.series){
  const available=!plot.unavailable&&series.points.some(p=>p[1]>0);
  const previous=items.get(series.name);
  items.set(series.name,{series,available:available||!!previous?.available});
 }
 const toggle=(name:string)=>setViews(old=>({...old,[key]:{x:null,y:null,hidden:hidden.includes(name)?hidden.filter(n=>n!==name):[...hidden,name]}}));
 // Four origins fit one row per detector in the four-column analysis footer.
 return {splitRows:Math.max(1,roles.length*2),hidden,items:[...items.values()],toggle};
}
export function SharedLegend({legend}:{legend:ReturnType<typeof useSharedLegend>}){
 return <div className="shared-legend" style={{'--split-rows':legend.splitRows} as React.CSSProperties} role="group" aria-label="Shared plot legend"><div className="shared-legend-items">{legend.items.map(({series:s,available})=><button key={s.name} className={`legend-badge ${legend.hidden.includes(s.name)?'muted':''}`} disabled={!available} aria-pressed={available&&!legend.hidden.includes(s.name)} aria-label={s.name} title={s.name+' — '+(available?'Show or hide this trace in all plots. Expanded plots have independent controls.':'No entries for this trace with the current selection.')} onClick={()=>legend.toggle(s.name)}><LineSwatch color={s.color} dashed={s.dashed}/><span className="legend-full-name">{s.name}</span><span className="legend-short-name">{s.name.replace(' keV (pair)','').replace(' keV','').replace('Scintillation','Scint.').replace('Cherenkov','Cher.').replace('No crystal light','None')}</span></button>)}</div></div>;
}
