// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {Field} from './Fields';

export function ImportWorkers({value,onChange,cpus,automatic,disabled}:{
 value:number;onChange:(workers:number)=>void;cpus:number;automatic:number;disabled:boolean
}){
 return <Field label="CPU workers" help="Choose how many CPU workers can read and validate the selected streams. Auto uses the recommended count for this computer.">
  <select aria-label="Import CPU workers" value={value} disabled={disabled} onChange={e=>onChange(Number(e.target.value))}>
   <option value={0}>Auto · {automatic}</option>
   {Array.from({length:Math.min(256,cpus)},(_,i)=><option key={i+1} value={i+1}>{i+1}</option>)}
  </select>
 </Field>;
}
