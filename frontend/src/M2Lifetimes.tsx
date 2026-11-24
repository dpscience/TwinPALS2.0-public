// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {percent} from './api';
import {Plus,Trash2} from 'lucide-react';
import {Field,Help,NumberField} from './Fields';
import type {Lifetime,PulseProfile} from './m2types';

export default function M2Lifetimes({values,change,prompt}:{values:Lifetime[];change:(v:PulseProfile['lifetimes'])=>void;prompt:boolean}){
 const update=(i:number,v:Partial<Lifetime>)=>change(values.map((c,j)=>i===j?{...c,...v}:c));
 const total=values.reduce((s,c)=>s+c.intensity,0)*100;
 if(prompt)return <><h3>Source timing</h3><p className="info-box">Co-60 emits a 1173 keV and a 1332 keV gamma ray in the same cascade. Module 2 uses their paired transport records with zero added emission delay.</p></>;
 return <><h3>Lifetime components <Help text={'Up to five components\n- Select a sample/source component by its intensity.\n- Discrete: one specific lifetime τ. Distributed: first draw τ from the chosen distribution.\n- Then draw the actual decay delay from an exponential distribution with mean τ. Both 511-keV photons share that delay.\n- A discrete τ = 0 is prompt. Co-60 ignores the lifetime mixture.\n- Distributed lifetimes are normalized over the selected finite range and discretized on a grid.'}/></h3>
 <fieldset className="m2-lifetime-fields">
 {values.map((c,i)=><section className="m2-lifetime-card" key={i}>
  <header><strong>Component {i+1}</strong><button title="Remove this component; adjust the remaining intensities to total 100%" disabled={values.length===1} onClick={()=>change(values.filter((_,j)=>i!==j))}><Trash2 size={13}/></button></header>
  <Field label="Name" help="Label retained in the stream, such as bulk sample or source foil."><input value={c.name} onChange={e=>update(i,{name:e.target.value})}/></Field>
  <div className="two-col">
   <Field label="Origin" help="Descriptive origin of this component; it does not change the distribution."><select value={c.origin} onChange={e=>update(i,{origin:e.target.value as Lifetime['origin']})}><option value="sample">Sample</option><option value="source">Source</option></select></Field>
   <NumberField label="Intensity · %" help="Probability of selecting this component. The total must be 100%." value={c.intensity*100} onChange={v=>update(i,{intensity:v/100})}/>
  </div>
  <Field label="Specific lifetime" help="Choose a single mean lifetime or a distribution of mean lifetimes. This is separate from the final exponential distribution of decay delays."><select value={c.distribution} onChange={e=>update(i,{distribution:e.target.value as Lifetime['distribution']})}><option value="discrete">Discrete</option><option value="gaussian">Gaussian distribution</option><option value="lorentzian">Lorentzian distribution</option><option value="lognormal">Lognormal distribution</option></select></Field>
  <div className="two-col">
   <NumberField label={c.distribution==='lognormal'?'Median τ · ns':'Lifetime τ · ns'} help={c.distribution==='lognormal'?'Median of the untruncated specific-lifetime distribution. Internally ln(τ / 1 ns) is the location parameter.':'Discrete: mean exponential lifetime. Gaussian/Lorentzian: centre of the specific-lifetime distribution before truncation.'} value={c.tau_ns} onChange={v=>update(i,{tau_ns:v})}/>
   {c.distribution!=='discrete'&&<NumberField label={c.distribution==='gaussian'?'Width σ · ns':c.distribution==='lorentzian'?'Width HWHM · ns':'Logarithmic width σ'} help={c.distribution==='lognormal'?'Dimensionless standard deviation of ln(τ / 1 ns). The median is exp(μ); this width is not measured in ns.':c.distribution==='lorentzian'?'Half width at half maximum of the untruncated Lorentzian distribution. Finite limits are necessary because the unbounded positive tail has no finite mean.':'Standard deviation of the untruncated Gaussian distribution. Negative lifetimes are excluded by the selected range.'} value={c.spread} onChange={v=>update(i,{spread:v})}/>}
  </div>
  {c.distribution!=='discrete'&&<details className="m2-lifetime-range"><summary title="Set the finite interval and numerical resolution">Distribution range</summary><div className="two-col">
   <NumberField label="Lower bound · ns" help="Lower support bound, at least zero. Probability outside the bounds is removed and the remainder is normalized." value={c.lower_ns} onChange={v=>update(i,{lower_ns:v})}/>
   <NumberField label="Upper bound · ns" help="Upper support bound. Increasing this can materially change a Lorentzian distribution's mean. The centre must lie inside the range." value={c.upper_ns} onChange={v=>update(i,{upper_ns:v})}/>
  </div><NumberField label="Grid points" help="21–10,001 specific-lifetime grid points. Probability is integrated over each grid cell. Increase until the simulated results are stable; a zero boundary never creates an artificial prompt component." value={c.grid_points} onChange={v=>update(i,{grid_points:v})}/></details>}
 </section>)}
 <div className="m2-inline"><button title="Add a component; at most five including source contributions" disabled={values.length>=5} onClick={()=>change([...values,{name:'Component',origin:'sample',tau_ns:.2,intensity:.01,distribution:'discrete',spread:.02,lower_ns:0,upper_ns:10,grid_points:2001}])}><Plus size={13}/>Add component</button><span className={Math.abs(total-100)>1e-6?'error-text':'muted'}>{values.length}/5 · Total {percent(total)}</span></div>
 </fieldset></>;
}
