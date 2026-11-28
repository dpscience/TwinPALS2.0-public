// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

require('./vite-assets.cjs');
const assert=require('node:assert/strict'),{test}=require('node:test'),fs=require('node:fs'),ts=require('typescript');
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const React=require('react'),{renderToStaticMarkup}=require('react-dom/server');
require.extensions['.css']=()=>{};
const {PreferencesProvider}=require('../src/Preferences.tsx');
const Fields=require('../src/M2ComponentFields.tsx').default;
const seed=JSON.parse(fs.readFileSync(require('node:path').join(__dirname,'../../seed/factory_catalogue.json'),'utf8'));
const entry=seed.items.find(e=>e.id==='psi-drs4-v5');
const component={...entry,...entry.properties,references:entry.provenance.references.map(r=>({...r,fields:r.properties}))};
test('cell model controls stay with their plot, separate from channel IRF and readout',()=>{
 const html=renderToStaticMarkup(React.createElement(PreferencesProvider,null,React.createElement(Fields,{entry:component,tab:'timing',newEntry:false,editing:false,change:()=>{}})));
 const group=html.split('aria-label="Cell interval model"')[1].split('aria-label="Channel timing and readout"')[0];
 assert.ok(group.includes('Cell intervals · generated model'));
 for(const text of ['Fixed aperture pattern','Random coordinate variation','Even/odd interval offset'])assert.ok(group.includes(text),text);
 assert.ok(!group.includes('Readout dead time'));
 assert.ok(!group.includes('Channel IRF σ · ps'));
 assert.ok(group.indexOf('Cell intervals · generated model')<group.indexOf('Fixed aperture pattern'));
 assert.match(html.split('aria-label="Channel timing and readout"')[1],/Readout dead time/);
 assert.ok((html.match(/disabled=""/g)||[]).length>=7);
});

test('selected transport keeps both selectors in each channel and attributes only responses started by CF',()=>{
 const {PulseTransport}=require('../src/PulseTransport.tsx');
 const render=wave=>renderToStaticMarkup(React.createElement(PulseTransport,{wave}));
 const empty=render(null);
 assert.equal((empty.match(/<select /g)||[]).length,4);
 assert.equal((empty.match(/<select [^>]*disabled/g)||[]).length,4);
 const pulse={role:0,record:24,decay:7,light_origin:'mixed'};
 const route=(detector,origin,by_cf)=>({detector,origin,birth:'Crystal '+detector,count:5,steps:[],by_cf,cathode_arrival_ns:[1.1,2.4]});
 const record={role:0,record:24,paths:[route('A','Scintillation',{7:4,8:0}),route('A','Cherenkov',{7:0,8:1}),route('B','Cherenkov',{7:1})]};
 const wave={id:5,sequence:6,features:[{valid:true,cfd_ns:50},{valid:true,cfd_ns:45}],transport_truth:[record],
  truth:{category:'correlated',selected:[[pulse],[pulse]]}};
 let html=render(wave);
 assert.match(html,/Scintillation at CF/);assert.match(html,/Cherenkov at CF/);
 assert.doesNotMatch(html,/Mixed at CF/);
 assert.match(html,/2\/2 · Cherenkov · Crystal A/);
 assert.match(html,/Photocathode A/);assert.match(html,/1.1–2.4 ns after γ emission/);
 assert.match(html,/4 PE responses started by CF/);
 assert.equal((html.match(/<select [^>]*disabled/g)||[]).length,3);
 wave.truth.selected[0].push({...pulse,decay:8},pulse);
 html=render(wave);
 assert.match(html,/Mixed at CF/);assert.match(html,/4 scintillation and 1 Cherenkov PE onsets by CF/);
 assert.equal((html.match(/<select [^>]*disabled/g)||[]).length,2);
 record.paths[0].by_cf={8:0};
 assert.match(render(wave),/Light unavailable/);
});

