// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

const assert=require('node:assert/strict'),{test}=require('node:test'),fs=require('node:fs'),ts=require('typescript');
require.extensions['.ts']=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {pollDensityBank}=require('../src/densityPolling.ts');
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('a permanent density failure stops requests and source replacement can restart',async t=>{
 const timers=new Map();let requests=0;const errors=[],data=[];
 t.mock.method(global,'setTimeout',(fn,ms)=>{timers.set(1,{fn,ms});return 1;});
 t.mock.method(global,'clearTimeout',id=>timers.delete(id));
 t.mock.method(global,'fetch',async()=>{requests++;return new Response(JSON.stringify({detail:'Insufficient disk space'}),{status:422});});
 const stop=pollDensityBank({run_id:'failed'},120,v=>data.push(v),v=>errors.push(v));
 await flush();assert.equal(requests,1);assert.equal(timers.size,0);assert.deepEqual(errors,['Insufficient disk space']);assert.equal(data.length,0);stop();
 global.fetch=async()=>{requests++;return new Response(JSON.stringify({data:{bins:120,maps:[],persistence:[]},version:1}));};
 const next=pollDensityBank({run_id:'new'},120,v=>data.push(v),v=>errors.push(v));
 await flush();assert.equal(requests,2);assert.equal(data.length,1);assert.equal(timers.get(1).ms,750);next();assert.equal(timers.size,0);
});

test('transient density failures back off and recovery resumes normal live cadence',async t=>{
 let scheduled,requests=0;const errors=[];
 t.mock.method(global,'setTimeout',(fn,ms)=>{scheduled={fn,ms};return 1;});
 t.mock.method(global,'clearTimeout',()=>{scheduled=null;});
 t.mock.method(global,'fetch',async()=>{requests++;return requests===1?new Response('{}',{status:503}):new Response(JSON.stringify({data:null,version:0}));});
 const stop=pollDensityBank({run_id:'live'},120,()=>{},v=>errors.push(v));
 await flush();assert.equal(scheduled.ms,1500);
 await scheduled.fn();assert.equal(scheduled.ms,750);assert.equal(errors.at(-1),'');stop();
});

test('disposing an inset prevents stale responses and further polling',async t=>{
 let resolveRequest,calls=0,timers=0;
 t.mock.method(global,'setTimeout',()=>{timers++;return 1;});
 t.mock.method(global,'clearTimeout',()=>{});
 t.mock.method(global,'fetch',()=>new Promise(resolve=>{resolveRequest=resolve;}));
 const stop=pollDensityBank({run_id:'old'},120,()=>calls++,()=>calls++);
 stop();resolveRequest(new Response(JSON.stringify({data:{bins:120,maps:[],persistence:[]},version:1})));
 await flush();assert.equal(calls,0);assert.equal(timers,0);
});
