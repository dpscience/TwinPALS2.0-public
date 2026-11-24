// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type { Curve, SourceProfile } from './types';
import { number } from './api';
export function opticalDisplayPoints(curve:Curve|undefined,axis:'eV'|'nm',probability=false):[number,number][]{
 if(!curve)return [];const hc=1239.8419843320026;return curve.points.map(([x,y])=>{const converted=curve.x_unit!==axis;let value=y;if(probability&&['%','percent'].includes(curve.y_unit))value/=100;if(converted&&!probability&&['1/eV','1/nm'].includes(curve.y_unit))value*=x*x/hc;return [converted?hc/x:x,value] as [number,number];}).sort((a,b)=>a[0]-b[0]);
}
export function DecayDiagram({source}:{source:SourceProfile}){
 const levels=source.decay.levels;const max=Math.max(...levels.map(l=>l.energy_keV),1);const sy=(e:number)=>145-e/max*105;
 return <div className="decay-diagram"><svg viewBox="0 0 360 180" role="img" aria-label={`${source.name} simplified decay diagram`}><defs><marker id="arrow" viewBox="0 0 8 8" refX="6" refY="4" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8" fill="#66d6c5"/></marker></defs><text x="12" y="18" className="nucleus-label">{source.decay.parent}</text><text x="343" y="18" textAnchor="end" className="nucleus-label">{source.decay.daughter}</text>{levels.map((l,i)=><g key={i}><line x1="110" x2="275" y1={sy(l.energy_keV)} y2={sy(l.energy_keV)} stroke="#526173"/><text x="104" y={sy(l.energy_keV)+4} textAnchor="end">{l.spin}</text><text x="284" y={sy(l.energy_keV)+4}>{number(l.energy_keV,1)}</text></g>)}{source.decay.transitions.map((t,i)=>{const x=146+i*49;return <g key={i}><line x1={x} x2={x} y1={sy(t.from_keV)+4} y2={sy(t.to_keV)-5} stroke="#66d6c5" strokeWidth="1.5" markerEnd="url(#arrow)"/><text x={x+6} y={(sy(t.from_keV)+sy(t.to_keV))/2} transform={`rotate(-90 ${x+6} ${(sy(t.from_keV)+sy(t.to_keV))/2})`}>{number(t.energy_keV,1)} keV</text></g>})}<path d="M20 30 L101 48" stroke="#8c99ac" strokeDasharray="3 3" fill="none"/><text x="12" y="65"><title>{source.decay.mode}</title>{source.id==='na22'?'β⁺ / EC':'β⁻'}</text><text x="110" y="171">Simplified nuclear levels · keV</text></svg></div>
}
