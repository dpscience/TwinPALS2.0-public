// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Channel colours are shared by waveforms, input previews and acquisition stems.
export const channelColors=['#199997','#6688ca'] as const;

export type OmittedInterval={from:number;until:number;label:string};
type SvgNode={tag:string;attrs:Record<string,string|number>;text?:string};
// Dependency-free: embedded verbatim in offline reports as well as rendered in React.
export function intervalAnnotation(interval:OmittedInterval,x:number,y:number,w:number,h:number):SvgNode[]{
 const mid=x+w/2,cy=y+h/2,color='#9c793a';
 return [
  {tag:'title',attrs:{},text:`Dead time ${interval.label}. Schematic, not to scale. From ${interval.from} to ${interval.until} µs; source events continue and new triggers are ignored.`},
  {tag:'rect',attrs:{x:x+10,y,width:w-10,height:h,rx:5,fill:'#faf6ec'}},
  {tag:'path',attrs:{d:`M${x-4} ${cy-7} l8 -8 m-8 16 l8 -8`,stroke:color,'stroke-width':1.5,fill:'none'}},
  {tag:'text',attrs:{x:mid+4,y:y+14,'text-anchor':'middle',fill:color,'font-size':11},text:'Dead time'},
  {tag:'text',attrs:{x:mid+4,y:cy-4,'text-anchor':'middle',fill:color,'font-size':12,'font-weight':600},text:interval.label},
  {tag:'path',attrs:{d:`M${x+22} ${cy+6} H${x+w-12} M${x+27} ${cy+2} l-5 4 5 4 M${x+w-17} ${cy+2} l5 4 -5 4`,stroke:color,'stroke-width':1.2,fill:'none'}},
  {tag:'text',attrs:{x:mid+4,y:y+h-5,'text-anchor':'middle',fill:color,'font-size':9},text:'not to scale'}
 ];
}