test('Module 1 analysis selectors stay disabled until an event is available',()=>{
 const Analysis=require('../src/AnalysisView.tsx').default;
 const props={analyses:[],selection:{detector:'all',primary:'all',category:'all',bins:120},plottedSelection:{},setSelection:()=>{},metrics:[],setMetrics:()=>{},roles:[],summaryStreams:[],sessionPhase:'',loading:false,error:'',hasSession:false,open:()=>{},locked:false};
 for(const completed of [null,0,1]){
  const html=renderToStaticMarkup(React.createElement(PreferencesProvider,null,React.createElement(Analysis,{...props,hasSession:completed!==null,summaryStreams:completed===null?[]:[{completed,role:'na22_prompt',path:'example.tpstream'}]})));
  const controls=html.split('class="analysis-scroll"')[0].match(/<(select|input)\b[^>]*>/g);assert.equal(controls.length,6);
  assert.ok(controls.every(v=>v.includes('disabled=""')===(completed!==1)));
 }
});

test('acquisition schematic shows largest M1 pulse and attenuation overflow for each channel',()=>{
 const {M2Schematic}=require('../src/M2Schematic.tsx');
 const p={channels:[{attenuation_dB:0,cable_delay_ns:0,threshold_mV:10},{attenuation_dB:30,cable_delay_ns:0,threshold_mV:10}],acquisition:{trigger:'coincidence',trigger_delay_ns:180,coincidence_ns:40},activity_Bq:925000};
 const inputs={isotope:'na22',observed_maximum_mV:[2000,2000],streams:[{header:{analog_response:['negative','negative'].map(polarity=>({polarity,hv_V:3000,gain:2500000,load_ohm:50,transit_ns:16,tts_sigma_ns:.15}))}}]};
 const html=renderToStaticMarkup(React.createElement(M2Schematic,{profile:p,device:component,inputs}));
 assert.equal((html.match(/Largest M1 pulse/g)||[]).length,2);
 assert.match(html,/Exceeds ADC range/);assert.match(html,/Within ADC range/);
 assert.match(html,/At ADC: 63\.246 mV/);
});

test('all histogram quantities have a sketch, filter interpretation and explicit zero control',()=>{
 const {analysisMetrics,emptyHistogram,metricExplanations}=require('../src/analysisModel.ts');
 assert.equal(analysisMetrics.length,9);
 for(const metric of analysisMetrics){
  assert.ok(metricExplanations[metric].diagram,metric);
  const plot=emptyHistogram(metric,{detector:'all',primary:'all',category:'miss',origin:'cherenkov',bins:120});
  assert.match(plot.note,/miss/);assert.match(plot.note,/Cherenkov/);
  assert.match(plot.explanation.text,/QE-accepted/);
  assert.match(plot.explanation.text,/SAME detector/);
  assert.match(plot.explanation.text,/groups complete events/);
 }
 assert.match(metricExplanations.energy.text,/TOTAL energy deposited/);
 assert.match(metricExplanations.photon_count.text,/ALL QE-accepted photons/);
 assert.match(metricExplanations.pulse_height.text,/COMPLETE anode pulse/);
 assert.match(metricExplanations.reflections.text,/photons rejected by QE/);
 for(const metric of ['mean_arrival','track_length'])assert.match(metricExplanations[metric].text,/No pulse has no/);
 assert.match(metricExplanations.depth.text,/no depth and remain excluded/);
 for(const metric of ['polar_angle','azimuth'])assert.match(metricExplanations[metric].text,/511-keV pair contributes both/);
});

test('Crystal plots do not silently show cathode-selected populations',()=>{
 const {analysisMetrics,emptyHistogram,crystalMetrics}=require('../src/analysisModel.ts');
 const {Plot}=require('../src/Plot.tsx');
 for(const metric of analysisMetrics){
  const data=emptyHistogram(metric,{basis:'crystal',detector:'A',primary:'all',category:'all',origin:'all',bins:120});
  assert.match(data.explanation.text,/CREATED inside this crystal/);
  assert.equal(!!data.unavailable,!crystalMetrics.includes(metric));
  if(data.unavailable){
   const html=renderToStaticMarkup(React.createElement(PreferencesProvider,null,React.createElement(Plot,{data})));
   assert.match(html,/aria-disabled="true"/);assert.match(html,/Available in Anode view/);
   assert.ok(!html.includes('Hide zeros'));
  }
 }
});

test('legend samples encode exactly the same solid/dashed distinction as the data traces',()=>{
 const {LineSwatch}=require('../src/Plot.tsx');
 const solid=renderToStaticMarkup(React.createElement(LineSwatch,{color:'#123456',dashed:false}));
 const dashed=renderToStaticMarkup(React.createElement(LineSwatch,{color:'#123456',dashed:true}));
 assert.match(solid,/stroke="#123456"/);assert.ok(!solid.includes('stroke-dasharray="5 3"'));
 assert.match(dashed,/stroke-dasharray="5 3"/);
});

