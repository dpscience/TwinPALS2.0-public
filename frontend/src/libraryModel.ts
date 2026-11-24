// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type { Entry } from './types';

const lengthToMm:Record<string,number>={nm:1e-6,um:.001,'µm':.001,'μm':.001,mm:1,cm:10,m:1000};
function binding(entry:Entry,key:string){
 const name=key==='refractive_index'?'refractive_index':key==='absorption_length_mm'?'absorption_length':null;
 if(!name||!['scintillator','coupling','window'].includes(entry.category))return null;
 const curve=entry.curves.find(c=>c.name===name);if(!curve)return null;
 const factor=name==='absorption_length'?lengthToMm[curve.y_unit]:curve.y_unit==='1'?1:undefined;
 const constant=curve.points.length>0&&curve.points.every(p=>p[1]===curve.points[0][1]);
 return {curve,factor,constant};
}
export function scalarControl(entry:Entry,key:string){
 const bound=binding(entry,key);if(!bound)return {value:entry.properties[key],disabled:false,hint:''};
 if(!bound.constant||bound.factor===undefined)return {value:entry.properties[key],disabled:true,hint:'Controlled by tabulated curve. Edit or import the curve below.'};
 return {value:bound.curve.points[0][1]*bound.factor,disabled:false,hint:'Updates the constant tabulated curve used by the engine.'};
}
export function updateLibraryProperty(entry:Entry,key:string,value:unknown):Entry{
 const bound=binding(entry,key);
 if(bound&&(!bound.constant||bound.factor===undefined))return entry;
 const properties={...entry.properties,[key]:value};
 const curves=bound?entry.curves.map(c=>c===bound.curve?{...c,points:c.points.map(([x])=>[x,Number(value)/bound.factor!] as [number,number])}:c):entry.curves;
 return {...entry,properties,curves};
}
