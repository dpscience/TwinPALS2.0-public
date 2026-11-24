// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {displaySettings} from './lifetimeEditing';
import type {HeightViewport, LifetimeChannel, LifetimeViews, SpectrumDirection, SpectrumDisplay, SpectrumHistogram} from './m3types';

export const spectrumNames:Record<SpectrumDirection,string>={merged:'Merged',AB:'A → B',BA:'B → A',SS:'Stop–Stop'};
export const spectrumRoles:Record<SpectrumDirection,string>={merged:'A → B + B → A',AB:'Start A · Stop B',BA:'Start B · Stop A',SS:'Stop A · Stop B'};
export const spectrumHelp:Record<SpectrumDirection,string>={
 merged:'Both Start–Stop assignments contribute once. Each channel’s recorded cable delay is subtracted before the Stop time minus Start time is binned. Merged has its own reset. Stop–Stop is a separate coincidence reference.',
 AB:'Stop B minus Start A, after subtracting the recorded cable delay from each channel time.',
 BA:'Stop A minus Start B, after subtracting the recorded cable delay from each channel time.',
 SS:'Stop B minus Stop A, after subtracting the recorded cable delay from each channel time. This coincidence reference is separate from Merged.'
};
export function spectrumDisplay(views:LifetimeViews,dir:SpectrumDirection):SpectrumDisplay{
 const saved=views.analysis?.displays[dir] as (SpectrumDisplay&{boras_overlays?:string[]})|undefined;
 if(!saved)return {...displaySettings(views),phs_bins:views.monitor?.phs_bins??[512,512],log_scale:true};
 if(!saved.boras_overlays)return saved;
 const {boras_overlays,...display}=saved;
 return {...display,subtype_overlays:display.subtype_overlays??boras_overlays};
}
/** Visibility, focus and hover are local to the plots. Fetch all seven disjoint layers once per snapshot. */
export function spectrumQuery(v:SpectrumDisplay){
 return {low_ns:v.low_ns,high_ns:v.high_ns,bin_ps:v.bin_ps,zero_ps:v.zero_ps,phs_bins:v.phs_bins,origin:v.origin,scatter:v.scatter,individual:true};
}
export function heightDomain(view:HeightViewport|undefined,channel:LifetimeChannel,adc:number):[number,number]{
 if(view?.mode==='custom'&&view.limits){
  const lo=Math.max(0,view.limits[0]),hi=Math.min(adc,view.limits[1]);
  if(lo<hi)return [lo,hi];
 }
 if(view?.mode==='start'||view?.mode==='stop'){
  const {low,high}=channel[view.mode].phs,margin=(high-low)*.09;
  const left=Math.max(0,low-margin),right=Math.min(adc,high+margin);
  if(left<right)return [left,right];
 }
 return [0,adc];
}
/** Render a single SVG path per trace. Occupied bins sharing a screen pixel still keep their separate numeric counts. */
export function spectrumCirclePath(points:[number,number][],sx:(x:number)=>number,sy:(y:number)=>number,low:number,high:number,r:number){
 const glyph='a'+r+' '+r+' 0 1 0 '+2*r+' 0a'+r+' '+r+' 0 1 0 '+(-2*r)+' 0z';
 const seen=points.length>2000?new Set<string>():null;
 let path='';
 for(const [x,y] of points){
  if(x<low||x>high||y<=0)continue;
  const px=sx(x),py=sy(y);
  if(seen){const pixel=Math.round(px)+','+Math.round(py);if(seen.has(pixel))continue;seen.add(pixel);}
  path+='M'+(px-r).toFixed(2)+' '+py.toFixed(2)+glyph;
 }
 return path;
}
export function spectrumStepPath(points:[number,number][],sx:(x:number)=>number,sy:(y:number)=>number,low:number,high:number,base:number,width:number){
 let path='',previous=-Infinity;
 const baseline=sy(base).toFixed(2);
 for(const [x,count] of points){
  const left=x-width/2,right=x+width/2;
  if(right<low||left>high)continue;
  if(left-previous>width*.01)path+=(path?'V'+baseline:'')+'M'+sx(left).toFixed(2)+' '+baseline;
  path+='V'+sy(count).toFixed(2)+'H'+sx(right).toFixed(2);
  previous=right;
 }
 return path?path+'V'+baseline:'';
}
/** Sum disjoint bins. A selected parent already contains every selected child. Also embedded in offline reports. */
export function superimposedBins(hist:SpectrumHistogram, selected:Iterable<string>, parentOf:(key:string)=>string|undefined):[number,number][] {
 const keys=new Set(selected);
 const counts=new Map<number,number>();
 for(const key of keys){
  const parent=parentOf(key);
  if(parent && keys.has(parent))continue;
  const bins=hist.layers[key]??hist.sublayers?.[key];
  if(bins)for(const [index,n] of bins)counts.set(index,(counts.get(index)??0)+n);
 }
 return [...counts.entries()].sort(([a],[b])=>a-b);
}

export function fitTimeRange(extent:[number,number],bin:number){
 const width=Math.max(bin,Math.ceil((extent[1]-extent[0])*1000/99996)),step=width/1000;
 return {bin_ps:width,low_ns:Math.floor(extent[0]/step-1)*step,high_ns:Math.ceil(extent[1]/step+1)*step};
}
