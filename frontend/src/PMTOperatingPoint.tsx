// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {HelpSketch} from './HelpSketch';
import {useEffect,useState} from 'react';
import type {Detector} from './m1types';
import type {Entry} from './types';
import {api,number} from './api';
import {Field,NumberField} from './Fields';

export default function PMTOperatingPoint({detector:d,pmt,change}:{detector:Detector;pmt?:Entry;change:(p:Partial<Detector>)=>void}){
 const [point,setPoint]=useState<Record<string,number>|null>(null),[error,setError]=useState('');
 useEffect(()=>{let stopped=false;const timer=setTimeout(()=>{if(!pmt)return;api<Record<string,number>>('/m1/pmt-response',{method:'POST',body:JSON.stringify({entry:pmt,hv_V:d.pmt_hv_V,load_ohm:d.pmt_load_ohm,polarity:d.pmt_polarity})}).then(v=>{if(!stopped){setPoint(v);setError('');}}).catch(e=>{if(!stopped){setPoint(null);setError(e.message);}});},250);return()=>{stopped=true;clearTimeout(timer);};},[pmt,d.pmt_hv_V,d.pmt_load_ohm,d.pmt_polarity]);
 return <><div className="pmt-operating-fields"><NumberField label="Operating |HV| · V" help="Magnitude of the PMT high voltage. Gain follows its database curve or documented exponent. Transit and intrinsic response times use the stated inverse-square-root approximation. This changes the anode response, not the Geant4 optical history." value={d.pmt_hv_V??Number(pmt?.properties.gain_hv_V??0)} min={Number(pmt?.properties.hv_min_V??1)} max={Number(pmt?.properties.hv_max_V??10000)} onChange={v=>change({pmt_hv_V:v})}/><div className="m2-spec-row reference-specs"><span>Reference HV {String(pmt?.properties.gain_hv_V??'—')} V</span><span>Operating HV {String(pmt?.properties.hv_min_V??'—')}–{String(pmt?.properties.hv_max_V??'—')} V</span></div><NumberField diagram={<HelpSketch kind="load"/>} label="Effective load · Ω" help="Effective resistive load seen by the anode. Voltage = current × this resistance. If two 50 Ω terminations are in parallel, enter 25 Ω. Module 2 receives this voltage; it does not multiply by the digitizer impedance again." value={d.pmt_load_ohm} min={.01} onChange={v=>change({pmt_load_ohm:v})}/><div className="m2-spec-row reference-specs"><span>Reference load {String(pmt?.properties.reference_load_ohm??'—')} Ω</span></div></div><Field label="Anode pulse polarity" help="Sign of the stored anode current and voltage; the accepted-photoelectron count remains positive."><select value={d.pmt_polarity} onChange={e=>change({pmt_polarity:e.target.value as Detector['pmt_polarity']})}><option value="negative">Negative</option><option value="positive">Positive</option></select></Field>{point&&<div className="m2-spec-row"><span>Gain {number(point.gain,0)}</span><span>TTS σ {number(point.tts_sigma_ns*1000,1)} ps</span><span>Transit {number(point.transit_ns,2)} ns</span></div>}{error&&<p className="inline-error">{error}</p>}</>;
}
