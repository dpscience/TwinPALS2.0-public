// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {FolderOpen} from 'lucide-react';

/** Shared initial state for both simulation/analysis workflows. */
export function SessionEmpty({kind,pulses=false,open,locked=false}:{kind:'simulation'|'analysis';pulses?:boolean;open?:()=>void;locked?:boolean}){
 if(kind==='simulation')return <div className="session-empty">Start a simulation in Setup or open {pulses?'a pulse stream':'streams'} in Analysis.</div>;
 return <div className="analysis-empty"><FolderOpen size={30}/><h2>Open {pulses?'pulse stream':'simulation streams'}</h2><p>{pulses?'Choose a recorded Module 2 pulse stream.':'Choose one stream or a matching pair.'}</p><button title={`Open ${pulses?'a pulse stream':'a stream or a matching pair'} for analysis`} disabled={locked} onClick={open}>Open {pulses?'pulse stream':'streams'}</button></div>;
}
