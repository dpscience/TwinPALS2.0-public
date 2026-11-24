// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {basisHelp} from './AnalysisBasis';
export const lightNames:Record<string,string>={none:'No pulse',scintillation:'Scintillation',cherenkov:'Cherenkov',mixed:'Mixed'};

export const lightHelp='Origin of the photons accepted at the photocathode after QE.\n- Scintillation: all accepted photons were produced by scintillation.\n- Cherenkov: all accepted photons were produced by Cherenkov radiation.\n- Mixed: both mechanisms contribute to this detector pulse; it is counted once.\n- No pulse: no accepted photon in this detector.\n\nThis is separate from interaction / pass through / miss in the crystals. The saved minimum-energy selection still applies to plotted detector responses.';

export function OriginSelect({value,onChange,disabled=false,cherenkov=true,basis}:{value:string;onChange:(v:string)=>void;disabled?:boolean;cherenkov?:boolean;basis?:'crystal'|'anode'}){

 return <select title={basis?basisHelp[basis]:lightHelp} aria-label={basis==='crystal'?'Crystal light origin':'Anode pulse origin'} disabled={disabled} value={value} onChange={e=>onChange(e.target.value)}><option value="all">{basis==='crystal'?'All crystal light':'All pulse origins'}</option>{Object.entries(lightNames).filter(([key])=>basis!=='anode'||key!=='none').map(([key,name])=><option key={key} value={key} disabled={!cherenkov&&(key==='cherenkov'||key==='mixed')}>{basis==='crystal'&&key==='none'?'No crystal light':name}</option>)}</select>;

}

export function OriginBadge({kind,children}:{kind:string;children?:React.ReactNode}){return <span className={`light-badge light-${kind}`}>{children??lightNames[kind]}</span>;}



export function WaveOriginBadges({pulses}:{pulses:{channel:number;light_origin:string}[]}){return <span className="wave-origin-badges">{[0,1].map(channel=>{const values=pulses.filter(p=>p.channel===channel).map(p=>p.light_origin),mask=values.reduce((m,v)=>m|({scintillation:1,cherenkov:2,mixed:3}[v]??0),0),kind=['none','scintillation','cherenkov','mixed'][mask];return <span key={channel} title="Optical origin of the M1 pulses contributing to this channel; waveform class is independent"><OriginBadge kind={kind}>{channel===0?'A':'B'} · {lightNames[kind]}</OriginBadge></span>;})}</span>;}


export function OriginSplit({value,onChange,disabled=false,basis}:{basis?:'crystal'|'anode';value:boolean;onChange:(v:boolean)=>void;disabled?:boolean}){return <label className="split-origin" title={(basis==='crystal'?'Group events by light generated in this crystal, independently of detection.':'Group pulse-producing events by the origin of accepted light.')+' Pure scintillation, pure Cherenkov and mixed are separate event groups. A is solid and B dashed.'}><input type="checkbox" disabled={disabled} checked={value} onChange={e=>onChange(e.target.checked)}/>Split by origin</label>;}
