// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

const assert=require('node:assert/strict'),{test}=require('node:test'),fs=require('node:fs'),ts=require('typescript');
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
test('restoring preferences never queues saved streams, but reattaches a server session',()=>{
 const {restoreSessionViews}=require('../src/sessionRestore.ts');
 const saved={analysis_paths:['old.tpstream'],last_session_paths:['last.tpstream'],module2:{tab:'simulation',analysis_paths:['old.tppulses.part']},selection:{bins:120}};
 const restored=restoreSessionViews(saved);
 assert.deepEqual(restored.analysis_paths,[]);
 assert.deepEqual(restored.module2.analysis_paths,[]);
 assert.deepEqual(restored.last_session_paths,saved.last_session_paths);
 assert.deepEqual(restored.selection,saved.selection);
 assert.deepEqual(restoreSessionViews(saved,['attached.tpstream']).analysis_paths,['attached.tpstream']);
 assert.deepEqual(saved.analysis_paths,['old.tpstream']);
});

test('processing progress counts source records, including zero-light and stopped streams',()=>{
 const {processingProgress}=require('../src/processingProgress.ts');
 const streams=[{role:'prompt',completed:100,total:100,outcomes:{total:72}}, {role:'pair',completed:40,total:100,status:'cancelled',outcomes:{total:40}}];
 assert.deepEqual(processingProgress(streams),{processed:112,total:140});
 assert.deepEqual(processingProgress(streams,'prompt'),{processed:72,total:100});
 const {percent}=require('../src/api.ts');
 assert.equal(percent(0),'0.00%');assert.equal(percent(100),'100.00%');assert.equal(percent(.126),'0.13%');
});
const {parseCurve,curveText,defaultCurveImport}=require('../src/curveText.ts');
const {plotText}=require('../src/Plot.tsx');
const {detectCurveImport,curveMetadata}=require('../src/curveText.ts');
const {spectralMatch}=require('../src/spectralMatch.ts');
const {plotRanges}=require('../src/plotRange.ts');

