// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {Help} from './Fields';

export function MeasurementIllustration({mode='selection',first=true}:{mode?:'selection'|'area'|'fall'|'band'|'ellipse'|'phs';first?:boolean}){
 if(['band','ellipse','phs'].includes(mode))return <svg className="m3-help-wave" viewBox="0 0 204 86" role="img" aria-label={mode+' acceptance diagram'}><path d="M19 7V69H192" fill="none" stroke="#a5b6c4"/>{mode==='band'?<><polygon points="74,53 141,27 141,14 74,40" fill="#cee7df" stroke="#378b80"/><path d="M21 67L186 4" stroke="#496e89" strokeDasharray="3 3"/><path d="M74 70V34M141 70V11" stroke="#83aaa6" strokeDasharray="2 4"/><text x="76" y="82">PHS interval</text></>:mode==='ellipse'?<><ellipse cx="92" cy="43" rx="45" ry="17" transform="rotate(-23 92 43)" fill="#fcdd98"/><ellipse cx="92" cy="43" rx="23" ry="9" transform="rotate(-23 92 43)" fill="#c94b37"/><ellipse cx="92" cy="43" rx="51" ry="22" transform="rotate(-23 92 43)" fill="none" stroke="#517599"/><text x="124" y="78">Rise 10–90%</text><text x="22" y="13">Fall 90–10%</text></>:<><rect x="42" y="20" width="35" height="49" fill="#ede5f5"/><rect x="110" y="20" width="52" height="49" fill="#dbefeb"/><path d="M20 68Q46 63 55 33Q61 17 68 43T94 61Q118 62 135 39T161 58L189 68" fill="none" stroke="#477b9b"/><text x="45" y="16">Stop</text><text x="118" y="16">Start</text></>}</svg>;
 if(mode==='fall'){
  // Mark linear crossings on the same sampled waveform drawn below.
  const points=[[12,68],[26,68],[34,62],[41,33],[47,15],[52,19],[61,45],[70,65],[78,55],[93,22],[104,17],[109,19],[119,37],[128,55],[139,64],[148,68],[154,68],[160,68],[192,68]];
  const baseline=68,height=baseline-15,high=baseline-.9*height,low=baseline-.1*height;
  const down=(y:number)=>points.flatMap(([x,a],i)=>{const next=points[i+1];return next&&a<=y&&next[1]>y?[x+(y-a)*(next[0]-x)/(next[1]-a)]:[];});
  const near=down(low),late90=down(high).at(-1)!,late10=near.at(-1)!;
  return <svg className="m3-help-wave" viewBox="0 0 205 94" role="img" aria-label="A first descent through ten percent enters a valley. The next peak remains connected. Solid dots mark the final falling crossings before three baseline samples.">
   <rect x="12" y="67" width="181" height="2" fill="#b4daca"/><path d={`M28 ${high}H146M28 ${low}H146`} stroke="#ac96b4" strokeDasharray="3 3"/><polyline points={points.map(p=>p.join(',')).join(' ')} fill="none" stroke="#14898a" strokeWidth="2"/>
   <text x="8" y={high-2}>90%</text><text x="8" y={low-3}>10%</text>
   <circle cx={near[0]} cy={low} r="2.5" fill="white" stroke="#897893"/><circle cx={late90} cy={high} r="3" fill="#975386"/><circle cx={late10} cy={low} r="3" fill="#975386"/>
   {[148,154,160].map(x=><circle key={x} cx={x} cy={68} r="2" fill="#397e69"/>)}<path d={`M${late90} 74v4H${late10}v-4`} fill="none" stroke="#975386"/><text x={(late90+late10)/2} y="89" textAnchor="middle">Fall time</text><text x="56" y="81">Valley</text><text x="149" y="81">Settled</text>
  </svg>;
 }
 const d='M12 68H25C33 68 34 40 48 40C57 40 60 68 71 68H88C96 68 98 14 113 14C126 14 133 68 149 68H193';
 return <svg className="m3-help-wave" viewBox="0 0 204 92" role="img" aria-label={mode==='area'?'Area across both pulses in the full readout':first?'Earlier smaller pulse selected':'Later taller pulse selected'}><rect x="12" y="66" width="181" height="4" fill="#d9e9e3"/><path d="M12 68H193" stroke="#83a797" strokeDasharray="3 3"/>{mode==='area'&&<path d={d+'L193 68Z'} fill="#a9d7d1"/>}<path d={d} fill="none" stroke="#14898a" strokeWidth="2.2"/>
 {mode==='selection'?<><circle cx={first?48:113} cy={first?40:14} r="4" fill="#a65685"/><text x={first?17:121} y={first?27:15}>{first?'First peak':'Highest peak'}</text><text x="17" y="85">Time in readout →</text></>:<><path d="M12 75V80H193V75" fill="none" stroke="#517487"/><text x="100" y="90" textAnchor="middle">Full acquisition window</text></>}</svg>;
}

