// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {PlotData} from './Plot';
import type {Component,RuntimePulseProfile as PulseProfile} from './m2types';
export function digitizerTimingPlots(profile:PulseProfile,device?:Component):PlotData[]{
 const d=profile.digitization,dt=1000/d.rate_GSps,a=device?.cell_alternation_ps??0;
 const width=Math.SQRT2*Math.hypot(d.fixed_jitter_ns,d.aperture_jitter_ns)*1000;
 const means=a?[dt-a,dt+a]:[dt];
 const lo=Math.max(0,Math.min(dt*.9,...means.map(v=>v-5*width))),hi=Math.max(dt*1.1,...means.map(v=>v+5*width));
 const dx=(hi-lo)/500;
 const points:[number,number][]=Array.from({length:501},(_,i)=>{const x=lo+dx*i;return [x,means.reduce((s,m)=>s+(width>0?Math.exp(-.5*((x-m)/width)**2)/(width*Math.sqrt(2*Math.PI)):Math.abs(x-m)<dx/2?1/dx:0),0)/means.length];});
 return [{title:'Cell intervals · generated model',xLabel:'Adjacent sample interval (ps)',yLabel:'Probability density (1/ps)',series:[{name:'Fixed cells + random jitter',color:'#268eab',points}],markers:[{x:dt,label:'Nominal interval'}],explanation:{text:'The curve is calculated from the cell-model values below; no curve or cell table is entered. Area = one.\n- The even/odd offset generates alternating short and long cell intervals. Their centres are nominal interval minus/plus this offset.\n- At run start, Gaussian fixed coordinate offsets are drawn once per physical cell and kept for every acquisition. Random coordinate jitter is drawn afresh for each waveform.\n- Each interval is the difference of two neighbouring coordinates. Its peak width is therefore √[2 × (fixed σ² + random σ²)]. The combined distribution alone does not identify the separate jitter contributions.\n- A finite cell realization fluctuates around this expected density. The cyclic intervals sum exactly to N/fs. The seed and realization are saved in the stream.\n- PMT TTS, voltage noise and whole-channel IRF are separate effects.'}}];
}
