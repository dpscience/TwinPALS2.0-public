// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useMemo,useState} from 'react';
import {Field,NumberField} from './Fields';
import {Plot} from './Plot';
import {deviceSettings} from './m2types';
import type {Component,RuntimePulseProfile} from './m2types';
import {digitizerTimingPlots} from './m2timingModel';
import {SourceLinks} from './MaterialSources';
import type {Entry} from './types';

export default function M2ComponentFields({entry:e,tab,newEntry,editing,change}:{entry:Component;tab:string;editing:boolean;newEntry:boolean;change:(p:Partial<Component>)=>void}){
 const [unit,setUnit]=useState(e.default_dead_ns>=1e6?'ms':e.default_dead_ns>=1000?'µs':'ns'),factor=unit==='ms'?1e6:unit==='µs'?1000:1;
 const uniform=e.architecture==='uniform_adc';
 const refs=(key:string)=><SourceLinks entry={{...e,properties:e,curves:[],provenance:{references:e.references.map(r=>({...r,properties:r.fields}))}} as unknown as Entry} property={key}/>;
 const numeric=(key:keyof Component,label:string,help:string,disabled=false)=><NumberField key={key} label={label} help={help} value={editing?e[key] as number:Number(Number(e[key]).toPrecision(8))} disabled={disabled||!editing} references={refs(key)} onChange={v=>change({[key]:v})}/>;
 const density=useMemo(()=>digitizerTimingPlots({digitization:deviceSettings(e)} as RuntimePulseProfile,e)[0],[e]);
 return <><div className="m2-form-grid"><Field label="Name" help="A single fixed two-channel configuration. Use separate entries for different rates or voltage ranges."><input disabled={!editing} value={e.name} onChange={v=>change({name:v.target.value})}/></Field><Field label="Identifier" help="Unique database reference stored in Module 2 settings."><input value={e.id} disabled={!newEntry||!editing} onChange={v=>change({id:v.target.value})}/></Field></div>
 {tab==='sampling'&&<div className="m2-form-grid">
 {numeric('default_rate','Sampling rate · GS/s','Fixed rate for each of the two simultaneously acquired channels. Window duration = sample count / rate.')}
 {numeric('default_samples','Samples per channel','Fixed record length for this configuration. DRS4 uses 1024 cells.')}
 <Field label="Time axis" help="Uniform: equally spaced sample coordinates. Non-uniform: a fixed cell pattern and optional random coordinate variation. Changing to Uniform clears both variations and the cell alternation." references={refs('architecture')}><select disabled={!editing} value={e.architecture} onChange={v=>change(v.target.value==='uniform_adc'?{architecture:'uniform_adc',default_fixed_jitter_ps:0,default_random_jitter_ps:0,cell_alternation_ps:0}:{architecture:'switched_capacitor'})}><option value="uniform_adc">Uniform</option><option value="switched_capacitor">Non-uniform</option></select></Field>
 {numeric('input_bandwidth_MHz','Input bandwidth · MHz','Single-pole analogue low-pass approximation before sampling and trigger evaluation. Zero disables the filter; it means an ideal model, not unlimited real hardware bandwidth.')}
 {numeric('input_impedance_ohm','Input impedance · Ω','Termination of the digitizer input. Module 1 already stores voltage at the effective anode load, so Module 2 does not multiply voltage by this impedance. Use it to choose the correct effective load in M1; mismatches are reported.')}
 </div>}
 {tab==='voltage'&&<div className="m2-form-grid">
 {numeric('voltage_min_mV','Input minimum · mV','Lower ADC rail. Supports asymmetric ranges, for example 0 to 1000 mV.')}{numeric('voltage_max_mV','Input maximum · mV','Upper ADC rail. Highest representable code is one LSB below this value.')}
 {numeric('adc_bits','ADC resolution · bit','Converter resolution, not ENOB. LSB = (maximum − minimum) / 2^bits.')}
 {numeric('baseline_mV','Baseline · mV','Fixed zero-signal voltage inside the selected input range. No baseline jitter is applied.')}
 {numeric('default_noise_sigma_mV','Voltage noise · mV RMS','Independent Gaussian noise per recorded sample before quantization. Zero is an ideal-noise model; check the reference comment.')}
 </div>}
 {tab==='timing'&&<><section className="cell-timing-model" aria-label="Cell interval model">
 <div className="device-timing-plot"><Plot data={density} preferenceKey={'database.cells.'+e.id}/></div>
 <div className="cell-timing-controls"><h3>Cell interval model</h3><div className="m2-form-grid">
 {numeric('default_fixed_jitter_ps','Fixed aperture pattern · ps RMS','Gaussian coordinate offsets generated once per physical cell at run start and kept for every acquisition. This is separate from the even/odd offset and random jitter. Disabled for Uniform.',uniform)}
 {numeric('default_random_jitter_ps','Random coordinate variation · ps RMS','Independent coordinate displacement for each sample and waveform. Added to the fixed cell pattern; adjacent intervals broaden by √2 times this value. Disabled for Uniform.',uniform)}
 {numeric('cell_alternation_ps','Even/odd interval offset · ps','Alternating short/long cell intervals: their mean values are nominal interval minus/plus this offset. Zero gives a single population. This fixed structure is separate from the two Gaussian jitter values.',uniform)}</div><div className="m2-spec-row"><span>Nominal {Number(1000/e.default_rate).toFixed(2)} ps</span><span>Centres {(1000/e.default_rate-e.cell_alternation_ps).toFixed(2)} / {(1000/e.default_rate+e.cell_alternation_ps).toFixed(2)} ps</span><span>Peak σ {(Math.SQRT2*Math.hypot(e.default_fixed_jitter_ps,e.default_random_jitter_ps)).toFixed(2)} ps</span></div></div></section>
 <section className="acquisition-timing" aria-label="Channel timing and readout"><h3>Channel timing and readout</h3><div className="m2-form-grid">
 {numeric('default_irf_sigma_ps','Channel IRF σ · ps','Independent Gaussian shift of the entire analogue waveform per channel. Pair FWHM = 2.35482 × √2 × σ. Excludes PMT TTS and cell-coordinate variation; it does not broaden the cell interval plot above.')}
 <Field label="Readout dead time" help="Busy interval following the saved acquisition window. Triggers in this interval are ignored. This is specific to the readout configuration; see its source comment." references={refs('default_dead_ns')}><div className="time-unit-input"><input disabled={!editing} type="number" min={0} value={e.default_dead_ns/factor} onChange={v=>change({default_dead_ns:Number(v.target.value)*factor})}/><select title="Dead-time display unit" value={unit} onChange={v=>setUnit(v.target.value)}><option>ns</option><option>µs</option><option>ms</option></select></div></Field>
 </div></section></>}
 </>;
}
