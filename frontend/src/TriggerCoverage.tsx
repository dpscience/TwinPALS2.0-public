// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {number} from './api';
export function TriggerCoverage({window,delay,coincidence,logic}:{window:number;delay:number;coincidence:number;logic:string}){
 const pre=window-delay,and=logic==='coincidence',risk=and&&pre<coincidence;
 const low=-Math.max(pre,and?coincidence:pre)*1.15,high=Math.max(delay,window*.1),x=(t:number)=>32+(t-low)/(high-low)*376;
 const earlier=and?-coincidence:0;
 return <div className="trigger-coverage">
  <svg viewBox="0 0 440 140" role="img" aria-label="Trigger coverage: saved acquisition window and permitted earlier crossing">
   <rect x={x(-pre)} y="28" width={x(delay)-x(-pre)} height="65" rx="4" fill="#199997" fillOpacity=".12"/>
   {[0,1].map(ch=>{const base=43+ch*32,at=x(and&&ch===0?earlier:0),show=and||logic==='either'||logic==='AB'[ch];return <g key={ch}>
    <text x="8" y={base+3} fill={ch?'#688aca':'#198f8c'}>{'AB'[ch]}</text><path d={`M28 ${base} H414`} stroke="#dce5ed"/>
    {and&&<path d={`M${x(earlier)} ${base} H${x(0)}`} stroke="#a38bc4" strokeWidth="5" opacity=".25"/>}
    {show&&<path d={`M${at-8} ${base} C${at-2} ${base} ${at-2} ${base+4} ${at} ${base+7} L${at+3} ${base+17} C${at+9} ${base+3} ${at+16} ${base} ${at+25} ${base}`} fill="none" stroke={ch?'#688aca':'#198f8c'} strokeWidth="1.5"/>}
   </g>;})}
   <path d={`M${x(0)} 24 V97`} stroke="#52778c" strokeDasharray="3 3"/>
   <text x={x(0)} y="17" textAnchor="middle" fill="#52778c" fontSize="10">{and?'Later crossing · pair accepted':logic==='either'?'A or B crossing':`Channel ${logic} crossing`}</text>
   {and&&<><path d={`M${x(earlier)} 29 V91`} stroke={risk?'#c88442':'#a38bc4'} strokeDasharray="3 3"/><text x={32} y="112" fill={risk?'#99621e':'#7853a6'} fontSize="10">Earlier crossing allowed up to {number(coincidence,2)} ns before acceptance</text></>}
   <text x="32" y="132" fill="#52778c" fontSize="10">Saved: {number(pre,2)} ns before · {number(delay,2)} ns after acceptance</text>
  </svg>
  {risk&&<p className="warning-box" role="note">The earlier AND pulse can fall outside the saved window. {window>=coincidence?`Set common delay to ${number(window-coincidence,2)} ns or less, or reduce coincidence to ${number(pre,2)} ns or less.`:'Use a longer acquisition window or reduce the coincidence interval.'} Allow extra margin for the full pulse.</p>}
 </div>;
}
