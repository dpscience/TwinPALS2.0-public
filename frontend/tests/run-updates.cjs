// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

const assert=require('node:assert/strict'),{test}=require('node:test'),fs=require('node:fs'),ts=require('typescript');
require.extensions['.ts']=(module,filename)=>module._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,filename);
const {mergeRunUpdate}=require('../src/runUpdates.ts');
const {outcomeProgress}=require('../src/processingProgress.ts');
test('Event outcomes reports processed records across both primaries',()=>{
 const streams=[{role:'prompt',completed:100,outcomes:{total:90}},{role:'pair',completed:60,outcomes:{total:10}}];
 assert.equal(outcomeProgress(streams,200),50);
 assert.equal(outcomeProgress([{role:'prompt',completed:100}],100),0);
 assert.equal(outcomeProgress([],0),0);
});
const a={role:'na22_prompt',event_id:1,tracks:[{points_mm:[[1,2,3]]}]},b={role:'na22_annihilation',event_id:1},c={role:'na22_prompt',event_id:5};
test('deltas preserve role identity, ordering, retained objects, and evict expired previews',()=>{
 const old={id:'one',trajectories:[a,b],trajectory_revision:2};
 const next=mergeRunUpdate(old,{id:'one',status:'completed',trajectory_revision:3,trajectory_order:['na22_annihilation:1','na22_prompt:5'],trajectories:[c]});
 assert.deepEqual(next.trajectories,[b,c]);assert.equal(next.trajectories[0],b);assert.equal(old.trajectories[0],a);
 assert.equal(next.status,'completed');assert.equal(next.trajectory_order,undefined);
});
test('missing snapshots and new runs require a full resync, never silently omit previews',()=>{
 assert.throws(()=>mergeRunUpdate(null,{id:'new',trajectory_order:['na22_prompt:1'],trajectories:[a]}));
 assert.throws(()=>mergeRunUpdate({id:'old',trajectories:[a]},{id:'new',trajectory_order:[],trajectories:[]}));
 assert.throws(()=>mergeRunUpdate({id:'one',trajectories:[]},{id:'one',trajectory_order:['na22_prompt:1'],trajectories:[]}));
 const full={id:'new',trajectories:[a]};assert.equal(mergeRunUpdate(null,full),full);assert.equal(mergeRunUpdate(full,null),null);
});
