// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useMemo,useState} from 'react';
import {FolderOpen,Plus,Trash2,Upload} from 'lucide-react';
import type {Curve,Entry} from './types';
import {Field,NumberField} from './Fields';
import {Plot} from './Plot';
import {Modal} from './Modal';
import {parseCurve,curveText,curveMetadata,detectCurveImport} from './curveText';
import type {CurveImportOptions} from './curveText';
import {usePreference} from './Preferences';
import {api} from './api';
import {curveLabel} from './materialModel';
import {SourceLinks} from './MaterialSources';

export function curveProblem(curve:Curve):string{
 if(!(curve.name==='gain_hv'?['V']:['nm','eV']).includes(curve.x_unit))return 'Use wavelength in nm or photon energy in eV.';
 if(curve.name.startsWith('emission')&&['1/nm','1/eV'].includes(curve.y_unit)&&curve.y_unit!=='1/'+curve.x_unit)return 'The spectrum density unit must match the horizontal axis.';
 if(curve.points.length<2||curve.points.length>20000)return 'Use between 2 and 20,000 points.';
 if(curve.points.some(([x,y])=>!Number.isFinite(x)||!Number.isFinite(y)||x<=0))return 'Every wavelength or energy must be positive; all values must be finite numbers.';
 if(new Set(curve.points.map(p=>p[0])).size!==curve.points.length)return 'Each wavelength or energy must occur only once.';
 if(['refractive_index','absorption_length','gain_hv'].includes(curve.name)&&curve.points.some(p=>p[1]<=0))return 'Refractive index and absorption length must be greater than zero.';
 if(['reflectivity','quantum_efficiency'].includes(curve.name)&&curve.points.some(p=>p[1]<0||p[1]>(curve.y_unit==='%'?100:1)))return `Probabilities must lie between 0 and ${curve.y_unit==='%'?100:1}.`;
 if(curve.name.startsWith('emission')&&(curve.points.some(p=>p[1]<0)||!curve.points.some(p=>p[1]>0)))return 'Emission values must be nonnegative and contain a nonzero spectrum.';
 return '';
}
function curveData(curve:Curve,name:string){return {title:curveLabel(curve.name),xLabel:curve.x_unit==='V'?'|HV| (V)':curve.x_unit==='nm'?'Wavelength (nm)':'Photon energy (eV)',yLabel:curve.y_unit,numericTable:(kind:'csv'|'txt')=>curveText(curve,kind),series:[{name,color:'#167c80',points:[...curve.points].sort((a,b)=>a[0]-b[0])}]};}

function CurveImport({curve,browse,apply,close}:{curve:Curve;browse:(kind:string,initial?:string)=>Promise<string|null>;apply:(value:Curve)=>void;close:()=>void}){
 const [options,setOptions]=usePreference('curve_import'),[path,setPath]=useState(''),[text,setText]=useState(''),[loadedPath,setLoadedPath]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
 const units=curveMetadata(text),importCurve={...curve,...units};
 const preview=useMemo(()=>{if(!text)return {points:[] as [number,number][],error:''};try{const points=parseCurve(text,options).sort((a,b)=>a[0]-b[0]);return {points,error:curveProblem({...curve,...curveMetadata(text),points})};}catch(e){return {points:[],error:(e as Error).message};}},[text,options,curve]);
 const read=async(value=path)=>{setBusy(true);setError('');setText('');setLoadedPath('');try{const data=await api<{text:string}>('/files/text',{method:'POST',body:JSON.stringify({path:value})});setOptions(detectCurveImport(data.text));setText(data.text);setLoadedPath(value);}catch(e){setError((e as Error).message);}finally{setBusy(false);}};
 return <Modal title={`Import ${curveLabel(curve.name).toLowerCase()}`} close={close} busy={busy} error={error||preview.error} wide>
  <Field label="CSV / TXT file" help="Read a numeric table, check its columns and units, then apply the preview to this curve."><div className="path-control"><input value={path} disabled={busy} onChange={e=>{setPath(e.target.value);setError('');}}/><button disabled={busy} title="Choose a CSV or TXT curve table" aria-label="Choose curve table" onClick={async()=>{setBusy(true);try{const value=await browse('open_table',path);if(value){setPath(value);await read(value);}}catch(e){setError((e as Error).message);}finally{setBusy(false);}}}><FolderOpen size={15}/></button><button title="Read this file and preview its columns before applying" disabled={busy||!path.trim()} onClick={()=>void read()}>{busy?'Reading…':'Read file'}</button></div></Field>
  <div className="curve-import-options"><Field label="Column separator" help="Automatic detects semicolons, tabs, commas or spaces."><select value={options.delimiter} onChange={e=>setOptions(o=>({...o,delimiter:e.target.value as CurveImportOptions['delimiter']}))}>{['auto','comma','semicolon','tab','space'].map(v=><option key={v}>{v}</option>)}</select></Field><NumberField label="X column" help="Column numbers start at 1." min={1} step={1} value={options.xColumn} onChange={v=>setOptions(o=>({...o,xColumn:v}))}/><NumberField label="Y column" help="Choose a different column from X." min={1} step={1} value={options.yColumn} onChange={v=>setOptions(o=>({...o,yColumn:v}))}/></div>
  <div className="table-import-toggles"><label><input type="checkbox" checked={options.decimalComma} onChange={e=>setOptions(o=>({...o,decimalComma:e.target.checked}))}/>Decimal comma</label><label><input type="checkbox" checked={options.header} onChange={e=>setOptions(o=>({...o,header:e.target.checked}))}/>First row contains headings</label></div>
  <div className="curve-import-preview">{preview.points.length&&!preview.error?<><Plot data={curveData({...importCurve,points:preview.points},'Import preview')}/><div className="import-table-preview"><table><thead><tr><th>X · {importCurve.x_unit}</th><th>Y · {importCurve.y_unit}</th></tr></thead><tbody>{preview.points.slice(0,10).map(([x,y],i)=><tr key={i}><td>{x}</td><td>{y}</td></tr>)}</tbody></table><p>{preview.points.length.toLocaleString()} points · first {Math.min(10,preview.points.length)} shown</p></div></>:<p className="field-note">Choose a table to preview its data.</p>}</div>
  <div className="dialog-actions"><button disabled={busy} onClick={close}>Cancel</button><button className="primary" disabled={busy||!!preview.error||preview.points.length<2||path!==loadedPath} onClick={()=>apply({...importCurve,points:preview.points})}>Apply table</button></div>
 </Modal>;
}

