// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {percent} from './api';
export type StreamBadge={key:string;label:string;path:string;color?:string};
// Both workbenches use the same markup and stylesheet, including narrow layouts.
export function SessionBadges({origin,streams}:{origin:'Imported'|'Simulation';streams:StreamBadge[]}){
 if(!streams.length)return null;
 return <div className="session-badges" aria-label="Current streams"><span className="session-origin">{origin}</span>{streams.slice(0,2).map(s=><span key={s.key} className="stream-badge" style={{color:s.color??'#198f8c'}} title={`${s.label}\n${s.path}`}><strong>{s.label}</strong><span>{s.path.split(/[\\/]/).at(-1)}</span></span>)}{streams.length>2&&<span className="session-origin" title={streams.slice(2).map(s=>`${s.label}\n${s.path}`).join('\n\n')}>+{streams.length-2}</span>}</div>;
}
export function PhaseBadge({label,progress}:{label:string;progress?:number}){
 return <span className="analysis-phase-badge">{['Live','Reading'].includes(label)&&<span className="spinner"/>}{label}{progress!==undefined&&<strong>{percent(progress)}</strong>}</span>;
}
