// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {HelpSketch} from './HelpSketch';
import {useEffect,useId,useState} from 'react';
import type {Detector} from './m1types';
import type {Entry} from './types';
import {api,number} from './api';
import {Field,NumberField,Toggle} from './Fields';

export default function PMTOperatingPoint({detector:d,pmt,change,reflectionIssue}:{detector:Detector;pmt?:Entry;reflectionIssue:string;change:(p:Partial<Detector>)=>void}){
 const reflectionNote=useId();
 const [point,setPoint]=useState<Record<string,number>|null>(null),[error,setError]=useState('');
 useEffect(()=>{let stopped=false;const timer=setTimeout(()=>{if(!pmt)return;api<Record<string,number>>('/m1/pmt-response',{method:'POST',body:JSON.stringify({entry:pmt,hv_V:d.pmt_hv_V,load_ohm:d.pmt_load_ohm,polarity:d.pmt_polarity,shape_factor:d.pmt_shape_enabled?d.pmt_shape_factor??1:1})}).then(v=>{if(!stopped){setPoint(v);setError('');}}).catch(e=>{if(!stopped){setPoint(null);setError(e.message);}});},250);return()=>{stopped=true;clearTimeout(timer);};},[pmt,d.pmt_hv_V,d.pmt_load_ohm,d.pmt_polarity,d.pmt_shape_enabled,d.pmt_shape_factor]);
 return <>
  <div className="m2-spec-row pmt-response-badges" aria-label="PMT operating response">
   <span>Gain {point?number(point.gain,0):'—'}</span>
   <span>TTS σ {point?number(point.tts_sigma_ns*1000,1)+' ps':'—'}</span>
   <span>Transit {point?number(point.transit_ns,2)+' ns':'—'}</span>
   {d.pmt_shape_enabled&&point&&<span>Effective order {number(point.order,3)}</span>}
  </div>
  <div className="pmt-reflections">
   <Toggle label="Simulate photocathode reflections" help="Track photons reflected from the active film of this detector. With this option off, photoelectron detection uses the PMT quantum efficiency directly."
     value={!reflectionIssue&&d.pmt_cathode_reflections!==false} disabled={!!reflectionIssue} describedBy={reflectionIssue?reflectionNote:undefined}
     onChange={v=>change({pmt_cathode_reflections:v})}/>
   {reflectionIssue&&<p className="field-note" id={reflectionNote}>{reflectionIssue}</p>}
  </div>
  <div className="pmt-operating-fields"><NumberField label="Operating |HV| · V" help="Magnitude of the PMT high voltage. Gain follows its database curve or documented exponent. Transit and intrinsic response times use the stated inverse-square-root approximation. This changes the anode response, not the Geant4 optical history." value={d.pmt_hv_V??Number(pmt?.properties.gain_hv_V??0)} min={Number(pmt?.properties.hv_min_V??1)} max={Number(pmt?.properties.hv_max_V??10000)} onChange={v=>change({pmt_hv_V:v})}/><div className="m2-spec-row reference-specs"><span>Reference HV {String(pmt?.properties.gain_hv_V??'—')} V</span><span>Operating HV {String(pmt?.properties.hv_min_V??'—')}–{String(pmt?.properties.hv_max_V??'—')} V</span></div><NumberField diagram={<HelpSketch kind="load"/>} label="Effective load · Ω" help="Effective resistive load seen by the anode. Voltage = current × this resistance. If two 50 Ω terminations are in parallel, enter 25 Ω. Module 2 receives this voltage; it does not multiply by the digitizer impedance again." value={d.pmt_load_ohm} min={.01} onChange={v=>change({pmt_load_ohm:v})}/><div className="m2-spec-row reference-specs"><span>Reference load {String(pmt?.properties.reference_load_ohm??'—')} Ω</span></div></div><Field label="Anode pulse polarity" help="Sign of the stored anode current and voltage; the accepted-photoelectron count remains positive."><select value={d.pmt_polarity} onChange={e=>change({pmt_polarity:e.target.value as Detector['pmt_polarity']})}><option value="negative">Negative</option><option value="positive">Positive</option></select></Field><div className="pmt-shape-controls">
 <Toggle label="Adjust anode pulse shape" help="Changes the single-photoelectron pulse shape for this detector. The effective order is the dynode count multiplied by f. The model preserves mean charge and recalibrates to the PMT’s reference 10–90% rise time." value={d.pmt_shape_enabled??false} onChange={v=>change({pmt_shape_enabled:v})}/>
 <NumberField label="Shape factor f" help="At f = 1 the effective order equals the dynode count. Choose f so the effective order lies between 2 and 32. Fractional orders are supported." value={d.pmt_shape_factor??1} min={2/Number(pmt?.properties.dynodes??12)} max={32/Number(pmt?.properties.dynodes??12)} disabled={!d.pmt_shape_enabled} commitOnBlur onChange={v=>change({pmt_shape_factor:v})}/>
 </div>{error&&<p className="inline-error">{error}</p>}</>;
}
