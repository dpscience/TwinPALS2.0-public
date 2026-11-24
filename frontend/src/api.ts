// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

let clientToken='';
let closeState:(()=>unknown)|null=null;
export function setCloseState(value:(()=>unknown)|null){closeState=value;}
export function connectClient(update:(state:'ready'|'busy'|'disconnected')=>void){
 const source=new EventSource('/api/client/connect');
 const close=()=>{if(clientToken)navigator.sendBeacon('/api/client/close',new Blob([JSON.stringify({token:clientToken,state:closeState?.()})],{type:'application/json'}));source.close();clientToken='';};
 source.onmessage=e=>{const message=JSON.parse(e.data);if(message.type==='ready'){clientToken=message.token;update('ready');}else if(message.type==='busy'){source.close();update('busy');}};
 source.onerror=()=>{source.close();clientToken='';update('disconnected');};
 window.addEventListener('pagehide',close);
 return()=>{window.removeEventListener('pagehide',close);close();};
}
export class ApiError extends Error {
 constructor(public status:number,message:string){super(message);this.name='ApiError';}
}
export async function api<T>(path:string, init?:RequestInit):Promise<T> {
  const response = await fetch(`/api${path}`, {...init,headers:{'X-TwinPALS-Client':clientToken,...(init?.body && !(init.body instanceof FormData)?{'Content-Type':'application/json'}:{}),...init?.headers}});
  if(!response.ok){const data=await response.json().catch(()=>null);const detail=data?.detail??data?.message??response.statusText;throw new ApiError(response.status,typeof detail==='string'?detail:JSON.stringify(detail));}
  return response.json() as Promise<T>;
}
export function downloadJson(value:unknown,name:string){const url=URL.createObjectURL(new Blob([JSON.stringify(value,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
export function number(value:number|undefined,digits=0){return Number.isFinite(value)?new Intl.NumberFormat('en-GB',{maximumFractionDigits:digits}).format(value!):'—';}
export function percent(value:number){return Number.isFinite(value)?value.toLocaleString('en-GB',{minimumFractionDigits:2,maximumFractionDigits:2})+'%':'—';}
export function duration(value:number|null|undefined){if(value==null||!Number.isFinite(value))return 'Estimating';if(value<60)return `${Math.ceil(value)} s`;if(value<3600)return `${Math.floor(value/60)}m ${Math.ceil(value%60)}s`;return `${Math.floor(value/3600)}h ${Math.floor(value%3600/60)}m`;}
