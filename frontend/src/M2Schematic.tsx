// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useId,type CSSProperties} from 'react';
import {Expand} from 'lucide-react';
import {number} from './api';
import {deviceSettings} from './m2types';
import type {AnalogResponse,Component,Digitization,PulseProfile,PulseInput,PulseHeader} from './m2types';

const chainStyles=`
.chain-diagram{font:14px system-ui,sans-serif;fill:#284764}
.chain-diagram .chain-box{fill:#fff;stroke:#d5e2ec;stroke-width:1.2}
.chain-diagram .chain-small{font-size:12px;fill:#758ba2}.chain-diagram .chain-title{font-size:16px;font-weight:500}.chain-diagram .chain-channel{font-size:15px;font-weight:500}
.chain-diagram .chain-wire{fill:none;stroke-width:1.5;marker-end:var(--chain-arrow)}
`;

export function M2Schematic({profile:p,device,inputs,recorded,onExpand}:{onExpand?:()=>void;profile:PulseProfile;device?:Component;inputs?:PulseInput|null;recorded?:{digitization:Digitization;dead:number;responses:AnalogResponse[];maximum?:number[];source:string}}){
 const arrow='chain-arrow-'+useId();
 const d=recorded?.digitization??deviceSettings(device),w=d.samples/d.rate_GSps,dead=recorded?.dead??device?.default_dead_ns??0;
 const responses=recorded?.responses??inputs?.streams[0]?.header.analog_response;
 const fmt=(n:number,u:string)=>`${number(n,3)} ${u}`;
 return <section className="acquisition-schematic">{!recorded&&<header><h2>Acquisition chain</h2><span>{inputs?inputs.isotope==='na22'?'Na-22':'Co-60':'Select two Module 1 streams'}</span>{onExpand&&<button type="button" aria-label="Enlarge acquisition chain" title="Enlarge acquisition chain" onClick={onExpand}><Expand size={14}/></button>}</header>}
 <svg className="chain-diagram" style={{'--chain-arrow':'url(#'+arrow+')'} as CSSProperties} viewBox="0 0 1120 644" role="img" aria-label="Two photomultiplier channels through attenuation and cable delay into a common digitizer, trigger and acquisition window">
 <style>{chainStyles}</style>
 <defs><marker id={arrow} viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse"><path d="M0 0L10 5L0 10" fill="none" stroke="currentColor"/></marker></defs>
 <rect className="chain-box" x="620" y="62" width="466" height="405" rx="12"/>
 {[0,1].map(i=>{const y=80+i*230,r=responses?.[i],c=p.channels[i],color=i?'#7192ce':'#299b99',maximum=recorded?.maximum?.[i]??inputs?.observed_maximum_mV?.[i],attenuated=(maximum??0)*10**(-c.attenuation_dB/20),positive=(r?.polarity==='positive')!==!!c.invert,rail=positive?d.voltage_max_mV-d.baseline_mV:d.baseline_mV-d.voltage_min_mV,fits=rail>0&&attenuated<=rail,statusColor=fits?'#198b70':'#ae6b25',height=Math.min(1.45,attenuated/Math.max(rail,1e-9))*28;return <g key={i} style={{color}}>
  <text className="chain-channel" x="32" y={y-20} fill={color}>Channel {'AB'[i]}</text>
  <rect className="chain-box" x="32" y={y} width="285" height="190" rx="10"/>
  <rect x="48" y={y+18} width="7" height="46" fill={color} opacity=".6"/><rect x="55" y={y+18} width="85" height="46" rx="3" fill="none" stroke={color}/><path d={`M65 ${y+54}l12 -24 12 24 12 -24 12 24 12 -24`} fill="none" stroke={color}/>
  <text x="155" y={y+38}>PMT · M1 response</text><text className="chain-small" x="155" y={y+58}>{r?`${r.polarity} output`:'No stream loaded'}</text>
  <text x="50" y={y+93}>{r?`${fmt(r.hv_V,'V')} · gain ${number(r.gain,0)}`:'Gain and HV from input stream'}</text>
  <text x="50" y={y+119}>{r?`${fmt(r.load_ohm,'Ω effective load')}`:'Effective anode load from M1'}</text>
  <text className="chain-small" x="50" y={y+143}>{r?`Transit ${fmt(r.transit_ns,'ns')} · TTS σ ${fmt(r.tts_sigma_ns*1000,'ps')}`:'Photocathode → charge → anode voltage'}</text>
  <text x="50" y={y+173} className="chain-small">Largest M1 pulse: {maximum===undefined?'—':fmt(maximum,'mV')}</text>
  {maximum!==undefined&&<g aria-label={`Channel ${'AB'[i]} maximum pulse versus ADC range`}>
   <title>Largest isolated M1 pulse after attenuation versus available ADC headroom. Pile-up and noise can still exceed this bound.</title>
   <path d={`M355 ${y+178}H399M355 ${y+150}H399`} stroke="#b7c8d2" strokeDasharray="3 3"/>
   <path d={`M355 ${y+178}H364Q369 ${y+178-height} 373 ${y+178-height}Q380 ${y+178} 393 ${y+178}H399`} stroke={statusColor} fill="none" strokeWidth="2"/>
   <text x="409" y={y+146} className="chain-small">At ADC: {fmt(attenuated,'mV')}</text>
   <text x="409" y={y+166} className="chain-small">Headroom: {fmt(rail,'mV')}</text>
   <text x="409" y={y+186} style={{fill:statusColor}} className="chain-small">{rail<=0?'⚠ Wrong polarity':fits?'✓ Within ADC range':'⚠ Exceeds ADC range'}</text>
  </g>}
  <path className="chain-wire" d={`M317 ${y+72}H355M515 ${y+72}H620`} stroke={color}/>
  <rect className="chain-box" x="355" y={y+35} width="160" height="73" rx="7"/><text x="435" y={y+63} textAnchor="middle">{fmt(c.attenuation_dB,'dB')}</text><text className="chain-small" x="435" y={y+87} textAnchor="middle">× {number(10**(-c.attenuation_dB/20),5)} voltage</text>
  <g aria-label={`Channel ${'AB'[i]} inverter ${c.invert?'on':'off'}`}><rect className="chain-box" x="531" y={y+55} width="54" height="34" rx="5"/><text x="558" y={y+77} textAnchor="middle">{c.invert?'× −1':'× +1'}</text><text className="chain-small" x="558" y={y+47} textAnchor="middle">{c.invert?'Inverter':'Direct'}</text><text className="chain-small" x="435" y={y+124} textAnchor="middle">{positive?'Positive':'Negative'} at ADC</text></g><text className="chain-small" x="560" y={y+115} textAnchor="middle">Cable</text><text className="chain-small" x="560" y={y+135} textAnchor="middle">+{fmt(c.cable_delay_ns,'ns')}</text>
  <circle cx="620" cy={y+72} r="5" fill={color}/><text x="608" y={y+27} textAnchor="end" fill={color}>{'AB'[i]} · {fmt(d.input_impedance_ohm,'Ω')}</text>
 </g>;})}
 
 <text x="646" y="94" className="chain-title">{device?.name??'Digitizer'}</text>
 <text x="646" y="122">{fmt(d.rate_GSps,'GS/s')} · {d.samples} samples · {device?.adc_bits??'—'} bit</text>
 <path d="M645 176H1058M645 395H1058" stroke="#dde7ee"/>
 <text x="646" y="204">Input {fmt(d.voltage_min_mV,'')} … {fmt(d.voltage_max_mV,'mV')}</text>
 <text x="646" y="230">Bandwidth {d.input_bandwidth_MHz?fmt(d.input_bandwidth_MHz,'MHz'):'ideal / unrestricted'}</text>
 <path d="M650 270h27v-23h27v45h27v-14h27v-7h27v-1h60" fill="none" stroke="#5887b9" strokeWidth="2"/>
 <text className="chain-small" x="646" y="316">Δt = {fmt(1/d.rate_GSps,'ns')} · {device?.architecture==='switched_capacitor'?'non-uniform cell coordinates':'uniform coordinates'}</text>
 <text x="646" y="346">Acquisition window {fmt(w,'ns')}</text>
 <text className="chain-small" x="646" y="372">First → last sample {fmt((d.samples-1)/d.rate_GSps,'ns')}</text>
 <text x="646" y="426">Readout / dead time {fmt(dead/1e6,'ms')}</text>
 <text className="chain-small" x="646" y="450">Acquisition ceiling {fmt(1e9/(p.acquisition.trigger_delay_ns+dead),'pairs/s')}</text>
 <path className="chain-wire" d="M855 467V520" stroke="#8198ab"/>
 <rect className="chain-box" x="32" y="520" width="1054" height="101" rx="10"/>
 <text className="chain-title" x="52" y="549">Trigger / DAQ</text><text x="52" y="577">{({either:'A OR B',A:'Channel A',B:'Channel B',coincidence:'A AND B'})[p.acquisition.trigger]}</text>
 <text className="chain-small" x="52" y="603">{p.acquisition.trigger==='coincidence'?`Coincidence ${fmt(p.acquisition.coincidence_ns,'ns')}`:'One accepted crossing opens a window'}</text>
 <text x="340" y="549">Threshold A {fmt(p.channels[0].threshold_mV,'mV')}</text><text x="340" y="577">Threshold B {fmt(p.channels[1].threshold_mV,'mV')}</text><text className="chain-small" x="340" y="603">Magnitudes follow each channel’s polarity</text>
 <text x="655" y="549">Before trigger {fmt(Math.max(0,w-p.acquisition.trigger_delay_ns),'ns')}</text><text x="655" y="577">After trigger {fmt(p.acquisition.trigger_delay_ns,'ns')}</text><text className="chain-small" x="655" y="603">Source {fmt(p.activity_Bq,'Bq')} · {fmt(p.activity_Bq/37000,'µCi')}</text>
 </svg><p>Module 1 supplies the analogue voltage at the effective anode load. Attenuation, acquisition and ADC conversion are applied here; the input impedance is not multiplied into the voltage a second time.</p></section>;
}

export async function recordedChainImage(header:PulseHeader){
 const {renderToStaticMarkup}=await import('react-dom/server');
 const peaks=header.inputs.map(input=>input.completion?.observed_maximum_mV);
 const maximum=peaks.length&&peaks.every(p=>p?.length===2)
  ?[0,1].map(i=>Math.max(...peaks.map(p=>p![i]))):undefined;
 const profile=header.profile;
 const recorded={digitization:profile.digitization,dead:profile.acquisition.dead_ns,
  responses:header.inputs[0]?.header.analog_response??[],maximum,source:header.isotope};
 const markup=renderToStaticMarkup(<M2Schematic profile={profile} device={header.resolved.digitizer} recorded={recorded}/>);
 const svg=new DOMParser().parseFromString(markup,'text/html').querySelector('svg')!;
 return 'data:image/svg+xml;charset=utf-8,'+encodeURIComponent(new XMLSerializer().serializeToString(svg));
}
