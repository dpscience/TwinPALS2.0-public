// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type { Curve } from './types';
export type CurveImportOptions={decimalComma:boolean;delimiter:'auto'|'comma'|'semicolon'|'tab'|'space';xColumn:number;yColumn:number;header:boolean};
export const defaultCurveImport:CurveImportOptions={decimalComma:false,delimiter:'auto',xColumn:1,yColumn:2,header:false};
// Exported tables identify their units; raw third-party tables keep the user's
// explicit unit selection. Detection changes the preview, never the saved curve.
export function curveMetadata(text:string):Partial<Pick<Curve,'x_unit'|'y_unit'>>{
 const match=text.match(/^# X unit: ([^;\r\n]+); Y unit: ([^\r\n]+)/m);
 return match?{x_unit:match[1].trim(),y_unit:match[2].trim()}:{};
}
function columns(line:string,delimiter:string):string[]{
 if(delimiter==='space')return line.trim().split(/\s+/);
 const separator=delimiter==='semicolon'?';':delimiter==='tab'?'\t':',';
 const result:string[]=[];let value='',quoted=false;
 for(let i=0;i<line.length;i++){const c=line[i];if(c==='"'){if(quoted&&line[i+1]==='"'){value+='"';i++;}else quoted=!quoted;}else if(c===separator&&!quoted){result.push(value.trim());value='';}else value+=c;}
 if(quoted)throw new Error('A quoted table cell is not closed.');result.push(value.trim());return result;
}
export function detectCurveImport(text:string):CurveImportOptions{
 const lines=text.replace(/^\uFEFF/,'').split(/\r?\n/).map(s=>s.trim()).filter(s=>s&&!/^[#%]/.test(s));
 if(!lines.length)return {...defaultCurveImport};
 const line=lines[0],delimiter=line.includes(';')?'semicolon':line.includes('\t')?'tab':line.includes(',')?'comma':'space';
 const parts=columns(line,delimiter),series=parts[0].toLowerCase()==='series';
 const header=series||parts.some(v=>!Number.isFinite(Number(v.replace(',','.'))));
 const sample=lines[header?1:0]??'',decimalComma=delimiter!=='comma'&&/\d,\d/.test(sample);
 return {...defaultCurveImport,delimiter,decimalComma,header,xColumn:series?2:1,yColumn:series?3:2};
}
export function parseCurve(text:string,options:CurveImportOptions|boolean=false):[number,number][]{
 const o=typeof options==='boolean'?{...defaultCurveImport,decimalComma:options}:options;
 if(!Number.isInteger(o.xColumn)||!Number.isInteger(o.yColumn)||o.xColumn<1||o.yColumn<1||o.xColumn===o.yColumn)throw new Error('Choose two different positive column numbers.');
 let lines=text.replace(/^\uFEFF/,'').split(/\r?\n/).map((line,i)=>({line:line.trim(),row:i+1})).filter(x=>x.line&&!/^[#%]/.test(x.line));if(o.header)lines=lines.slice(1);
 const points:[number,number][]=[],seen=new Set<number>();
 for(const {line,row} of lines){const delimiter=o.delimiter==='auto'?(line.includes(';')?'semicolon':line.includes('\t')?'tab':!o.decimalComma&&line.includes(',')?'comma':'space'):o.delimiter;
  const parts=columns(line,delimiter);const x=parts[o.xColumn-1],y=parts[o.yColumn-1];
  if(x===undefined||y===undefined||x===''||y==='')throw new Error(`Row ${row}: missing value in a selected column.`);
  const values=[x,y].map(v=>Number(o.decimalComma?v.replace(',','.'):v));if(!values.every(Number.isFinite))throw new Error(`Row ${row}: expected numeric values. Enable “Header row” if needed.`);
  if(seen.has(values[0]))throw new Error(`Row ${row}: duplicate x = ${values[0]}.`);seen.add(values[0]);points.push(values as [number,number]);
 }
 if(points.length<2)throw new Error('At least two numeric data rows are required.');return points;
}
export function curveText(curve:Curve,kind:'csv'|'txt'){const sep=kind==='csv'?',':'\t';return ['# TwinPALS curve table v1',`# ${curve.name}`,`# ${curve.semantics.replace(/[\r\n]+/g,' ')}`,`# X unit: ${curve.x_unit}; Y unit: ${curve.y_unit}`,...curve.points.map(p=>p.join(sep))].join('\n');}