export const timingExplanations = {
  CF: {title: 'CF level', text: 'Measure the first rising crossing of the selected fraction of peak height on the leading flank of the chosen pulse. The level is relative to the measured baseline. The difference between the two channel crossing times enters the assigned lifetime spectrum.'},
  pre_pulse: {title:'Before-pulse reference',text:'The first eight samples (or the chosen length if shorter) provide a provisional reference for peak finding. From the steepest sampled voltage rise on the selected leading lobe, scan backwards to the nearest three samples spanning at most the larger of three noise sigmas and 0.5% of the provisional height. The next sample is the onset. Count back the selected start offset from onset, then take the configured number of raw samples. For example, a start 36 samples before onset and length 32 leaves four samples between the reference window and onset. Its raw median and noise are used to measure that same peak. A missing window rejects the channel.'},
  baseline: {title: 'Baseline and noise', text: 'Readout start uses the first samples. Before pulse takes a full window upstream of the detected onset. Both use the raw median as the voltage reference. Estimate noise as 1.4826 times their median absolute deviation. Show baseline region shades the interval from its first through its last calibrated sample and marks their median voltage. Each channel uses its own time coordinates. Settling on a trailing edge is measured separately.'},
  median: {title: 'Median filter', text: 'Replace each amplitude with the median of its centred, odd-width sample window. At the ends the nearest edge sample is repeated. Measure the height, area and crossings on this filtered trace. Off keeps the original amplitudes.'},
  interpolation: {title: 'Interpolation and intra-steps', text: 'Linear finds the crossing directly on the straight segment between adjacent ADC samples. Cubic and Akima use intra-steps. Natural cubic fits a smooth spline across the calibrated sample times. Akima uses local slopes. In the interval bracketing a level, the selected number of subdivisions refines the estimated crossing on that curve.'},
  height: {title: 'Minimum height', text: 'The selected peak must reach the greater of the configured minimum height and five times the estimated baseline noise. Peak height is the baseline-relative excursion in the recorded pulse direction.'},
  clip: {title: 'ADC clipping', text: 'Module 2 stores one clipping flag per channel and readout. It flags a voltage sample below the lower ADC limit or at or above the upper limit. With this cut enabled, the flagged channel cannot form a lifetime pair. A valid CF crossing still enters the pulse-height and filter plots.'},
} as const;
export type TimingDiagramKind = keyof typeof timingExplanations;

