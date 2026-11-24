// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {classColors} from './lifetimeEditing';
import {categoryHelp,categoryNames,type SpectrumDirection} from './m3types';
import {spectrumRoles} from './spectrumAnalysis';

import {subtypeFor} from './spectrumSubtypes';

export const traceColors:Record<string,string>={...classColors,total:'#253f59',superimposed:'#007245'};
const short:Record<string,string>={total:'Total spectrum',superimposed:'Superimposed spectrum',correlated:'Correlated γ pair',annihilation_pair:'Two 511 keV photons',same_primary:'Shared γ',accidental:'Accidental background',pileup_same_decay:'Same-decay pile-up',pileup_multiple_decays:'Multi-decay pile-up',unresolved:'Unresolved'};
export function contributionName(key:string,isotope?:string){
 if(key==='correlated' && isotope)return categoryNames[key]+' · '+(isotope==='co60'?'Prompt cascade':'Ideal / intended');
 return subtypeFor(key)?.name??categoryNames[key]??short[key]??key;
}
export function traceColor(key:string){return traceColors[key]??subtypeFor(key)?.color??'#758695';}
export function traceLabel(key:string){
 const sub=subtypeFor(key);
 return sub?short[sub.parent]+' · '+sub.name:short[key]??contributionName(key);
}

export function contributionExample(kind:string,direction:SpectrumDirection,isotope?:string){
 const sodium=isotope==='na22',cobalt=isotope==='co60',start=direction==='BA'?1:0,stop=1-start;
 const energy=sodium?['1275 keV','511 keV']:cobalt?['1173 keV','1332 keV']:['Gamma 1','Gamma 2'];
 const photons=['',''];photons[start]=energy[0];photons[stop]=energy[1];
 let detail='';
 switch(kind){
  case 'correlated':
   detail=sodium?(direction==='SS'?'A prompt and an annihilation gamma from one decay both passed Stop-height windows. Their delay is a Stop–Stop timing reference.':'The intended lifetime assignment is 1275 keV in Start and 511 keV in Stop. Reversed window assignments and scattered paths also qualify for this ancestry class.'):
    cobalt?'The two cascade lines form a prompt coincidence reference. Either line can pass either measured height window.':'Different gamma roles from one recorded decay are present in the selected pair.';
   break;
  case 'annihilation_pair':
   photons[0]='511 keV · γ₁';photons[1]='511 keV · γ₂';
   detail=direction==='SS'?'Both 511 keV primaries from one annihilation passed the two Stop windows. Their time difference is a coincidence reference.':'The two recorded primary IDs distinguish the annihilation photons. One pulse passed the Start-height window.';
   break;
  case 'same_primary':
   photons[0]=energy[0];photons[1]='Same γ, scattered';
   detail='One primary gamma deposited energy in both detectors. The sketch shows A then B. The transport can also run from B to A. The transport record supplies the gamma energy.';
   break;
  case 'accidental':
   detail='The selected A and B pulses come from separate source decays. This is the random-coincidence component of the background.';
   break;
  case 'pileup_same_decay':
   photons[start]=sodium?'1275 + 511 keV':cobalt?'1173 + 1332 keV':'Gamma 1 + 2';
   detail=sodium?'A 1275 keV response can overlap a 511 keV response in A while the partner annihilation photon reaches B. The energy subtypes identify which gamma roles contribute to each pulse. A transport path can give additional scattering evidence.':'For example, two contributions from one cascade overlap the selected pulse in one detector and a scattered gamma also reaches the other detector.';
   break;
  case 'pileup_multiple_decays':
   photons[start]='Overlapping pulses';
   detail='For example, two decays contribute to one selected pulse while the partner channel contains a contribution from the second decay.';
   break;
  default:
   photons[start]='Unknown ancestry';photons[stop]='Recorded pulse';
   detail='For example, one selected pulse has no associated transport record, or the recorded primary IDs are ambiguous.';
 }
 const gates=direction==='BA'?['Stop','Start']:direction==='SS'?['Stop','Stop']:['Start','Stop'];
 const scope=(sodium?'Na-22 · ':cobalt?'Co-60 · ':'')+(direction==='merged'?'Merged includes both directions. The sketch shows A → B.':spectrumRoles[direction]+'.');
 const overlap=kind.startsWith('pileup')?'The digitizer sees the sum. Each simulated contribution extends from its onset through its modeled response tail. Count the responses that overlap the selected lobe. Its end is the first of three consecutive samples within ±max(3 × baseline noise, 0.5% of peak height), or the readout boundary. A second contribution arriving after CF but before baseline recovery still counts. Overlap alone does not establish a shift in CF time.':'';
 const subtype=subtypeFor(kind);
 if(subtype){
  const nested='Included in '+contributionName(subtype.parent)+'.';
  const facet=subtype.parent.startsWith('pileup')?'Energies identify the original gammas. The sum counts contributing responses in that detector.':'';
  return {photons,gates,start,text:[subtype.description,nested,facet,scope].filter(Boolean).join('\n\n')};
 }
 return {photons,gates,start,text:[categoryHelp[kind],overlap,detail,scope].filter(Boolean).join('\n\n')};
}

