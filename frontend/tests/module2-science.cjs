// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

require('./vite-assets.cjs');
const assert=require('node:assert/strict'),{test}=require('node:test'),fs=require('node:fs'),ts=require('typescript');
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {classLabel,waveformPlot}=Object.assign({},require('../src/m2types.ts'),require('../src/m2plots.ts'));
const seed={entries:JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../../seed/factory_catalogue.json'),'utf8')).items.filter(e=>e.category==='digitizer').map(e=>({...e,...e.properties}))};
const {digitizerTimingPlots}=require('../src/m2timingModel.ts');
const {classExplanation,classPlot}=require('../src/m2plots.ts');
const responses=[{polarity:'negative'},{polarity:'positive'}];

test('waveform default range, autoscale and timeline follow effective inverted polarity',()=>{
 const {timelinePlot}=require('../src/m2plots.ts');
 const p={channels:[{threshold_mV:10,invert:false},{threshold_mV:20,invert:false}],digitization:{voltage_min_mV:-500,voltage_max_mV:500,full_range_mV:1000,baseline_mV:0,noise_sigma_mV:.5}};
 const negative=[{polarity:'negative'},{polarity:'negative'}];
 assert.deepEqual(waveformPlot(null,'Waveform pair',p,negative).fixedY,[-500,3]);
 assert.equal(waveformPlot(null,'Waveform pair',p,negative,true).fixedY,undefined);
 p.channels[0].invert=true;
 assert.deepEqual(waveformPlot(null,'Waveform pair',p,negative).fixedY,[-500,500]);
 assert.deepEqual(waveformPlot(null,'Waveform pair',p,negative).levels.map(x=>x.y),[10,-20]);
 assert.deepEqual(timelinePlot(null,'na22',p,negative).panelY,[[0,500],[-500,0]]);
 p.channels[1].invert=true;
 assert.deepEqual(waveformPlot(null,'Waveform pair',p,negative).fixedY,[-3,500]);
 p.digitization.voltage_min_mV=0;p.digitization.voltage_max_mV=1000;
 assert.deepEqual(waveformPlot(null,'Waveform pair',p,negative).fixedY,[0,1000]);
});

test('AND timeline marks both accepted crossings and shades coincidence in both panels',()=>{
 const {timelinePlot}=require('../src/m2plots.ts');
 const w={start_ns:100,end_ns:300,trigger_ns:120,trigger_channel:1,busy_until_ns:30300,accepted_crossings_ns:[116,120],coincidence_window_ns:[116,156],timeline:{low_ns:60,high_ns:340,total:0,pulses:[]},waveform:[[0,200],[0,0],[0,200],[0,0]]};
 const p=timelinePlot(w,'na22');
 assert.deepEqual(p.markers.filter(m=>m.label.startsWith('Accepted')).map(m=>[m.panel,m.x]),[[0,.116],[1,.12]]);
 const band=p.bands.find(b=>b.label.startsWith('A AND B'));assert.equal(band.low,.116);assert.equal(band.high,.156);
 assert.equal(band.panel,undefined); // Common band is drawn in both channel panels.
 assert.ok(!p.markers.some(m=>m.label==='Earliest allowed crossing'));
 assert.equal(p.markers.find(m=>m.label.startsWith('Common trigger')).span.end,.3);
 const wave=waveformPlot(w);assert.deepEqual(wave.bands.map(b=>[b.low,b.high]),[[16,56]]);
 assert.deepEqual(wave.markers.map(m=>m.x),[16,20,20]);
});

test('scalar cell model density has unit area and the expected moments',()=>{
 const {deviceSettings}=require('../src/m2types.ts');
 const integral=(points,fn)=>points.slice(1).reduce((sum,[x,y],i)=>sum+(x-points[i][0])*(fn(x,y)+fn(...points[i]))/2,0);
 for(const e of seed.entries){
  const d=deviceSettings(e),plots=digitizerTimingPlots({digitization:d},e);
  assert.equal(plots.length,1);const points=plots[0].series[0].points;
  assert.ok(Math.abs(integral(points,(x,y)=>y)-1)<1e-5,e.name);
  const mean=1000/e.default_rate;
  assert.ok(Math.abs(integral(points,(x,y)=>x*y)-mean)<mean*1e-5);
  if(e.architecture==='switched_capacitor'){
   const expected=e.cell_alternation_ps**2+2*(e.default_fixed_jitter_ps**2+e.default_random_jitter_ps**2);
   assert.ok(Math.abs(integral(points,(x,y)=>(x-mean)**2*y)/expected-1)<.0001);
  }
 }
});

test('every exclusive class has matching isotope-aware explanation and hover region',()=>{
 for(const isotope of ['na22','co60']){
  const p=classPlot({},isotope);
  assert.equal(p.series.length,8);
  for(let i=0;i<p.series.length;i++){
   const s=p.series[i];assert.ok(s.hoverRange[0]<i+1&&s.hoverRange[1]>i+1);
   assert.ok(s.explanation.text.includes('origin IDs'));
   assert.equal(s.explanation.isotope,isotope);
  }
 }
 assert.match(classExplanation('same_primary_2','co60').text,/same 1332-keV gamma/);
 assert.match(classExplanation('same_primary_2','na22').text,/two annihilation photons together/);
 assert.match(classExplanation('single','co60').text,/Exactly one analogue/);
});

test('primary labels use isotope metadata in reloaded pulse classes',()=>{
 assert.match(classLabel('same_primary_1','na22'),/1275/);
 assert.match(classLabel('same_primary_2','na22'),/511/);
 assert.match(classLabel('same_primary_1','co60'),/1173/);
 assert.match(classLabel('same_primary_2','co60'),/1332/);
});
test('waveform plots retain per-channel time coordinates and negative polarity',()=>{
 const w={start_ns:100,trigger_ns:120,waveform:[[0,.19,.41],[0,-10,-20],[0,.21,.39],[0,10,20]]};
 const p=waveformPlot(w);
 assert.deepEqual(p.series[0].points,[[0,0],[.19,-10],[.41,-20]]);
 assert.deepEqual(p.series[1].points,[[0,0],[.21,10],[.39,20]]);
 assert.equal(p.markers[0].x,20);
});



test('absolute pulse timeline retains heights, trigger and acquisition/dead intervals',()=>{
 const {timelinePlot}=require('../src/m2plots.ts');const {plotRanges}=require('../src/plotRange.ts');
 const p=timelinePlot({start_ns:1000000,end_ns:1000204.8,trigger_ns:1000020,trigger_channel:1,busy_until_ns:1000500,timeline:{low_ns:999960,high_ns:1000540,total:2,pulses:[{channel:0,role:0,onset_ns:15,height_mV:80},{channel:1,role:1,onset_ns:300,height_mV:40}]}},'co60',{digitization:{full_range_mV:1000,baseline_mV:10,noise_sigma_mV:.5},channels:[{},{}]},responses);
 assert.deepEqual(p.series[0].points,[[1000.015,10],[1000.015,-70],[1000.015,10]]);
 assert.equal(p.series[3].points[1][1],50);
 assert.ok(Math.abs(p.bands[0].high-1000.2048)<1e-9);assert.equal(p.bands[0].low,1000);assert.equal(p.bands[1].low,p.bands[0].high);assert.equal(p.bands[1].high,1000.5);
 assert.equal(p.markers[0].x,1000.02);assert.equal(p.markers[0].label,'Accepted crossing · B');
 assert.equal(p.preciseX,true);assert.match(p.series[3].name,/1332/);
 const domain=plotRanges(p.series,p.extent.map(x=>({x})),{x:null,y:null});
 assert.deepEqual(domain.x,[999.96,1000.54]);assert.deepEqual(p.panelY,[[-500,10],[10,500]]);assert.deepEqual(p.panels,['A','B']);assert.equal(p.series[3].panel,1);assert.equal(p.series[0].panel,0);assert.equal(p.series[0].color,p.series[1].color);assert.notEqual(p.series[0].color,p.series[2].color);assert.equal(p.series[1].dashed,true);
 assert.ok(p.series.every(s=>s.stems));
 const zoomed=plotRanges(p.series,p.extent.map(x=>({x})),{x:[1000,1000.1],y:[-20,20]});
 assert.deepEqual(zoomed.x,[1000,1000.1]);assert.deepEqual(p.panelY,[[-500,10],[10,500]]);
});


test('noise-free timeline uses per-channel polarity and a white separator',()=>{
 const {timelinePlot}=require('../src/m2plots.ts'),{plotPanels}=require('../src/plotRange.ts');
 const profile={digitization:{full_range_mV:1000,baseline_mV:0,noise_sigma_mV:.48},channels:[{},{}]};
 const p=timelinePlot(null,'na22',profile,responses);
 assert.deepEqual(p.panelY,[[-500,0],[0,500]]);
 const rows=plotPanels(p.panels,p.panelY,[-500,500],18,216,p.panelGap);
 assert.equal(rows.length,2);assert.equal(rows[1].top-(rows[0].top+rows[0].height),16);
 assert.deepEqual(rows[0].ticks,[-500,-250,0]);assert.deepEqual(rows[1].ticks,[0,250,500]);
 assert.equal(rows[1].top+rows[1].height,234);
 const quiet=timelinePlot(null,'na22',{...profile,digitization:{...profile.digitization,noise_sigma_mV:0}},responses);
 assert.deepEqual(quiet.panelY,[[-500,0],[0,500]]);
 const noisy=timelinePlot(null,'na22',{...profile,digitization:{...profile.digitization,noise_sigma_mV:200}},responses);
 assert.deepEqual(noisy.panelY,[[-500,0],[0,500]]);
});

test('bounded source generation exposes the known timeline horizon',()=>{
 const {timelinePlot}=require('../src/m2plots.ts');
 const w={start_ns:0,end_ns:200,trigger_ns:20,trigger_channel:0,busy_until_ns:400,timeline:{low_ns:-40,high_ns:440,known_until_ns:300,total:0,pulses:[]}};
 const p=timelinePlot(w,'na22');
 assert.equal(p.markers.find(m=>m.label==='Preview horizon').x,.3);
 assert.match(p.note,/saved acquisition window is complete/);
 assert.equal(timelinePlot({...w,timeline:{...w.timeline,known_until_ns:w.timeline.high_ns}},'na22').markers.length,2);
});

test('long dead time leaves acquisition window readable and channel colours unambiguous',()=>{
 const {timelinePlot,waveformPlot}=require('../src/m2plots.ts');
 const {intervalAnnotation,channelColors}=require('../src/plotStyle.ts');
 const w={start_ns:1000,end_ns:1204.8,trigger_ns:1020,trigger_channel:1,busy_until_ns:2001204.8,waveform:[[0,1],[0,2],[0,1],[0,3]],timeline:{low_ns:960,high_ns:2001245.76,known_until_ns:9000,total:1,pulses:[{channel:1,role:0,onset_ns:20,height_mV:40}]}};
 const p=timelinePlot(w,'na22'),wave=waveformPlot(w);
 assert.equal(p.omittedTail.label,'2 ms');assert.deepEqual(p.focusX,[.95904,1.2047999999999999]);
 assert.ok(p.focusX[1]-p.focusX[0]<.25);assert.ok(p.bands[1].high-p.bands[1].low>1999);
 assert.equal(p.series[2].points[0][0],1.02); // Numeric time is unchanged by the schematic.
 for(let ch=0;ch<2;ch++)for(let role=0;role<2;role++)assert.equal(p.series[ch*2+role].color,wave.series[ch].color);
 assert.notEqual(channelColors[0],channelColors[1]);assert.equal(p.series[1].dashed,true);assert.equal(p.series[0].dashed,false);
 const nodes=intervalAnnotation(p.omittedTail,660,22,120,150);
 assert.ok(nodes.some(n=>n.text==='2 ms'));assert.ok(nodes.some(n=>n.text==='not to scale'));
 assert.equal(timelinePlot({...w,busy_until_ns:1204.8},'na22').omittedTail,undefined);
});

test('timeline puts independent thresholds and the shared delay in the correct channel',()=>{
 const {timelinePlot}=require('../src/m2plots.ts');
 const profile={digitization:{full_range_mV:1000,baseline_mV:10},channels:[{threshold_mV:8},{threshold_mV:20}]};
 const w={start_ns:1000,end_ns:1204.8,trigger_ns:1020,trigger_channel:1,busy_until_ns:1504.8};
 const p=timelinePlot(w,'na22',profile,responses);
 assert.deepEqual(p.levels.map(v=>[v.panel,v.y]),[[0,2],[1,30]]);
 assert.match(p.levels[0].label,/Threshold A/);assert.match(p.levels[1].label,/Threshold B/);
 assert.equal(p.markers[0].panel,1);assert.match(p.markers[0].label,/Accepted crossing · B/);
 const marker=p.markers.find(m=>m.label==='Common trigger');
 assert.equal(marker.span.end,p.bands[0].high);
 assert.ok(Math.abs((marker.span.end-marker.x)*1000-184.8)<1e-9);
 assert.equal(marker.span.label,'Common delay · 184.8 ns');
 assert.match(p.explanation.text,/summed analogue voltage/);
 const fromA=timelinePlot({...w,trigger_channel:0},'co60',profile,responses);
 assert.equal(fromA.markers[0].panel,0);assert.deepEqual(fromA.markers.find(m=>m.label==='Common trigger').span,marker.span);
});
const {cathodeLayer,persistenceLayer}=require('../src/reportDensity.ts');
const {reportHTML}=require('../src/report.ts');

test('wheel zoom is reciprocal and remains at the same offset on a moving source clock',()=>{
 const {wheelRange,shiftRange}=require('../src/plotRange.ts');
 const original=[1000.01,1000.21],origin=1000.03;
 let range=original;
 for(let i=0;i<5;i++)range=wheelRange(range,.37,-1);
 for(let i=0;i<5;i++)range=wheelRange(range,.37,1);
 range.forEach((v,i)=>assert.ok(Math.abs(v-original[i])<1e-9));
 const relative=shiftRange(range,-origin),next=shiftRange(relative,2e6);
 next.forEach((v,i)=>assert.ok(Math.abs(v-2e6-(original[i]-origin))<1e-9));
});
test('offline reports contain all density selections with exact counts and no server dependency',()=>{
 const counts=[[1,2],[3,4]],map=cathodeLayer({geometry:{width_mm:40,height_mm:20,shape:'rect'},counts,count:10},'B · 511 keV');
 assert.deepEqual(map.x,[-20,20]);assert.deepEqual(map.y,[-10,10]);assert.equal(map.log,false);
 const density=persistenceLayer({x_range:[12,40],y_range:[0,.6],counts,count:7},'A · 1275 keV');
 assert.equal(density.log,true);assert.deepEqual(density.counts,counts);
 const plots=[{title:'Cathode map',xLabel:'X (mm)',yLabel:'Y (mm)',series:[],density:[map]},{title:'Pulse persistence',xLabel:'Time (ns)',yLabel:'1/ns',series:[],density:[density]}];
 const html=reportHTML({name:'</script><unsafe>'},plots,{created_at:'2026-11-11T12:00:00Z',complete:true});
 const payload=JSON.parse(html.match(/id="report-data">(.*?)<\/script>/s)[1]);
 assert.deepEqual(payload.plots,plots);assert.equal(payload.profile.name,'</script><unsafe>');
 assert.ok(!html.includes('</script><unsafe>'));assert.ok(html.includes('densityRender(card, plot)'));
 assert.ok(html.includes('svg.ondblclick'));assert.ok(html.includes('x_low'));assert.ok(html.includes('canvas.toDataURL'));
 assert.ok(!html.includes('fetch('));
});