export function TimingDiagram({kind}:{kind:TimingDiagramKind}){
 if(kind==='pre_pulse'||kind==='baseline')return <svg className="m3-help-wave" viewBox="0 0 230 89" role="img" aria-label="Baseline windows at readout start and before the pulse onset, with the start offset measured backwards from onset"><rect x="7" y="40" width="36" height="19" fill="#e1e9f4"/><rect x="76" y="34" width="40" height="21" fill="#cce6dc"/><path d="M6 50L44 50Q67 49 79 44H133Q138 44 146 17Q151 3 158 22T185 45H222" fill="none" stroke="#198a89" strokeWidth="2"/><path d="M134 26V69M76 57v7h58v-7" fill="none" stroke="#9274a0"/><text x="6" y="74">Readout start</text><text x="68" y="28">Before pulse</text><text x="77" y="79">Start offset</text><text x="145" y="60">Onset</text></svg>;
 if(kind==='interpolation')return <svg className="m3-help-wave" viewBox="0 0 190 70" role="img" aria-label="Measured samples, straight segments and a smooth interpolated leading edge with subdivisions"><path d="M15 52L44 50L81 18L117 13L160 42" fill="none" stroke="#7e92a3" strokeDasharray="4 3"/><path d="M15 52C28 52 33 55 44 50C56 45 67 29 81 18C94 8 105 9 117 13C132 18 147 33 160 42" fill="none" stroke="#14898a" strokeWidth="2"/>{[[15,52],[44,50],[81,18],[117,13],[160,42]].map(([x,y])=><circle key={x} cx={x} cy={y} r="2.7" fill="#36576f"/>)}<path d="M44 55v5m9-5v5m9-5v5m10-5v5m9-5v5" stroke="#996e8c"/><text x="39" y="69">Intra-steps</text><text x="103" y="61">● ADC samples</text></svg>;
 if(kind==='median'){
  const raw=[54,54,54,54,31,54,54,51,39,24,18,19,27,39,48,53,54,54,54];
  const smooth=raw.map((v,i)=>[raw[Math.max(0,i-1)],v,raw[Math.min(raw.length-1,i+1)]].sort((a,b)=>a-b)[1]);
  const points=(values:number[])=>values.map((v,i)=>[12+i*9,v].join(',')).join(' ');
  return <svg className="m3-help-wave" viewBox="0 0 194 76" role="img" aria-label="A centred three-sample median suppresses a single spike and retains the broad pulse">
   <rect x="37" y="26" width="23" height="34" fill="#fcf1df"/><polyline points={points(raw)} fill="none" stroke="#ba834a" strokeWidth="1.5" strokeDasharray="3 2"/>
   <polyline points={points(smooth)} fill="none" stroke="#14898a" strokeWidth="2"/><circle cx="48" cy="31" r="2.2" fill="#ba834a"/><circle cx="48" cy="54" r="2.2" fill="#14898a"/>
   <text x="12" y="18">Single-sample spike</text><text x="26" y="70">3 samples</text><text x="114" y="17">Median trace</text>
  </svg>;
 }
 if(kind==='clip')return <svg className="m3-help-wave" viewBox="0 0 194 76" role="img" aria-label="An input peak beyond the ADC range is recorded at the upper rail">
  <path d="M10 59H182" stroke="#a2b7be"/><path d="M12 58H42Q51 58 59 32L66 22Q77 -3 88 22L100 41Q109 58 133 58H178" fill="none" stroke="#b67c39" strokeDasharray="3 3"/>
  <path d="M12 58H42Q51 58 59 32L66 22H88L100 41Q109 58 133 58H178" fill="none" stroke="#14898a" strokeWidth="2"/><path d="M12 22H181" stroke="#b67c39" strokeDasharray="4 3"/>
  <text x="124" y="17">ADC limit</text><text x="93" y="70">Recorded samples</text>
 </svg>;
 const height=kind==='height';
 return <svg className="m3-help-wave" viewBox="0 0 194 77" role="img" aria-label={height?'A small pulse falls below the effective height threshold. A taller pulse clears it.':'The rising edge crosses 25 percent of the peak height. The measured time is projected to the horizontal axis.'}>
  <path d="M10 58H184" stroke="#97abae"/><polyline points={height?'12,58 24,58 33,51 41,58 55,58 65,48 81,18 93,35 109,52 128,58 181,58':'12,58 50,58 60,48 81,18 93,35 109,52 128,58 181,58'} fill="none" stroke="#14898a" strokeWidth="2"/>
  {height?<><path d="M12 39H181" stroke="#bc8140" strokeDasharray="3 3"/><text x="101" y="32">Height threshold</text><circle cx="81" cy="18" r="2.7" fill="#14898a"/><text x="18" y="72">Below threshold</text></>:<><path d="M12 48H181M60 48V63" stroke="#986caa" strokeDasharray="3 3"/><circle cx="60" cy="48" r="3" fill="#975386"/><text x="111" y="43">25% of height</text><text x="45" y="73">CF time</text></>}
 </svg>;
}
const firstLobe = [[5,58],[19,58],[23,57],[26,51],[29,37],[32,30],[35,31],[39,38],[45,45],[53,51],[62,56],[72,58]];
const secondLobe = [[79,58],[85,57],[88,54],[91,45],[94,27],[97,13],[100,9],[104,11],[109,19],[115,30],[123,40],[133,49],[145,55],[156,58],[168,58]];
const exampleTrace = [...firstLobe,...secondLobe].map(point=>point.join(',')).join(' ');

