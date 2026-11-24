// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

export type Range = [number, number];
// Store a live timeline zoom relative to its current trigger. The source clock
// can advance by seconds without moving the viewed offset within a window.
export const shiftRange=(r:Range,origin:number):Range=>[r[0]+origin,r[1]+origin];
export function wheelRange(r:Range,position:number,direction:number):Range {
 const factor=Math.exp(Math.sign(direction)*Math.log(1.2));
 const centre=r[0]+Math.max(0,Math.min(1,position))*(r[1]-r[0]);
 return [centre+(r[0]-centre)*factor,centre+(r[1]-centre)*factor];
}
type Series = {points: [number, number][]};

// Fit rendered line segments, not only vertices: a constant two-point curve
// still crosses a zoom window that contains neither endpoint.
export function plotRanges(series: Series[], markers: {x:number}[], view: {x:Range|null;y:Range|null}) {
 const valid = (r: Range | null | undefined): r is Range => !!r && r.every(Number.isFinite) && r[1] > r[0];
 let low=Infinity,high=-Infinity;
 for(const s of series)for(const [x,y] of s.points)if(Number.isFinite(x)&&Number.isFinite(y)){low=Math.min(low,x);high=Math.max(high,x);}
 for(const m of markers)if(Number.isFinite(m.x)){low=Math.min(low,m.x);high=Math.max(high,m.x);}
 const extent:Range=Number.isFinite(low)?[low,high>low?high:low+1]:[0,1];
 const usableX=valid(view.x)&&view.x[1]>=extent[0]&&view.x[0]<=extent[1];
 const x:Range=usableX?view.x!:extent;
 let ymin=Infinity,ymax=-Infinity;
 const add=(y:number)=>{if(Number.isFinite(y)){ymin=Math.min(ymin,y);ymax=Math.max(ymax,y);}};
 for(const s of series)for(let i=0;i<s.points.length;i++){
  const [px,py]=s.points[i];if(px>=x[0]&&px<=x[1])add(py);
  if(!i)continue;const [ax,ay]=s.points[i-1];
  if(px===ax)continue;
  for(const edge of x)if(edge>Math.min(ax,px)&&edge<Math.max(ax,px))add(ay+(py-ay)*(edge-ax)/(px-ax));
 }
 const fit:Range=Number.isFinite(ymin)?[Math.min(0,ymin*1.08),Math.max(0,ymax)*1.08]:[0,1.08];
 if(fit[0]===fit[1])fit[1]=fit[0]+1;
 const usableY=(!view.x||usableX)&&valid(view.y)&&(!Number.isFinite(ymin)||view.y[1]>=ymin&&view.y[0]<=ymax);
 return {x,y:usableY?view.y!:fit};
}

// Shared by the live chart and the standalone report. Panel backgrounds and
// clipping use these same rectangles, leaving the separator completely white.
export function plotPanels(labels:string[]|undefined, ranges:Range[]|undefined, fallback:Range, top:number, height:number, requestedGap=0) {
 const names=labels?.length?labels:[''];
 const gap=Math.max(0,Math.min(requestedGap,height/(2*names.length)));
 const rowHeight=(height-gap*(names.length-1))/names.length;
 return names.map((label,index)=>{
  const range=ranges?.[index]??fallback;
  const span=range[1]-range[0],rough=span/(rowHeight<60?1:rowHeight<150?2:4);
  const scale=10**Math.floor(Math.log10(rough));
  const step=[1,2,2.5,5,10].map(v=>v*scale).reduce((a,b)=>Math.abs(a-rough)<Math.abs(b-rough)?a:b);
  const ticks:number[]=[];
  for(let n=Math.ceil(range[0]/step);n*step<=range[1]+span*1e-9;n++)ticks.push(Number((n*step).toPrecision(12)));
  if(!ticks.length||ticks[0]-range[0]>step*.4)ticks.unshift(range[0]);
  if(range[1]-ticks[ticks.length-1]>step*.4)ticks.push(range[1]);
  return {label,range,top:top+index*(rowHeight+gap),height:rowHeight,ticks};
 });
}
