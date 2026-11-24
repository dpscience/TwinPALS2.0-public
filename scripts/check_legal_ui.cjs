// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

const assert = require('node:assert/strict');

module.exports = async function checkLicenses(run, send, until, capture) {
  await until(()=>run("!!document.querySelector('.legal-trigger')"),'License footer missing');
  const centersMatch = async (a,b) => run(`(() => {
    const mid = s => { const r=document.querySelector(s).getBoundingClientRect(); return r.top+r.height/2; };
    return Math.abs(mid(${JSON.stringify(a)})-mid(${JSON.stringify(b)})) <= 1;
  })()`);
  assert.ok(await centersMatch('.legal-trigger span','.release-version'),'Footer text alignment');
  await run("document.querySelector('.legal-trigger').click()");
  await until(()=>run("document.querySelector('.legal-text')?.textContent.includes('Permission is hereby granted')"),'MIT text missing');
  assert.ok(await run("!!document.querySelector('.legal-reading a[href=\"https://doi.org/10.25972/OPUS-37663\"]')"));
  assert.ok(await run("!!document.querySelector('.legal-reading a[href=\"mailto:twinpals@proton.me\"]')"));
  assert.ok(await run("!document.querySelector('.legal-basis a[href^=mailto]') && !!document.querySelector('.legal-contact a[href^=mailto]')"));
  assert.ok(await centersMatch('.legal-doc-choice select','.legal-doc-choice a'),'Document selector and download alignment');
  if(capture) await capture();
  async function search(value) {
    await run(`(()=>{const i=document.querySelector('.legal-search input');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,${JSON.stringify(value)});i.dispatchEvent(new Event('input',{bubbles:true}))})()`);
  }
  await search('MCP');
  await until(()=>run("document.querySelector('.legal-reading h3')?.textContent==='TwinPALS 2.0 MCP server and observer'"),'MCP project notice absent');
  assert.ok(await run("document.querySelector('.legal-reading .legal-upstream')?.textContent.includes('Protocol specification')"));
  assert.ok(await run("(()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('.legal-components button[aria-current=true]'));return range.getClientRects().length===1})()"),'MCP name wraps at desktop width');
  await search('Optical curves');
  await until(()=>run("document.querySelector('.legal-reading h3')?.textContent==='Optical curves and catalogue data'"),'Missing catalogue scope');
  assert.ok(await run("!document.querySelector('.legal-upstream')"));
  await search('G4EMLOW');
  await until(()=>run("document.querySelector('.legal-text')?.textContent.includes('NOT* FOR COMMERCIAL USE')"),'Original G4EMLOW terms missing');
  assert.equal(await run("document.querySelectorAll('.legal-components button').length"),1);
  await search('no-such-component-123');
  await until(()=>run("document.querySelector('.legal-components [role=status]')?.textContent==='No matching components.'"),'Empty search feedback missing');
  await search('CLHEP');
  await until(()=>run("!!document.querySelector('.legal-doc-choice select')"),'License document selector missing');
  await run("const select=document.querySelector('.legal-doc-choice select');select.value='1';select.dispatchEvent(new Event('change',{bubbles:true}));");
  await until(()=>run("document.querySelector('.legal-text')?.textContent.includes('GNU GENERAL PUBLIC LICENSE')"),'Second original notice missing');
  await send('Emulation.setDeviceMetricsOverride',{width:390,height:820,deviceScaleFactor:1,mobile:true});
  assert.ok(await run("document.querySelector('.legal-dialog').getBoundingClientRect().right<=innerWidth && document.querySelector('.legal-reading').clientHeight>120"));
  await send('Input.dispatchKeyEvent',{type:'keyDown',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await send('Input.dispatchKeyEvent',{type:'keyUp',key:'Escape',code:'Escape',windowsVirtualKeyCode:27});
  await until(()=>run("!document.querySelector('.legal-dialog')"),'Escape did not close legal dialog');
  await send('Emulation.setDeviceMetricsOverride',{width:1500,height:900,deviceScaleFactor:1,mobile:false});
  await run("document.querySelector('.legal-trigger').click()");
  await until(()=>run("!!document.querySelector('.legal-close')"),'Could not reopen legal dialog');
  await run("document.querySelector('.legal-close').click()");
  return ['MIT and citation','Project contact and control alignment','MCP implementation and catalogue provenance','Dataset restriction','Search and empty state','Multiple original texts','Narrow layout','Escape and Close'];
};
