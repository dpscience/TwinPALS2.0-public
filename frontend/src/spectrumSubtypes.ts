// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

type Row = [line:string, detectorA:string, detectorB:string];
type Subtype = {parent:string;name:string;color:string;description:string;rows:Row[];facet?:string};
const correlated='correlated',shared='same_primary';
const hit='Hit',none='—';
function topology(parent:string,name:string,color:string,description:string,...rows:Row[]):Subtype{
 return {parent,name,color,description,rows};
}
const sodium:Record<string,Subtype>={
 tc1:topology(correlated,'A 1275 / B 511','#177987','Channel A receives the prompt gamma and B receives annihilation light from the same decay. The measured Start and Stop windows are shown independently.',['1275 keV',hit,none],['511 keV',none,hit]),
 tc2:topology(correlated,'A 511 / B 1275','#44689b','Channel B receives the prompt gamma and A receives annihilation light from the same decay. Either channel can pass the Start window.',['1275 keV',none,hit],['511 keV',hit,none]),
 shared511:topology(shared,'Shared 511 keV annihilation photon','#785885','Both selected channel responses carry the same annihilation primary ID from the same record. A separate second 511 keV primary would change the assignment.',['511 keV · one γ',hit,hit]),
 be1275:topology(shared,'Shared 1275 keV prompt photon','#3f789d','The same prompt gamma contributes in both crystals. Both responses have the same original photon ID in the same decay and transport record. The recorded path can identify a backscatter.',['1275 keV · one γ','Same γ','Same γ']),
};
const cobalt:Record<string,Subtype>={
 cascade1173_a:topology(correlated,'A 1173 / B 1332','#187a83','The 1173 keV cascade gamma contributes in A and the 1332 keV gamma in B from the same Co-60 decay. This is a prompt coincidence reference.',['1173 keV',hit,none],['1332 keV',none,hit]),
 cascade1332_a:topology(correlated,'A 1332 / B 1173','#456a9f','The 1332 keV cascade gamma contributes in A and the 1173 keV gamma in B from the same Co-60 decay. The measured pulse heights determine their gate assignments.',['1173 keV',none,hit],['1332 keV',hit,none]),
 shared1173:topology(shared,'Shared 1173 keV cascade photon','#477f95','Both selected channel responses trace to the same primary of the 1173 keV transport record.',['1173 keV · one γ',hit,hit]),
 shared1332:topology(shared,'Shared 1332 keV cascade photon','#786096','Both selected channel responses trace to the same primary of the 1332 keV transport record.',['1332 keV · one γ',hit,hit]),
};
// Energy order is always A then B, including in B → A and Stop–Stop views.
function randomPairs(target:Record<string,Subtype>,lines:[number,number]){
 const colors=['#8d783b','#b1753e','#a65b44','#80604d'];
 for(const [i,a] of lines.entries())for(const [j,b] of lines.entries()){
  target['random_'+a+'_'+b]=topology('accidental','A '+a+' / B '+b,colors[2*i+j],
   'One response in each selected pulse. A receives the '+a+' keV role from one source decay and B receives the '+b+' keV role from a different decay. The measured delay includes the separation of the decay times.',
   ['Decay 1 · '+a+' keV',hit,none],['Decay 2 · '+b+' keV',none,hit]);
 }
}
randomPairs(sodium,[1275,511]);randomPairs(cobalt,[1173,1332]);
const fixed:Record<string,Subtype>={...sodium,...cobalt};
const patterns=['1_1_1_0','1_1_0_1','1_0_1_1','0_1_1_1','1_1_1_1'];
const pileColors=['#ae4d83','#8e5aa9','#92522b','#425f9c','#087f80','#a44f48','#586c37','#65549b'];
function energyList(counts:number[], energies:number[]){
 const terms:string[]=[];
 counts.forEach((n,i)=>{
  if(n===2 && counts[1-i]===0)terms.push(String(energies[i]),String(energies[i]));
  else if(n>0)terms.push((n===1?'':n+'×')+energies[i]);
 });
 return terms.join('+');
}
export function subtypeFor(key:string):Subtype|undefined{
 if(fixed[key])return fixed[key];
 const match=/^(na22|co60)_(same|multi)_(unknown|[0-9]+_[0-9]+_[0-9]+_[0-9]+)$/.exec(key);
 if(!match)return;
 const [,isotope,group,signature]=match, multiple=group==='multi';
 const parent=multiple?'pileup_multiple_decays':'pileup_same_decay';
 if(signature==='unknown')return topology(parent,'Unresolved energy combination','#778892','Pulse overlap and decay membership are established. The stored contributions do not resolve the energy assignment.',['Energy','?','?']);
 const counts=signature.split('_').map(Number),energies=isotope==='na22'?[511,1275]:[1173,1332];
 const a=counts[0]+counts[1]>1,b=counts[2]+counts[3]>1;
 const facet=a&&b?'Pile-up in A and B':a?'Pile-up in A':'Pile-up in B';
 const name='A '+energyList(counts.slice(0,2),energies)+' / B '+energyList(counts.slice(2),energies);
 const rows:Row[]=[];
 let next=1;
 counts.forEach((n,i)=>{
  if(!n)return;
  const decay=!multiple?'D1':n===1?'D'+next:'D'+next+'–D'+(next+n-1);
  const amount=(n===1?'':n+'× ')+energies[i%2]+' keV';
  rows.push([decay+' · '+amount,i<2?hit:none,i>=2?hit:none]);
  next+=n;
 });
 const desc=facet+'. Each term is a recorded response overlapping the selected pulse in its channel. '+(multiple?'At least two decays contribute across the pair. The sketch shows one possible decay assignment.':'Every contribution shown comes from D1.');
 const index=patterns.indexOf(signature);
 const hash=index>=0?index+(multiple?3:0):Array.from(key).reduce((n,c)=>(31*n+c.charCodeAt(0))>>>0,0);
 return {...topology(parent,name,pileColors[hash%pileColors.length],desc,...rows),facet};
}

export function subtypeKeys(isotope?:string,observed:string[]=[]){
 if(isotope!=='na22'&&isotope!=='co60')return [];
 const base=Object.keys(isotope==='na22'?sodium:cobalt);
 const pile=[...new Set([...patterns.map(s=>isotope+'_same_'+s),...observed.filter(k=>k.startsWith(isotope+'_'))])];
 function order(key:string){
  const facet=subtypeFor(key)?.facet;
  const group=facet==='Pile-up in A'?0:facet==='Pile-up in B'?1:facet==='Pile-up in A and B'?2:3;
  const standard=patterns.indexOf(key.split('_').slice(2).join('_'));
  return group*(patterns.length+1)+(standard<0?patterns.length:standard);
 }
 return [...base,...pile.sort((a,b)=>order(a)-order(b)||a.localeCompare(b,undefined,{numeric:true}))];
}
