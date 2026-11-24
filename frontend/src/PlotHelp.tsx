// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {Help} from './Fields';
import {PulseClassSketch} from './PulseClassSketch';

export type PlotExplanation={text:string;diagram?:'arrival'|'depth'|'pulse-class'|'energy'|'photons'|'pulse'|'polar'|'azimuth'|'path'|'reflections';pulseClass?:string;isotope?:string};

export function PlotHelp({title,explanation}:{title:string;explanation:PlotExplanation}){
 return <Help text={explanation.text} ariaLabel={`About ${title}`}>
  {explanation.diagram==='pulse-class'?<PulseClassSketch kind={explanation.pulseClass??'single'} isotope={explanation.isotope}/>:explanation.diagram==='arrival'?<div className="arrival-explanation" aria-label="Gamma and secondary transport, light emission, optical transport, then average over photons accepted by quantum efficiency">
   <div className="arrival-stages"><span><b>γ / secondaries</b><small>to energy deposit</small></span><i>→</i><span><b>Light emission</b><small>scintillation / Cherenkov</small></span><i>→</i><span><b>Optical path</b><small>to cathode</small></span></div>
   <div className="arrival-result">QE selection → mean arrival time per event</div>
  </div>:explanation.diagram==='depth'?<svg className="depth-explanation" viewBox="0 0 360 80" role="img" aria-label="Axial depth projects the first gamma interaction onto the crystal axis, measured from the front face">
   <rect x="75" y="10" width="250" height="45" rx="4" fill="#ffffff12" stroke="#a3cfcf"/><text x="75" y="8">Front face</text>
   <path d="M15 25 L102 27 L192 40" stroke="#edd0a2" strokeWidth="2" fill="none"/><circle cx="102" cy="27" r="4" fill="#7cdfc0"/>
   <path d="M102 32 V65 M75 55 V69 M75 64 H102" stroke="#7cdfc0" strokeWidth="1.5" strokeDasharray="3 2"/>
   <text x="112" y="69">Depth along the crystal axis →</text><text x="114" y="24">First interaction</text>
  </svg>:explanation.diagram?<QuantitySketch kind={explanation.diagram}/>:undefined}
 </Help>;
}

function QuantitySketch({kind}:{kind:string}){
 const optical=kind==='path'||kind==='reflections';
 return <svg className="quantity-sketch" viewBox="0 0 360 95" role="img" aria-label={{energy:'Gamma energy deposited in the crystal is distinct from light reaching the cathode',photons:'Quantum efficiency selects some incident photons as photoelectrons',pulse:'Photoelectron responses are summed to form one anode pulse',polar:'Polar angle between the gamma direction and crystal axis',azimuth:'Azimuth measured from world X towards world Y',path:'Reflections lengthen the path from photon creation to the cathode',reflections:'Each optical reflection adds to the event count'}[kind]}>
 {(kind==='energy'||optical)&&<><rect x="74" y="12" width="205" height="52" rx="4"/><path d="M16 38 H103"/><circle cx="103" cy="38" r="4"/><text x="18" y="29">{optical?'light':'gamma'}</text>{optical?<><path className="sketch-accent" d="M103 38 L145 16 L193 60 L238 16 L285 38"/>{kind==='reflections'&&[145,193,238].map((x,i)=><text key={x} x={x-4} y={i===1?54:30}>{i+1}</text>)}</>:<><path className="sketch-accent" d="M103 38 L150 24 L183 55"/><text x="119" y="48">energy deposit</text></>}<path d="M285 12 V65"/><text x="242" y="85">cathode</text><text x="74" y="85">{kind==='energy'?'Not anode energy':kind==='path'?'Total optical distance':'Reflection count'}</text></>}
 {kind==='photons'&&<>{[24,42,60].map(y=><path key={y} d={`M20 ${y} H125`}/>)}<rect x="130" y="10" width="72" height="63" rx="4"/><text x="153" y="46">QE</text>{[24,60].map(y=><g key={y}><path className="sketch-accent" d={`M206 ${y} H315`}/><circle cx="315" cy={y} r="3"/></g>)}<text x="20" y="90">incident photons</text><text x="223" y="90">accepted electrons</text></>}
 {kind==='pulse'&&<><path d="M22 18 V72 H334"/><path className="sketch-accent" d="M25 68 H85 C99 68 100 18 112 18 C135 18 127 68 190 68 H333"/><path d="M170 25 H255 M170 21 V29 M255 21 V29"/><text x="181" y="17">sum responses</text><text x="40" y="92">one event</text><text x="242" y="92">time</text></>}
 {(kind==='polar'||kind==='azimuth')&&<><path d="M95 75 H310 M95 75 V10"/><path className="sketch-accent" d="M95 75 L224 17 M143 75 A48 48 0 0 0 139 55"/><text x="152" y="64">angle</text><text x="228" y="20">gamma</text><text x="242" y="91">{kind==='polar'?'crystal axis':'world +X'}</text><text x="61" y="16">{kind==='polar'?'':'+Y'}</text></>}
 </svg>;
}
