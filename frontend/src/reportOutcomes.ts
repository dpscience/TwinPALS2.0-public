// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {EventOutcomes} from './m1types';

// Embedded verbatim into offline reports; all helpers must stay inside this function.
export function reportOutcomes(container:HTMLElement,outcomes:EventOutcomes,label:string,color:string){
 const node=(tag:string,text='',className='')=>{const e=document.createElement(tag);e.textContent=text;e.className=className;return e;};
 const card=node('section','','outcome-report'),heading=node('h2',label);heading.style.color=color;card.append(heading,node('p',`${outcomes.total.toLocaleString()} processed events. These statistics are independent of plot filters.`));
 const grid=node('div','','outcome-report-grid');card.append(grid);
 const table=(parent:HTMLElement,labels:string[],rows:[string,{count:number;percent:number}[]][])=>{
  const t=document.createElement('table'),head=node('tr');labels.forEach(s=>head.append(node('th',s)));const thead=node('thead');thead.append(head);t.append(thead);
  const body=node('tbody');for(const [title,values] of rows){const row=node('tr');row.append(node('th',title));values.forEach(v=>row.append(node('td',`${v.count.toLocaleString()} (${v.percent.toFixed(2)}%)`)));body.append(row);}t.append(body);parent.append(t);
 };
 const crystals=node('div');crystals.append(node('h3','Crystals'));table(crystals,['Outcome','Events'],[['Interaction',[outcomes.interaction]],['Pass through',[outcomes.transmission]],['Miss',[outcomes.miss]]]);grid.append(crystals);
 const anode=node('div');anode.append(node('h3','Anode'));if(outcomes.pulses)table(anode,['Origin','A','B'],(['none','scintillation','cherenkov','mixed'] as const).map((k,i)=>[['No pulse','Scintillation','Cherenkov','Mixed'][i],['A','B'].map(d=>outcomes.pulses![d as 'A'|'B'][k]) ]));grid.append(anode);
 for(const [level,parent] of [['crystal',crystals],['anode',anode]] as const){const joint=outcomes.joint?.[level];if(joint){const d=document.createElement('details');d.open=true;d.append(node('summary','Detector response A/B'),node('p','Joint response of both detectors. The four groups are exclusive and use all processed events as their denominator, independently of plot filters.'));table(d,['Response','Events'],(['A','B','both','neither'] as const).map(k=>[k==='both'?'A + B':k==='neither'?'Neither':k+' only',[joint[k]]]));parent.append(d);}}
 const births=document.createElement('details');births.append(node('summary','Cherenkov origin'));
 let photons=0;for(const d of ['A','B'] as const){const rows=outcomes.pulses?.[d]?.births??[];if(rows.length){births.append(node('h4','Receiving cathode '+d));for(const b of rows){const line=node('p',`${b.label}: ${b.events.toLocaleString()} (${b.percent.toFixed(2)}%)`);line.title=`${b.material}; ${b.photons.toLocaleString()} accepted Cherenkov photons`;births.append(line);photons+=b.photons;}}}
 if(photons){births.append(node('p','Includes pure Cherenkov and Mixed responses. Events with at least one QE-accepted Cherenkov photon from the named component. Percentages use all processed events. An event can contribute to several components; rows do not add up to 100%.'));anode.append(births);}container.append(card);
}