test('nested modal background locks release in either order without stranding the app',()=>{
 const {lockBackground}=require('../src/modalInert.ts');
 for(const outerFirst of [true,false]){
  const root={inert:false},outer=lockBackground(root),inner=lockBackground(root);
  assert.equal(root.inert,true);
  (outerFirst?outer:inner)();assert.equal(root.inert,true);
  (outerFirst?inner:outer)();assert.equal(root.inert,false);
  outer();inner();assert.equal(root.inert,false);
 }
 const alreadyLocked={inert:true},release=lockBackground(alreadyLocked);release();assert.equal(alreadyLocked.inert,true);
});

test('recorded crystal dimension drawings use the physical faces for all four shapes',()=>{
 const {DetectorDrawings}=require('../src/DetectorDrawings.tsx');
 const dimensions={length_mm:27,diameter_mm:24,width_mm:18,height_mm:14,front_diameter_mm:12,rear_diameter_mm:26,front_width_mm:11,front_height_mm:15,rear_width_mm:19,rear_height_mm:23};
 for(const [shape,front,rear] of [['cone','Ø 12 mm','Ø 26 mm'],['cylinder','Ø 24 mm','Ø 24 mm'],['pyramid','11 × 15 mm','19 × 23 mm'],['box','18 × 14 mm','18 × 14 mm']]){
  const setup={detectors:[{id:'A',shape,dimensions}],source_geometry:{radius_mm:0,thickness_mm:0},sample:{enabled:false,foil_enabled:false}};
  const html=renderToStaticMarkup(React.createElement(DetectorDrawings,{input:{setup}}));
  assert(html.includes(shape+' crystal, front '+front+', rear '+rear+', length 27 mm'));
  assert(!html.includes('undefined')&&!html.includes('NaN')&&!html.includes('Left sample'));
 }
});

test('baseline visibility imports a single switch for both channels and keeps their new states independent',()=>{
 const {baselineRegions}=require('../src/m3types.ts');
 assert.deepEqual(baselineRegions(true),[true,true]);
 assert.deepEqual(baselineRegions(false),[false,false]);
 const original=[true,false],copy=baselineRegions(original);copy[1]=true;
 assert.deepEqual(original,[true,false]);
});

test('Module 3 exposes intra-steps only for the channel using a curved interpolation',()=>{
 const {TimingSettings}=require('../src/LifetimeTuning.tsx');
 const {defaultMonitor}=require('../src/m3types.ts');
 const channel={baseline_samples:32,cfd_percent:25,intra_steps:12,median_samples:1,minimum_height_mV:5,reject_clipped:true};
 for(const interpolation of ['linear',undefined,'cubic','akima']){
  const html=renderToStaticMarkup(React.createElement(TimingSettings,{
   channels:[{...channel,interpolation},{...channel,interpolation:'akima',intra_steps:4}],rule:'highest',m:defaultMonitor,
   edit:()=>{},patch:()=>{},selectRule:()=>{}
  }));
  const inputs=html.match(/<input\b[^>]*>/g);
  const steps=name=>inputs.find(input=>input.includes('aria-label="'+name+' interpolation subdivisions"'));
  const linear=!interpolation||interpolation==='linear';
  assert.equal(steps('A').includes('disabled=""'),linear);
  assert.ok(steps('A').includes('value="12"'));
  assert.ok(!steps('B').includes('disabled=""')&&steps('B').includes('value="4"'));
 }
});

test('M1 switches the reflection metric in place for both populations',()=>{
 const {analysisMetricsFor,emptyHistogram}=require('../src/analysisModel.ts');
 for(const basis of ['anode','crystal']){
  const initial={basis,category:'all',origin:'all'};
  const first=analysisMetricsFor(initial);
  const second=analysisMetricsFor({...initial,reflection_scope:'cathode_reflections'});
  assert.equal(first.length,9);
  assert.deepEqual(second,[...first.slice(0,8),'cathode_reflections']);
  assert.equal(first[8],'reflections');
  for(const metric of [first[8],second[8]])assert.equal(emptyHistogram(metric,initial).unavailable,undefined);
 }
});