function exampleMarkers(lobe:number[][]){
 const baselineY=lobe[0][1];
 const [peakX,peakY]=lobe.reduce((peak,point)=>point[1]<peak[1]?point:peak);
 const level=baselineY-(baselineY-peakY)*.25;
 const upper=lobe.findIndex(([,y])=>y<=level);
 const [x0,y0]=lobe[upper-1], [x1,y1]=lobe[upper];
 return {peakX,peakY,level,crossing:x0+(level-y0)*(x1-x0)/(y1-y0)};
}
const examplePeaks={first:exampleMarkers(firstLobe),highest:exampleMarkers(secondLobe)};

export function ProcessingPath({selection}:{selection:'first'|'highest'}){
 const first=selection==='first';
 const {peakX,peakY,level,crossing}=examplePeaks[selection];
 return <section className="m3-settings-section m3-processing-path">
  <h3>Pulse measurement <Help ariaLabel="How pulse measurements are calculated" text="The schematic shows two positive, baseline-relative excursions. Each channel is measured in its recorded polarity. Its raw baseline and optional median filter define the measured samples. The selection rule chooses the peak for PHS and timing. Area sums the absolute trapezoids across the complete readout, including other pulses. Timing uses the selected interpolation to locate the CF crossing and the 10–90% rise and 90–10% fall crossings. The purple marker illustrates a 25% leading-edge crossing."/></h3>
  <figure className="m3-measurement-figure">
   <figcaption><span>ADC samples</span><i aria-hidden="true">→</i><span>Baseline correction</span><i aria-hidden="true">→</i><span>Optional median</span><i aria-hidden="true">→</i><span>Interpolation</span><i aria-hidden="true">→</i><span>CF</span></figcaption>
   <div className="m3-measurement-example">
    <div className="m3-example-readout"><svg viewBox="0 0 174 71" role="img" aria-label={first?'First peak selected. Both pulses contribute to the shaded area.':'Highest peak selected. Both pulses contribute to the shaded area.'}>
     <polygon points={exampleTrace} fill="#c5e5e1"/>
     <path d="M5 58H168" stroke="#7f9b9f" strokeDasharray="3 3"/>
     <polyline points={exampleTrace} fill="none" stroke="#277f80" strokeWidth="1.8" strokeLinejoin="round"/>
     <path d={`M${peakX} ${peakY}V58`} stroke="#147e7b" strokeDasharray="2 2"/>
     <path d={`M${crossing} 58V${level}H${peakX}`} fill="none" stroke="#8866a9" strokeDasharray="2.5 2"/>
     <circle cx={peakX} cy={peakY} r="3.4" fill="#157d78" stroke="white" strokeWidth="1.1"/>
     <circle cx={crossing} cy={level} r="2.9" fill="#8762a6" stroke="white" strokeWidth="1"/>
     <path d="M5 62v4h163v-4" fill="none" stroke="#a2b5c0"/>
    </svg><span>Example · 25% CF</span></div>
    <dl className="m3-measurement-key">
     <div><dt><i className="peak"/>Peak height</dt><dd>{first?'First':'Highest'} pulse · PHS</dd></div>
     <div><dt><i className="area"/>Pulse area</dt><dd>Entire readout</dd></div>
     <div><dt><i className="crossing"/>CF, rise & fall</dt><dd>Interpolated crossings</dd></div>
    </dl>
   </div>
  </figure>
 </section>;
}