function PileupWaveform({multiple}:{multiple:boolean}){
 // An illustrative pair of detector responses. The CF dot is calculated on their sum.
 const response=(t:number,onset:number,scale:number)=>t<=onset?0:scale*(1-Math.exp(-(t-onset)/4))*Math.exp(-(t-onset)/17);
 const x=Array.from({length:146},(_,i)=>i),a=x.map(t=>response(t,18,1)),b=x.map(t=>response(t,28,.71)),sum=a.map((v,i)=>v+b[i]);
 const peak=Math.max(...sum),level=.25*peak,index=sum.findIndex(v=>v>=level);
 const time=index-1+(level-sum[index-1])/(sum[index]-sum[index-1]);
 const floor=peak*.005,peakIndex=sum.indexOf(peak);
 const settled=sum.findIndex((v,i)=>i>peakIndex&&v<=floor&&sum[i+1]<=floor&&sum[i+2]<=floor);
 const begin=Math.max(0,sum.findIndex(v=>v>floor)-1),end=settled<0?sum.length-1:settled;
 const px=(i:number)=>14+2*i,py=(v:number)=>67-v*39;
 const path=(ys:number[])=>ys.map((v,i)=>(i?'L':'M')+px(i)+' '+py(v).toFixed(2)).join('');
 return <svg role="img" className="m3-class-sketch" viewBox="0 0 318 115" aria-label="Two overlapping detector responses form one measured pulse with a single CF crossing">
  <rect width="318" height="115" rx="5" fill="#f3f7fa"/><text x="14" y="15" fontSize="10.5" fill="#23465a">Selected pulse · example at 25% CF</text>
  <rect x={px(begin)} y="21" width={px(end)-px(begin)} height="47" fill="#daebee" opacity=".6"/>
  <text x="174" y="32" fontSize="9" fill="#40636d">Selected pulse interval</text>
  <path d="M14 67h290" stroke="#aabcc8"/><path d={path(a)} fill="none" stroke="#138789" strokeWidth="1.8" strokeDasharray="4 2"/>
  <path d={path(b)} fill="none" stroke="#a8587e" strokeWidth="1.8" strokeDasharray="2 2"/><path d={path(sum)} fill="none" stroke="#254563" strokeWidth="2.2"/>
  <path d={'M'+px(time)+' 22V67'} stroke="#657a87" strokeDasharray="2 3"/>
  <circle cx={px(time)} cy={py(level)} r="3" fill="white" stroke="#254563" strokeWidth="1.7"/>
  <g fontSize="9.5" fill="#425f72"><text x="14" y="85" fill="#087a7f">① Record 1 · decay 1</text><text x="145" y="85" fill="#913862">② Record 2 · decay {multiple?'2':'1'}</text>
   <path d="M14 100h14" stroke="#254563" strokeWidth="2"/><text x="33" y="103">Measured sum</text><text x="145" y="103">○ Leading CF crossing</text></g></svg>;
}
export function ContributionSketch({kind,direction,isotope}:{kind:string;direction:SpectrumDirection;isotope?:string}){
 const {photons,gates,start}=contributionExample(kind,direction,isotope);
 const multiple=kind==='accidental'||kind==='pileup_multiple_decays',pile=kind.startsWith('pileup');
 const subtype=subtypeFor(kind);
 if(subtype){
  const rows=subtype.rows,h=38+rows.length*33;
  return <svg className="m3-class-sketch" viewBox={'0 0 318 '+h} role="img" aria-label={subtype.name+' contributions in detectors A and B'}>
   <rect width="318" height={h} rx="5" fill="#f3f7fa"/><text x="12" y="20" fontSize="10.5" fill="#254563">{(subtype.parent==='accidental'||subtype.parent==='pileup_multiple_decays')?(isotope==='co60'?'Co-60 · multiple decays':'Na-22 · multiple decays'):isotope==='co60'?'Co-60 cascade':'Na-22 decay'}</text>
   {gates.map((gate,i)=><text key={i} x={182+84*i} y="20" textAnchor="middle" fontSize="10" fill="#415c71">{'AB'[i]} · {gate}</text>)}
   {rows.map(([line,...hits],i)=><g key={line+hits.join('/')}><text x="12" y={49+33*i} fontSize="11" fill="#36566a">{line}</text>
    {hits.map((hit,ch)=><g key={ch}><rect x={153+84*ch} y={34+33*i} width="58" height="22" rx="5" fill={hit==='—'?'#eaf0f3':ch?'#e0e7f3':'#d9eeec'}/>
     <text x={182+84*ch} y={49+33*i} textAnchor="middle" fontSize="10.5" fill={ch?'#47649a':'#216c70'}>{hit}</text></g>)}</g>)}</svg>;
 }
 const y=[39,76],sourceY=multiple?y:[57],ink=traceColors[kind],unknown=kind==='unresolved';
 const route=(from:number,to:number,offset=0)=>'M37 '+from+' Q68 '+(from+offset)+' 93 '+(to+offset)+' T125 '+to;
 const ends=kind==='same_primary'?['M37 57 Q82 57 125 39','M119 42 Q77 56 119 73']:[
  route(sourceY[0],y[multiple&&pile?start:0]),
  route(multiple?sourceY[1]:sourceY[0],y[multiple&&pile?1-start:1]),
  ...(pile?[route(multiple?sourceY[1]:sourceY[0],y[start],multiple?10:-16)]:[])
 ];
 return <>{pile&&<PileupWaveform multiple={multiple}/>}<svg viewBox="0 0 318 99" className="m3-class-sketch" role="img" aria-label={'Example for '+traceLabel(kind)+' in '+spectrumRoles[direction]}>
  <rect width="318" height="99" rx="5" fill="#f5f8fa"/>
  <g fill="#526f83" fontSize="9.5"><text x="12" y="15">Decay</text><text x="128" y="15">Gamma contribution</text><text x="253" y="15">PHS window</text></g>
  {ends.map((d,i)=><path key={i} d={d} fill="none" stroke={ink} strokeWidth="1.7" strokeDasharray={unknown?'3 3':undefined}/>)}
  {sourceY.map((v,i)=><g key={i}><circle cx="30" cy={v} r="9" stroke={ink} fill="white"/><text x="30" y={v+3.5} textAnchor="middle" fill={ink} fontSize="10">{unknown?'?':i+1}</text></g>)}
  {y.map((v,i)=><g key={i}><circle cx="123" cy={v} r="3" fill={ink}/><text x="132" y={v+4} fontSize="10.5" fill="#29475a">{photons[i]}</text><rect x="249" y={v-10} width="60" height="20" rx="7" fill={i?'#e9eef8':'#deefed'}/><text textAnchor="middle" x="279" y={v+4} fontSize="10.5" fill={i?'#46679c':'#176e6e'}>{'AB'[i]} · {gates[i]}</text></g>)}
 </svg></>;
}

