// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Illustrative origins; spacing is schematic and is not a lifetime scale.
const examples:Record<string,number[][]>={single:[[0,0,1,0]],true_A_start:[[0,0,1,0],[1,1,1,0]],true_B_start:[[0,1,1,0],[1,0,1,0]],same_primary_1:[[0,0,1,0],[1,0,1,0]],same_primary_2:[[0,1,1,0],[1,1,1,0]],mixed_same_decay:[[0,0,1,0],[0,1,1,1],[1,1,1,0]],accidental:[[0,0,1,0],[1,1,2,1]],pileup:[[0,0,1,0],[0,1,2,1],[1,1,1,0]]};
export function PulseClassSketch({kind,isotope='na22'}:{kind:string;isotope?:string}){
 const energies=isotope==='co60'?['1173','1332']:['1275','511'];
 return <svg className="pulse-class-sketch" viewBox="0 0 300 118" role="img" aria-label={`Schematic ${kind.replaceAll('_',' ')}; A and B are channels; D1 and D2 identify different source decays`}>
 {[0,1].map(ch=><g key={ch}><text x="8" y={39+ch*44} fill="currentColor">{'AB'[ch]}</text><path d={`M30 ${42+ch*44}H287`} fill="none" stroke="currentColor" opacity=".25"/></g>)}
 {(examples[kind]??[]).map(([ch,role,decay,pos],i)=>{const x=80+pos*125,y=42+ch*44,color=role?'#c2a3f5':'#70ddd5';return <g key={i}><path d={`M${x-13} ${y}l8 -24 8 24h22`} stroke={color} strokeWidth="2.4" fill="none"/><text x={x+8} y={y-13} fill={color} fontSize="10">{energies[role]} · D{decay}</text></g>;})}
 <text x="30" y="111" fill="currentColor" opacity=".8" fontSize="9">D1 / D2 = source decay ID · spacing is schematic</text>
 </svg>;
}
