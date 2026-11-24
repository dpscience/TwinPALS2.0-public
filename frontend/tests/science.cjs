// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

const assert=require('node:assert/strict');
const {test}=require('node:test');
const fs=require('node:fs'),ts=require('typescript');
// Load the real frontend transformations; no mock API or simulated run data.
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {opticalDisplayPoints}=require('../src/Charts.tsx');
const {scalarControl,updateLibraryProperty}=require('../src/libraryModel.ts');
const hc=1239.8419843320026;
const input={name:'emission',x_unit:'eV',y_unit:'1/eV',semantics:'Photon number density',points:Array.from({length:4001},(_,i)=>[2+i/2000,.5])};
const wavelength=opticalDisplayPoints(input,'nm');

test('spectral conversion produces an increasing axis',()=>assert.ok(wavelength.every((p,i)=>i===0||p[0]>wavelength[i-1][0])));
test('density conversion conserves photon number',()=>{
 const integral=wavelength.slice(1).reduce((sum,p,i)=>sum+(p[0]-wavelength[i][0])*(p[1]+wavelength[i][1])/2,0);
 assert.ok(Math.abs(integral-1)<1e-7);
});
test('energy/wavelength density round trip preserves values',()=>{
 const roundTrip=opticalDisplayPoints({...input,x_unit:'nm',y_unit:'1/nm',points:wavelength},'eV');
 for(let i=0;i<input.points.length;i++){assert.ok(Math.abs(roundTrip[i][0]-input.points[i][0])<1e-12);assert.ok(Math.abs(roundTrip[i][1]-.5)<1e-12);}
});
test('relative ordinates do not receive a density Jacobian',()=>assert.deepEqual(opticalDisplayPoints({...input,y_unit:'relative',points:[[2,.2],[4,.8]]},'nm'),[[hc/4,.8],[hc/2,.2]]));
test('QE percentage conversion preserves probability',()=>assert.deepEqual(opticalDisplayPoints({name:'quantum_efficiency',x_unit:'eV',y_unit:'%',semantics:'Probability',points:[[2,20],[4,80]]},'nm',true),[[hc/4,.8],[hc/2,.2]]));
const material={category:'scintillator',properties:{refractive_index:1.58,absorption_length_mm:80},curves:[{name:'refractive_index',y_unit:'1',points:[[2,1.58],[4,1.58]]},{name:'absorption_length',y_unit:'cm',points:[[2,8],[4,8]]}]};
test('scalar index edit updates the active constant curve',()=>assert.deepEqual(updateLibraryProperty(material,'refractive_index',1.7).curves[0].points,[[2,1.7],[4,1.7]]));
test('scalar absorption edit converts mm into the table unit',()=>{
 const changed=updateLibraryProperty(material,'absorption_length_mm',120);
 assert.deepEqual(changed.curves[1].points,[[2,12],[4,12]]);assert.equal(scalarControl(changed,'absorption_length_mm').value,120);
});
test('material edit preserves the original revision',()=>{
 const original=structuredClone(material);updateLibraryProperty(material,'refractive_index',1.7);updateLibraryProperty(material,'absorption_length_mm',120);assert.deepEqual(material,original);
});
test('dispersive curves cannot be overwritten with a scalar',()=>{
 const dispersion={...material,curves:[{name:'refractive_index',y_unit:'1',points:[[2,1.58],[4,1.7]]}]};
 assert.equal(scalarControl(dispersion,'refractive_index').disabled,true);assert.deepEqual(updateLibraryProperty(dispersion,'refractive_index',1.4),dispersion);
});