test('constant material curves remain visible between their two endpoints',()=>{
 const s=[{points:[[150,80],[750,80]]}];
 const r=plotRanges(s,[],{x:[300,400],y:null});
 assert.deepEqual(r.x,[300,400]);assert.ok(r.y[0]<80&&r.y[1]>80);
 const stale=plotRanges(s,[],{x:[1.7,2],y:[0,1.08]});
 assert.deepEqual(stale.x,[150,750]);assert.ok(stale.y[1]>80);
 const linear=plotRanges([{points:[[0,0],[10,100]]}],[],{x:[4,6],y:null});
 assert.equal(linear.y[1],64.80000000000001);
});
test('every factory material curve has finite visible autofit and internal zoom',()=>{
 const seed=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../../seed/factory_catalogue.json'),'utf8'));
 for(const e of seed.items)for(const c of e.curves){
  const points=[...c.points].sort((a,b)=>a[0]-b[0]),s=[{points}];
  assert.ok(points.every(p=>p.every(Number.isFinite)),e.id+':'+c.name);
  const fit=plotRanges(s,[],{x:null,y:null});
  assert.ok(fit.x[1]>fit.x[0]&&fit.y[1]>fit.y[0],e.id+':'+c.name);
  const width=fit.x[1]-fit.x[0],zoom=plotRanges(s,[],{x:[fit.x[0]+width*.4,fit.x[0]+width*.6],y:null});
  assert.ok(zoom.y.every(Number.isFinite)&&zoom.y[1]>zoom.y[0],e.id+':'+c.name);
 }
});
test('pulse plots fit negative and bipolar values without clipping',()=>{
 const r=plotRanges([{points:[[0,0],[1,-100],[2,15],[3,0]]}],[],{x:null,y:null});
 assert.ok(r.y[0]<-100&&r.y[1]>15);
});
test('curve export format detects headers, separators and units for every material curve',()=>{
 const seed=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../../seed/factory_catalogue.json'),'utf8'));
 for(const entry of seed.items)for(const curve of entry.curves)for(const kind of ['csv','txt']){
  const text=curveText(curve,kind);assert.deepEqual(parseCurve(text,detectCurveImport(text)),curve.points);
  assert.deepEqual(curveMetadata(text),{x_unit:curve.x_unit,y_unit:curve.y_unit});
 }
 const old=plotText({title:'Emission',xLabel:'Wavelength (nm)',yLabel:'1/nm',series:[{name:'Quoted, "name"',color:'#000',points:[[300,.1],[400,.2]]}]});
 assert.deepEqual(parseCurve(old,detectCurveImport(old)),[[300,.1],[400,.2]]);
 assert.deepEqual(parseCurve('lambda;density\n300,5;0,1\n400,5;0,2',detectCurveImport('lambda;density\n300,5;0,1\n400,5;0,2')),[[300.5,.1],[400.5,.2]]);
});
test('spectral match preserves absolute QE and weighted component photon fractions',()=>{
 const scint={name:'Test',properties:{spectral_interpretation:'photon_density_per_wavelength',components:[{curve:'emission_fast',fraction:.2},{curve:'emission_slow',fraction:.8}]},curves:[{name:'emission_fast',x_unit:'nm',y_unit:'1/nm',points:[[200,0],[210,1],[220,0]]},{name:'emission_slow',x_unit:'nm',y_unit:'1/nm',points:[[400,0],[410,1],[420,0]]}]};
 const cathode={name:'Test QE',curves:[{name:'quantum_efficiency',x_unit:'nm',y_unit:'1',points:[[200,.1],[420,.3]]}]};
 const data=spectralMatch(scint,cathode);assert.deepEqual(data.series[1].points,[[200,10],[420,30]]);
 const emission=data.series[0].points;assert.ok(Math.abs(Math.max(...emission.map(p=>p[1]))-100)<1e-8);
 const fast=emission.find(p=>Math.abs(p[0]-210)<1e-8)[1],slow=emission.find(p=>Math.abs(p[0]-410)<1e-8)[1];assert.ok(Math.abs(fast/slow-.25)<.002);
 assert.match(data.note,/QE is absolute/);
});
test('CSV, TXT and decimal comma preserve numeric values',()=>{
 assert.deepEqual(parseCurve('300,0.125\n400,0.25'),[[300,.125],[400,.25]]);
 assert.deepEqual(parseCurve('300\t0.125\n400\t0.25'),[[300,.125],[400,.25]]);
 assert.deepEqual(parseCurve('300,5;0,125\n400,5;0,25',true),[[300.5,.125],[400.5,.25]]);
});
test('selectable columns and header skip are explicit',()=>assert.deepEqual(parseCurve('id;lambda;qe\n1;300;0.2\n2;400;0.3',{...defaultCurveImport,header:true,delimiter:'semicolon',xColumn:2,yColumn:3}),[[300,.2],[400,.3]]));
test('curve import rejects missing, nonfinite and duplicate measurements',()=>{
 assert.throws(()=>parseCurve('300,0.2\n400,'),/missing/);
 assert.throws(()=>parseCurve('300,NaN\n400,0.2'),/numeric/);
 assert.throws(()=>parseCurve('300,0.2\n300,0.3'),/duplicate/);
});
test('curve text roundtrip does not normalize probability or emission weights',()=>{
 const c={name:'quantum_efficiency',x_unit:'nm',y_unit:'1',semantics:'Absolute probability',points:[[300,.125],[400,.25]]};
 for(const kind of ['csv','txt'])assert.deepEqual(parseCurve(curveText(c,kind)),c.points);
});
test('histogram numeric export retains explicit bin bounds and counts',()=>{
 const result=plotText({title:'Energy',xLabel:'Energy (keV)',yLabel:'Events / bin',series:[{name:'A',color:'#000',points:[[0,8],[20,8]],bins:[{low:0,high:20,count:8}]}]});
 assert.match(result,/bin_low.*bin_high.*count/);assert.match(result,/"A",0,20,8/);assert.match(result,/keV/);
});
const {matchesAnodePreview,originSeriesColor}=require('../src/previewSelection.ts');
test('all anode preview combinations, including no pulse in neither detector',()=>{
 const kinds=['none','scintillation','cherenkov','mixed'];
 for(let a=0;a<4;a++)for(let b=0;b<4;b++)for(const d of ['all','A','B'])for(const origin of ['all',...kinds]){
  const expected=origin==='all'||(d==='all'?(origin==='none'?a===0&&b===0:kinds[a]===origin||kinds[b]===origin):kinds[d==='A'?a:b]===origin);
  assert.equal(matchesAnodePreview([a,b],d,origin),expected,`${a}/${b}/${d}/${origin}`);
 }
});
test('split origin styles distinguish every primary and detector, independently of visibility',()=>{
 const {makePlot}=require('../src/analysisModel.ts');
 for(const roles of [['na22_prompt','na22_annihilation'],['co60_1173','co60_1332']]){
  const colors=roles.flatMap(p=>['none','scintillation','cherenkov','mixed'].map(o=>originSeriesColor(p,o)));
  assert.equal(new Set(colors).size,8);
  const series=roles.flatMap(primary=>['A','B'].flatMap(detector=>['none','scintillation','cherenkov','mixed'].map(origin=>({primary,detector,origin,counts:[2],edges:[0,1]}))));
  const plot=makePlot({metric:'energy',unit:'keV',series,markers:[]},{detector:'all',primary:'all',category:'all',origin:'all',split_origin:true,bins:120,suppress_zero:[]});
  assert.equal(new Set(plot.series.map(s=>s.name)).size,16);
  assert.equal(new Set(plot.series.map(s=>`${s.color}:${s.dashed}`)).size,16);
  assert.ok(plot.series.every((s,i)=>s.dashed===(series[i].detector==='B')&&!s.legendGroup));
 }
});
