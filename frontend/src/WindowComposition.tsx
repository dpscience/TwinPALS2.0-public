// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect,useState} from 'react';
import {Plus,Trash2} from 'lucide-react';
import type {Entry} from './types';
import {Field,NumberField} from './Fields';
import {SourceLinks} from './MaterialSources';
import {elements} from './materialModel';
import {compositionText} from './compositionText';
import {api} from './api';

export default function WindowComposition({entry,editable,change,onPending}:{entry:Entry;editable:boolean;change:(entry:Entry)=>void;onPending:(value:boolean)=>void}){
 const p=entry.properties,composition=(p.composition??{}) as Record<string,number>;
 const [formula,setFormula]=useState(String(p.formula??'')),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const [mode,setMode]=useState(p.nist_material?'standard':p.formula?'formula':'elements');
 const [standards,setStandards]=useState<{id:string;density_g_cm3:number;composition:Record<string,number>;composition_basis:string}[]>([]);
 useEffect(()=>{api<{items:typeof standards}>('/materials/standards').then(v=>setStandards(v.items)).catch(e=>setError(e.message));},[]);
 useEffect(()=>{onPending(mode==='formula'&&formula!==String(p.formula??''));return()=>onPending(false);},[mode,formula,p.formula]);
 const props=(v:Record<string,unknown>)=>change({...entry,properties:{...p,...v}});
 const setComposition=(value:Record<string,number>)=>{const next:Record<string,unknown>={...p,composition:value};delete next.formula;delete next.nist_material;change({...entry,properties:next});};
 return <fieldset disabled={!editable||busy} className="material-editor-fields">
  <Field label="Composition input" help="Choose a chemical formula, individual element proportions, or a Geant4 standard material." references={<SourceLinks entry={entry} property="composition"/>}><select value={mode} onChange={e=>{setMode(e.target.value);const next={...p};delete next.nist_material;delete next.formula;if(e.target.value==='standard'){const s=standards.find(s=>s.id==='G4_SILICON_DIOXIDE');if(s)Object.assign(next,{nist_material:s.id,density_g_cm3:s.density_g_cm3,composition:s.composition,composition_basis:s.composition_basis});}change({...entry,properties:next});}}><option value="formula">Chemical formula</option><option value="elements">Element proportions</option><option value="standard">Geant4 standard material</option></select></Field>
  {mode==='standard'?<Field label="Standard material" help="Only names from the Geant4 material catalogue are valid. Density and composition come from that standard."><input list="pmt-glass-standards" value={String(p.nist_material??'')} onChange={e=>{const s=standards.find(s=>s.id===e.target.value);props({nist_material:e.target.value,...s?{density_g_cm3:s.density_g_cm3,composition:s.composition,composition_basis:s.composition_basis}:{}});}}/><datalist id="pmt-glass-standards">{standards.map(s=><option key={s.id} value={s.id}/>)}</datalist></Field>:<>
  <NumberField label="Density · g/cm³" help="Mass density used for particle transport through the entrance glass." min={.000001} value={Number(p.density_g_cm3??0)} references={<SourceLinks entry={entry} property="density_g_cm3"/>} onChange={v=>props({density_g_cm3:v})}/>
  {mode==='formula'?<Field label="Chemical formula" help="Apply the formula before saving the PMT." references={<SourceLinks entry={entry} property="composition"/>}><div className="formula-input"><input value={formula} onChange={e=>setFormula(e.target.value)}/><button title="Replace the element table with this chemical formula" disabled={!formula.trim()||formula===String(p.formula??'')} onClick={async()=>{setBusy(true);setError('');try{const result=await api<{composition:Record<string,number>}>('/materials/formula',{method:'POST',body:JSON.stringify({formula})});const next:Record<string,unknown>={...p,formula,composition:result.composition,composition_basis:'atoms'};delete next.nist_material;change({...entry,properties:next});}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}>Apply formula</button></div></Field>:<>
  <Field label="Proportion convention" help="Atomic proportions count atoms. Mass fractions must sum to 1; update the numbers when changing convention."><select value={String(p.composition_basis??'atoms')} onChange={e=>props({composition_basis:e.target.value})}><option value="atoms">Atomic proportions</option><option value="mass_fraction">Mass fractions</option></select></Field>
  <div className="element-table"><div className="element-table-heading"><span>Element</span><span>Proportion</span><span/></div>{Object.entries(composition).map(([key,value])=><div key={key}><select aria-label={`${key} window element`} value={key} onChange={e=>{const next={...composition};delete next[key];next[e.target.value]=value;setComposition(next);}}>{elements.map(el=><option key={el} disabled={el!==key&&el in composition}>{el}</option>)}</select><input type="number" min="0" step="any" aria-label={`${key} window proportion`} value={value} onChange={e=>setComposition({...composition,[key]:Number(e.target.value)})}/><button title={`Remove ${key}`} onClick={()=>{const next={...composition};delete next[key];setComposition(next);}}><Trash2 size={13}/></button></div>)}</div>
  <div className="element-actions"><button title="Add a chemical element to the glass composition" onClick={()=>{const el=elements.find(e=>!(e in composition));if(el)setComposition({...composition,[el]:1});}}><Plus size={13}/>Add element</button><span>{compositionText(entry)}</span></div>
  </>}</>}
  {error&&<div className="material-error" role="alert">{error}</div>}
 </fieldset>;
}
