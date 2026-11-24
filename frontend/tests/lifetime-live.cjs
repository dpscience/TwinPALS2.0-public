// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

const assert = require('node:assert/strict');
const {test} = require('node:test');
const fs = require('node:fs');
const ts = require('typescript');
require.extensions['.ts'] = (module, filename) => module._compile(
  ts.transpileModule(fs.readFileSync(filename, 'utf8'), {compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022
  }}).outputText, filename);
const {classKeys, chosenClasses, diagnosticFraction, displaySettings, gateError, moveEdge} = require('../src/lifetimeEditing.ts');

const {spectrumDisplay, fitTimeRange, heightDomain, spectrumQuery, spectrumCirclePath} = require('../src/spectrumAnalysis.ts');

test('each direction inherits a legacy display until it has its own stored controls', () => {
  const base = {bin_ps:12,zero_ps:100,low_ns:-3,high_ns:8,category:'all',origin:'all',scatter:'all'};
  const merged = spectrumDisplay(base,'merged');
  const views = {...base,analysis:{direction:'AB',displays:{AB:{...merged,bin_ps:50,phs_bins:[97,513]}}}};
  assert.equal(spectrumDisplay(views,'BA').bin_ps,12);
  assert.equal(spectrumDisplay(views,'AB').bin_ps,50);
  assert.deepEqual(spectrumDisplay(views,'merged').phs_bins,[512,512]);
  views.analysis.displays.AB.boras_overlays=['bc511'];
  assert.deepEqual(spectrumDisplay(views,'AB').subtype_overlays,['bc511']);
  assert.ok(!('boras_overlays' in spectrumDisplay(views,'AB')));
});

test('full range includes single-bin, negative and very distant cable-corrected populations', () => {
  for(const [lo,hi] of [[0,0],[-5.125,-.11],[-1000200,1000200],[.99,1]]) {
    const fit = fitTimeRange([lo,hi],5);
    assert(fit.low_ns<=lo && fit.high_ns>hi);
    assert(Math.ceil((fit.high_ns-fit.low_ns)*1000/fit.bin_ps)<=100000);
  }
});


test('superimposed bins count each selected pair once, including subtype-only selections', () => {
  const {superimposedBins,spectrumQuery}=require('../src/spectrumAnalysis.ts');
  const hist={bins:[[0,100]],layers:{ideal:[[3,5],[0,4]],random:[[0,2]]},sublayers:{ab:[[0,1],[3,2]],ba:[[0,3],[3,3]]}};
  const parent=k=>['ab','ba'].includes(k)?'ideal':undefined;
  assert.deepEqual(superimposedBins(hist,['ab','ba','random'],parent),[[0,6],[3,5]]);
  assert.deepEqual(superimposedBins(hist,['ideal','ab','ab','random'],parent),[[0,6],[3,5]]);
  assert.deepEqual(superimposedBins(hist,['ab'],parent),[[0,1],[3,2]]);
  assert.deepEqual(superimposedBins(hist,['superimposed','total'],parent),[]);
  assert.deepEqual(spectrumQuery({show_superimposed:true}),spectrumQuery({show_superimposed:false}));
});

function channel() {
  const window = (low, high) => ({
    phs: {low, high},
    area: {enabled: false, slope: 1, intercept: 0, below: 2, above: 2},
    shape: {enabled: false, rise: 2, fall: 4, radius_rise: 1, radius_fall: 2, angle_deg: 0}
  });
  return {median_samples: 1, cfd_percent: 25, baseline_samples: 16, minimum_height_mV: 1, start: window(100, 300), stop: window(10, 100)};
}

test('height focus follows live gates while a custom axis and trace visibility leave histogram inputs alone', () => {
  const c=channel(), v={low_ns:-2,high_ns:3,bin_ps:10,zero_ps:0,phs_bins:[64,32],origin:'all',scatter:'all'};
  assert.deepEqual(heightDomain(undefined,c,500),[0,500]);
  assert.deepEqual(heightDomain({mode:'start'},c,500),[82,318]);
  c.stop.phs={low:8,high:28};
  assert.deepEqual(heightDomain({mode:'stop'},c,500),[6.2,29.8]);
  assert.deepEqual(heightDomain({mode:'custom',limits:[10,20]},c,500),[10,20]);
  assert.deepEqual(spectrumQuery(v),spectrumQuery({...v,categories:[],individual:false,show_total:false,phs_views:[{mode:'stop'},{mode:'full'}]}));
  assert.deepEqual(spectrumQuery({...v,time_view:[-1,1]}),spectrumQuery(v));
  const glyphs=spectrumCirclePath([[-2,5],[1,3],[2,0],[3,1]],x=>x,y=>10-y,0,4,2);
  assert.equal((glyphs.match(/M/g)||[]).length,2);assert.equal((glyphs.match(/a2 2/g)||[]).length,4);
  assert(!/[VHL]/.test(glyphs));
});

test('touching PHS handles honour the neighbouring window in either order', () => {
  const c = channel();
  assert.equal(moveEdge(c, 'stop', 'high', 180), 100);
  assert.equal(moveEdge(c, 'start', 'low', 16), 100);
  assert.equal(moveEdge(c, 'stop', 'low', -8), 0);
  assert.equal(moveEdge(c, 'start', 'high', 80), 100.01);
  assert.equal(gateError([c]), '');
  c.stop.phs.high++;
  assert.match(gateError([c]), /overlap/);
  c.stop.phs.high--; c.median_samples = 2;
  assert.match(gateError([c]), /odd/);
});

test('live gate feedback uses the inclusive lower edge, exclusive upper edge and both cuts', () => {
  const c = channel(); c.start.area.enabled = c.start.shape.enabled = true;
  const area = [[100, 100], [180, 185], [185, 186], [300, 300]];
  const shape = [[2, 4, 100], [2, 4, 180], [4, 4, 185], [2, 4, 300]];
  assert.deepEqual(diagnosticFraction(area, shape, c, 'start'), {window: 3, passes: 1});
  c.start.shape.angle_deg = 90;
  assert.deepEqual(diagnosticFraction(area, shape, c, 'start'), {window: 3, passes: 2});
});

test('old single-class settings, empty selection and a saved class mix stay distinct', () => {
  assert.deepEqual(chosenClasses({category: 'all'}), classKeys);
  assert.deepEqual(chosenClasses({category: 'accidental'}), ['accidental']);
  for (const categories of [[], ['correlated','accidental']]) {
    const view = {category: 'all', categories, individual: true, origin: 'all', scatter: 'none'};
    assert.deepEqual(chosenClasses(displaySettings(view)), categories);
    assert.equal(displaySettings(view).individual, true);
  }
});