const routes:Record<string,string[]>={
 correlated:['M10 16 L40 6','M10 16 L40 26'],
 annihilation_pair:['M24 16 L40 6','M24 16 L8 26'],
 same_primary:['M8 16 L34 6 L41 26'],
 accidental:['M10 7 L40 6','M10 25 L40 26'],
 pileup_same_decay:['M9 15 L40 6','M9 15 Q20 2 40 6','M9 15 L40 26'],
 pileup_multiple_decays:['M9 7 L40 6','M9 25 Q25 19 40 6','M9 25 L40 26']
};
export function ContributionGraphic({kind}:{kind:string}){
 const multiple=kind==='accidental'||kind==='pileup_multiple_decays';
 const sources:number[][]=multiple?[[9,7],[9,25]]:kind==='annihilation_pair'?[[24,16]]:[[9,16]];
 const ends=kind==='annihilation_pair'?[[40,6],[8,26]]:kind==='same_primary'?[[34,6],[41,26]]:[[40,6],[40,26]];
 return <svg className="m3-contribution-icon" viewBox="0 0 50 32" aria-hidden="true" style={{color:classColors[kind]}}>
 {kind==='unresolved'?<><path d="M9 16H21M29 16L40 6M29 16L40 26" fill="none" stroke="currentColor" strokeDasharray="2 3"/><text x="25" y="20" textAnchor="middle" fill="currentColor">?</text></>:
 routes[kind]?.map((d,i)=><path key={i} d={d} stroke="currentColor" strokeWidth="1.65" fill="none" strokeLinecap="round"/>)}
 {sources.map(([x,y])=><circle key={y} cx={x} cy={y} r="3.4" stroke="currentColor" strokeWidth="1.4" fill="white"/>)}
 {ends.map(([x,y],i)=><rect key={i} x={x-2.4} y={y-3.4} width="5" height="7" rx="1.3" fill={i?'#6985bd':'#208b88'}/>)}</svg>;
}
