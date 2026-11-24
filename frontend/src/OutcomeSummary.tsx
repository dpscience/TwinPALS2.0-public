// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {Help} from './Fields';
import {number,percent} from './api';
import type {EventOutcomes} from './m1types';
import {usePreference} from './Preferences';
import {PhaseBadge} from './SessionBadges';
import {lightNames,lightHelp} from './LightOrigin';

export type AncestryPreview=Record<'crystal'|'anode',{shared_primary:boolean;distinct_primaries:boolean;routes:{detector:string;primary:number;visits:string[];count:number}[]}>;
export const outcomeHelp='All processed events, before plot filters.\n- Interaction: a gamma interaction or energy deposited by its secondary particles in either crystal.\n- Pass through: entry into a crystal by the gamma or its non-optical secondaries, without an interaction or energy deposit.\n- Miss: neither crystal is entered and neither records an interaction or energy deposit.\n\nCounting\n- Each generated event is counted once across both crystals: interaction takes priority, then pass through, then miss.\n- A 511-keV pair is one event. Co-60 statistics are separate for each gamma energy.\n- Percentages use the processed event count of that stream; plot filters do not change these counts.';
export function OutcomeRows({outcomes}:{outcomes:EventOutcomes}){
 return <dl className="outcome-rows">{(['interaction','transmission','miss'] as const).map(key=><div key={key}><dt><i className={`outcome-dot ${key}`}/>{key==='interaction'?'Interaction':key==='transmission'?'Pass through':'Miss'}</dt><dd>{number(outcomes[key].count)}<span>{outcomes.total?percent(outcomes[key].percent):'—'}</span></dd></div>)}</dl>;
}
function AnodeColumns({outcomes}:{outcomes:EventOutcomes}){
 return <table className="anode-columns"><thead><tr><th scope="col">Pulse origin</th><th scope="col">A</th><th scope="col">B</th></tr></thead><tbody>{Object.entries(lightNames).map(([key,name])=><tr key={key}><th scope="row"><span><i className={`outcome-dot light-${key}`}/>{name}</span></th>{(['A','B'] as const).map(d=>{const v=outcomes.pulses?.[d]?.[key];return <td key={d}>{number(v?.count??0)}<small>{outcomes.total?percent(v?.percent??0):'—'}</small></td>;})}</tr>)}</tbody></table>;
}
function CherenkovOrigins({outcomes}:{outcomes:EventOutcomes}){
 const populated=(['A','B'] as const).filter(d=>outcomes.pulses?.[d]?.births.length);
 if(!populated.length)return null;
 return <details className="light-births"><summary>Cherenkov origin <Help ariaLabel="About Cherenkov origin" text="Includes pure Cherenkov and Mixed responses. Each row counts events with at least one QE-accepted Cherenkov photon born in this component and reaching the named cathode. It is an event count, not a photon count. Percentages use all processed events of this primary stream. One event can contribute to several components, so the rows need not add up to 100%."/></summary>{populated.map(d=><div className="birth-detector" key={d}><strong>Reaching cathode {d}</strong>{outcomes.pulses![d].births.map(b=><div key={b.id} title={`${b.material} · ${number(b.photons)} accepted Cherenkov photons`}><span>{b.label}</span><b>{number(b.events)}<small>{percent(b.percent)}</small></b></div>)}</div>)}</details>;
}
function DetectorPattern({outcomes,level,expanded}:{expanded:boolean;outcomes:EventOutcomes;level:'crystal'|'anode'}){
 const joint=outcomes.joint?.[level];if(!joint)return null;
 return <details open={expanded} className="detector-patterns"><summary>Detector response A/B <Help ariaLabel="About detector response A/B" text="Joint response of both detectors, independent of plot filters. A only, B only, both and neither are mutually exclusive and include every processed event once. Crystal view counts crystal interactions; Anode view counts anode pulses. Percentages use all processed events of this primary stream; a 511-keV pair is one event."/></summary><p>{level==='crystal'?'Crystal interaction':'Anode pulse'} · both detectors</p><dl className="outcome-rows">{(['A','B','both','neither'] as const).map(k=><div key={k}><dt><span className="pattern-glyph" aria-hidden="true"><i className={k==='A'||k==='both'?'on':''}/>—<i className={k==='B'||k==='both'?'on':''}/></span>{k==='both'?'A + B':k==='neither'?'Neither':`${k} only`}</dt><dd>{number(joint[k].count)}<span>{outcomes.total?percent(joint[k].percent):'—'}</span></dd></div>)}</dl></details>;
}
export type OutcomeStream={role:string;label:string;color:string;outcomes?:EventOutcomes};
type OutcomeActivity={percent:number;details:string};
export function OutcomePanel({streams,responseOpen=true,activity}:{streams:OutcomeStream[];responseOpen?:boolean;activity?:OutcomeActivity}){
 const [level,setLevel]=usePreference('outcome_level');
 return <><header><strong>Event outcomes</strong>{activity&&<span className="outcome-activity" tabIndex={0} aria-label={activity.details} title={activity.details}><PhaseBadge label="Live" progress={activity.percent}/></span>}<Help text={level==='crystal'?outcomeHelp:lightHelp+'\n\nAll processed events before plot filters. Each detector column uses the full stream event count as its denominator.'}/></header>
 <nav className="light-level" aria-label="Statistics level"><button className={level==='crystal'?'active':''} onClick={()=>setLevel('crystal')} title="Interactions, passages and misses in the crystals">Crystals</button><button className={level==='anode'?'active':''} onClick={()=>setLevel('anode')} title="Anode response in A and B, classified by accepted photon origin">Anode</button></nav>
 <p className="outcome-scope">All processed events · independent of plot filters</p>
 {streams.map(s=>s.outcomes&&<section key={s.role}><strong style={{color:s.color}}>{s.label}</strong>{level==='crystal'?<OutcomeRows outcomes={s.outcomes}/>:<><AnodeColumns outcomes={s.outcomes}/><CherenkovOrigins outcomes={s.outcomes}/></>}<DetectorPattern expanded={responseOpen} key={level} outcomes={s.outcomes} level={level}/></section>)}
 {!streams.some(s=>s.outcomes)&&<p className="empty">Waiting for events…</p>}</>;
}
export function OutcomeOverlay({streams,activity}:{streams:OutcomeStream[];activity?:OutcomeActivity}){
 if(!activity&&!streams.some(s=>s.outcomes))return null;
 return <div className="outcome-overlay"><OutcomePanel streams={streams} responseOpen={false} activity={activity}/></div>;
}
