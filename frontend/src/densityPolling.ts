// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {api,ApiError} from './api';
import type {PersistenceData} from './PersistencePlot';
import type {CathodeData} from './CathodeMap';

export type DensityBank={bins:number;processed_events?:Record<string,number>;maps:CathodeData[];persistence:PersistenceData[]};
type Bank=DensityBank;

// One prepared bank serves every inset selection. Permanent failures need a
// new source/settings selection; transient connection failures back off.
export function pollDensityBank(source:{paths?:string[];run_id?:string},bins:number,onData:(data:Bank)=>void,onError:(message:string)=>void){
 let stopped=false,since=0,delay=750,timer:ReturnType<typeof setTimeout>|undefined;
 const controller=new AbortController();
 const poll=async()=>{
  try{
   const result=await api<{data:Bank|null;version:number}>('/m1/density-bank',{method:'POST',body:JSON.stringify({...source,bins,since}),signal:controller.signal});
   if(stopped)return;
   onError('');delay=750;
   if(result.data){onData(result.data);since=result.version;}
  }catch(e){
   if(stopped)return;
   onError((e as Error).message);
   if(e instanceof ApiError&&e.status>=400&&e.status<500&&e.status!==408&&e.status!==429)return;
   delay=Math.min(30000,delay*2);
  }
  if(!stopped)timer=setTimeout(poll,delay);
 };
 void poll();
 return()=>{stopped=true;controller.abort();clearTimeout(timer);};
}
