// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {number} from './api';
import type {PulseInput} from './m2types';
import {Field} from './Fields';
export function InputStatistics({inputs,shuffle,details=false}:{inputs:PulseInput;shuffle:boolean;details?:boolean}){
 const co=inputs.isotope==='co60',roles=co?['1173','1332']:['1275','511'],bounds=inputs.directional_combinations;
 return <div className="input-statistics">
  {inputs.physics&&<div className="physics-badges" title="Immutable settings recorded by Module 1. All eligible light origins contribute to Module 2 acquisition."><span className="readonly-badge">Cherenkov {inputs.physics.include_cherenkov?"on":"off"}</span><span className="readonly-badge">Minimum crystal energy {number(inputs.physics.minimum_energy_keV)} keV</span></div>}
  {details&&<div className="m2-input-summary">{inputs.streams.map((s,i)=><div key={s.path} title={s.path}>
   <b>{roles[i]} keV{!co&&i===1?' pair':''}</b><span>{number(inputs.counts[i])} transport records</span>
   {inputs.eligible_response_counts?.[i]&&<table title="Energy-eligible anode pulses: scintillation + Cherenkov + mixed, each detector response counted once."><thead><tr><th/><th>A</th><th>B</th></tr></thead><tbody><tr><td>Anode pulses</td>{inputs.eligible_response_counts[i]!.map((n,j)=><td key={j}>{number(n)}</td>)}</tr></tbody></table>}
  </div>)}</div>}
  {bounds&&(co||shuffle)&&<Field label={co?'Matched cascade pairs':'Theoretical directional combinations'} help={co?'Pairs with eligible anode pulses in opposite detectors from the same Co-60 event. Cascades are never combined independently.':'Eligible 1275 anode pulses in one detector × eligible 511 anode pulses in the other. Includes scintillation, Cherenkov and mixed. Directions can overlap; this is not an expected digitizer yield. Trigger thresholds, timing, clipping and dead time still apply.'}>
   <table><thead><tr><th>Direction</th><th>Pulses</th></tr></thead><tbody>{[0,1].map(d=><tr key={d}><td>{roles[0]} {'AB'[d]} / {roles[1]} {'BA'[d]}</td><td>{number(bounds.response[d])}</td></tr>)}</tbody></table>
  </Field>}
 </div>;
}
