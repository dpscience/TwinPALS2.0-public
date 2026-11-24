// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import logo from '../public/favicon.svg?raw';
export const reportIcon = '<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,'+encodeURIComponent(logo)+'">';

const titles={1:'Detector response',2:'Digitizer acquisition',3:'Lifetime analysis'} as const;

export const reportCitation = '<footer class="meta">TwinPALS 2.0 · © 2026 Danny Petschke · <a href="mailto:twinpals@proton.me">twinpals@proton.me</a><br/>Scientific basis · Dominik Boras (2024), doctoral dissertation, Universität Würzburg. <a href="https://doi.org/10.25972/OPUS-37663">10.25972/OPUS-37663</a></footer>';

export function reportHeader(module:1|2|3){
 return `<header class="page-head"><div><p class="module">TwinPALS · Module ${module}</p><h1>${titles[module]}</h1><p id="stream-name"></p></div><div class="actions"><button id="settings">Download settings</button><button id="snapshot">Download analysis data</button></div></header>`;
}

export function reportMetrics(fields:[string,string][]){
 return '<dl class="metrics">'+fields.map(([id,title])=>`<div><dt>${title}</dt><dd id="${id}"></dd></div>`).join('')+'</dl>';
}

/** Self-contained styles for the three offline reports. */
export const reportStyle = `
:root{font:14px/1.5 system-ui,sans-serif;color:#263f54;background:#f3f6f8;--line:#d7e2e9;--muted:#526c7e;--teal:#127d7e}
*{box-sizing:border-box}[hidden]{display:none!important}
body{max-width:1680px;margin:0 auto;padding:clamp(14px,2.4vw,40px)}
h1,h2,h3,p,dl,dd{margin:0}h1{font-size:clamp(23px,2.7vw,34px);line-height:1.2}h2{font-size:19px}h3{font-size:14px}
button,select,input{font:inherit;color:inherit}button,select,input[type=number]{background:white;border:1px solid #c3d3dd;border-radius:5px;padding:5px 9px}
button,select,summary,input[type=checkbox]{cursor:pointer}button:hover,summary:hover{color:var(--teal)}input{accent-color:var(--teal)}
:focus-visible{outline:2px solid var(--teal);outline-offset:2px}
.page-head,.section-head,.rail-head,.actions,.plot-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.page-head,.section-head,.rail-head{justify-content:space-between}.actions,.plot-actions{gap:6px}
.module{font-size:13px;color:var(--teal);font-weight:650;margin-bottom:4px}#stream-name{margin-top:7px;overflow-wrap:anywhere}
.meta,#stream-name,.plot-card p{color:var(--muted);font-size:12px}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:22px 0}
.metrics>div{background:white;padding:12px 16px}.metrics dt{font-size:12px;color:var(--muted)}.metrics dd{font-size:19px;font-weight:600;font-variant-numeric:tabular-nums}.metrics #status{text-transform:capitalize}
.section-head{margin:14px 0 3px}.section-head label,#path-label{display:inline-flex;align-items:center;gap:8px;font-size:12px}
.comparison{display:grid;grid-template-columns:minmax(0,1fr) minmax(245px,280px);gap:14px;align-items:start;margin:12px 0 20px}
.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
.plot-card,.comparison aside,.report-section,#acquisition section{min-width:0;background:white;border:1px solid var(--line);border-radius:8px;padding:14px}
.plot-card svg{width:100%;height:auto;display:block;margin:8px 0;touch-action:none}.plot-card p{margin:8px 0}
.plot-card details{margin-top:6px}.plot-card summary{color:var(--muted);font-size:12px}
.plot-actions{margin-top:12px}.plot-actions button,.rail-head button{font-size:11px}.inactive{background:#f8fafb}.inactive p{margin:10px 0}
.rail-head{padding-bottom:10px;border-bottom:1px solid var(--line)}.rail-head button+button{margin-left:4px}
aside>label{display:flex;gap:7px;align-items:center;margin:12px 0}#report-total{font-weight:600}aside input{margin:0;flex-shrink:0}
.report-branch{padding:9px 0;border-top:1px solid var(--line)}
.report-class{display:flex;align-items:baseline;gap:7px;border-left:3px solid;padding:3px 0 3px 8px;cursor:pointer;font-size:12px;line-height:1.45}
.report-class span{min-width:0}.report-class small{display:block;color:var(--muted);font-variant-numeric:tabular-nums}
.report-branch summary{color:var(--muted);font-size:11px;margin:4px 0 0 12px}
.report-subtypes{margin:6px 0 0 14px;display:grid;gap:6px}.report-subtypes h5{margin:3px 0 0;font-size:11px}
#selection{border-top:1px solid var(--line);padding-top:10px}.report-range{display:flex;flex-wrap:wrap;gap:6px;align-items:end;padding:8px 0}
.report-range label{display:grid;gap:2px;font-size:11px}.report-range input{width:90px}
.report-section{margin-top:10px;padding:0 16px}.report-section>summary{padding:13px 0;font-weight:600}.report-section[open]{padding-bottom:16px}
.report-section .section-head{margin:4px 0 10px}#acquisition{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}
table{width:100%;border-collapse:collapse;margin:8px 0;font-size:12px;overflow-wrap:anywhere}th,td{text-align:left;border-bottom:1px solid #e5ecf0;padding:6px 7px;vertical-align:top}th{color:var(--muted);font-weight:600}
.badge{display:inline-block;border-radius:16px;padding:3px 8px;margin:3px 4px 3px 0;font-size:11px;color:#375568;background:#eef3f6}.badge.start{color:#126966;background:#e2f2ee}.badge.stop{color:#6d5096;background:#f1ebf8}
.page-head>div,.metrics dd{min-width:0;overflow-wrap:anywhere}
.setup-figure{margin:10px 0 20px}.setup-figure img{display:block;width:100%;max-height:460px;object-fit:contain;border-radius:4px}.setup-figure img[src^="data:image/png"]{background:#ecf1f5}.setup-figure img[src^="data:image/svg"]{max-height:560px}
.histograms{margin:10px 0 20px}.histograms .plot-card{display:flex;flex-direction:column}.histograms .plot-actions{margin-top:auto;padding-top:10px}
.plot-card .legend{display:flex;flex-wrap:wrap;align-items:center;gap:6px;font-size:11px}.legend button{display:inline-flex;align-items:center;gap:5px;font-size:11px}.legend svg.line-swatch{width:25px;height:8px;display:inline;margin:0}
.plot-card>svg{user-select:none}.layer-selector{margin-top:8px;max-width:100%;font-size:12px}
.report-plot-heading{display:flex;align-items:center;gap:8px}.plot-card .report-plot-help{margin:0}.report-plot-help>summary{list-style:none;color:var(--teal);line-height:1}
.plot-card:has(.report-plot-help[open]){position:relative;z-index:1}.report-help-body{position:absolute;left:12px;right:12px;z-index:1;max-width:440px;max-height:55vh;overflow:auto;margin-top:8px;border-radius:6px;padding:10px 14px;background:#30485e;color:white;font-size:12px}.report-help-body p{color:inherit}.report-help-body ul{padding-left:18px}
.outcome-report+.outcome-report{border-top:1px solid var(--line);padding-top:14px;margin-top:16px}.outcome-report p{color:var(--muted);font-size:12px;margin:5px 0 10px}.outcome-report summary{font-size:12px}.outcome-report-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.outcome-report table :is(td,th):not(:first-child){text-align:right}
@media(max-width:660px){.outcome-report-grid{grid-template-columns:1fr}.setup-figure{padding:6px}}
@media(max-width:1100px){.comparison{grid-template-columns:1fr}.comparison aside{order:1}#classes{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:20px}}
@media(max-width:660px){.grid,#acquisition,#classes{grid-template-columns:1fr}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.page-head{align-items:flex-start}.actions{width:100%}.metrics>div{padding:9px 11px}}
@media print{body{padding:0}.actions,.plot-actions,.report-range,.rail-head button{display:none}.comparison{display:block}.comparison aside{margin-top:12px}.plot-card,#acquisition section{break-inside:avoid}.grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
`;