export function MaterialCurveEditor({entry,curve,editable,change,browse}:{entry:Entry;curve:Curve;editable:boolean;change:(curve:Curve)=>void;browse:(kind:string,initial?:string)=>Promise<string|null>}){
 const [page,setPage]=useState(0),[importing,setImporting]=useState(false);
 const currentPage=Math.min(page,Math.max(0,Math.ceil(curve.points.length/30)-1)),start=currentPage*30;
 const issue=curveProblem(curve);
 const update=(patch:Partial<Curve>)=>change({...curve,...patch});
 return <>
  <div className="curve-units"><Field label="Horizontal unit" help="The units of the entered X values."><select disabled={!editable} value={curve.x_unit} onChange={e=>update({x_unit:e.target.value})}><>{curve.name==='gain_hv'?<option value="V">Voltage magnitude · V</option>:<><option value="nm">Wavelength · nm</option><option value="eV">Photon energy · eV</option></>}</></select></Field><Field label="Vertical unit" help={curve.name.startsWith('emission')?'Spectrum density or relative photon weights. Light yield is entered separately.':'Physical unit of each Y value. Quantum efficiency remains an absolute probability.'}><select disabled={!editable} value={curve.y_unit} onChange={e=>update({y_unit:e.target.value})}>{(curve.name==='absorption_length'?['mm','cm','m','um','nm']:curve.name.startsWith('emission')?['relative','1/nm','1/eV','1']:['quantum_efficiency','reflectivity'].includes(curve.name)?['1','%']:['1']).map(v=><option key={v}>{v}</option>)}</select></Field><span>{curve.points.length.toLocaleString()} points</span></div>
  <div className="curve-workbench"><div className="curve-chart"><Plot preferenceKey={`material.${entry.id}.${curve.name}.${curve.x_unit}.${curve.y_unit}`} data={curveData(curve,entry.name)} titleAdornment={<SourceLinks entry={entry} property={curve.name}/>}/></div><div className="curve-points-panel"><div className="curve-actions"><strong>Points</strong><button disabled={!editable} title="Preview and import a CSV or TXT table into this curve" onClick={()=>setImporting(true)}><Upload size={13}/>Import</button><button title="Append an editable point after the last wavelength or energy" disabled={!editable||curve.points.length>=20000} onClick={()=>{update({points:[...curve.points,[Math.max(0,...curve.points.map(p=>p[0]))+1,curve.points.at(-1)?.[1]??0]]});setPage(Math.floor(curve.points.length/30));}}><Plus size={13}/>Add point</button></div>
   <div className="curve-table"><table><thead><tr><th>X · {curve.x_unit}</th><th>Y · {curve.y_unit}</th>{editable&&<th/>}</tr></thead><tbody>{curve.points.slice(start,start+30).map(([x,y],row)=>{const i=start+row;return <tr key={i}>{([0,1] as const).map(axis=><td key={axis}>{editable?<input aria-label={`Point ${i+1} ${axis?'y':'x'}`} type="number" step="any" value={axis?y:x} onChange={e=>update({points:curve.points.map((v,j)=>i===j?axis?[v[0],Number(e.target.value)]:[Number(e.target.value),v[1]]:v)})}/>:<span title={String(axis?y:x)}>{Number((axis?y:x).toPrecision(7)).toLocaleString("en-GB",{maximumSignificantDigits:7})}</span>}</td>)}{editable&&<td><button title={`Delete point ${i+1}`} onClick={()=>update({points:curve.points.filter((_,j)=>j!==i)})}><Trash2 size={12}/></button></td>}</tr>;})}</tbody></table></div>
   <div className="pagination"><button title="Show the previous 30 points" disabled={currentPage===0} onClick={()=>setPage(currentPage-1)}>Previous</button><span>{curve.points.length?start+1:0}–{Math.min(start+30,curve.points.length)}</span><button title="Show the next 30 points" disabled={start+30>=curve.points.length} onClick={()=>setPage(currentPage+1)}>Next</button></div>
  </div></div>{issue&&<p className="material-error" role="alert">{issue}</p>}
  {importing&&<CurveImport curve={curve} browse={browse} close={()=>setImporting(false)} apply={value=>{change(value);setPage(0);setImporting(false);}}/>}
 </>;
}
