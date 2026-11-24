// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {createContext,useCallback,useContext,useEffect,useRef,useState} from 'react';
import type {ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {AlertTriangle,X} from 'lucide-react';
import {lockBackground} from './modalInert';

type Options={title?:string;acceptLabel?:string;cancelLabel?:string|false;destructive?:boolean};
type Ask=(message:string,options?:Options)=>Promise<boolean>;
const Context=createContext<Ask|null>(null);
export function useConfirm(){const ask=useContext(Context);if(!ask)throw new Error('Confirmation provider missing');return ask;}

export function ConfirmationProvider({children}:{children:ReactNode}){
 const [request,setRequest]=useState<({message:string}&Options)|null>(null);
 const resolve=useRef<((value:boolean)=>void)|null>(null),dialog=useRef<HTMLElement>(null);
 const ask=useCallback<Ask>((message,options={})=>{
  if(resolve.current)return Promise.resolve(false);
  const verb=message.split(' ')[0];
  const label=options.acceptLabel??({Overwrite:'Replace',Replace:'Replace',Delete:'Delete',Discard:'Discard',Stop:'Stop simulation',Apply:'Apply to setup',Copy:'Copy',Remove:'Remove'}[verb]??'Continue');
  const title=options.title??({Overwrite:'Replace file?',Replace:'Replace existing data?',Delete:'Delete material?',Discard:'Discard changes?',Stop:'Stop simulation?',Apply:'Apply Module 1 settings?',Copy:'Copy detector settings?',Remove:'Remove shielding?'}[verb]??'Confirm action');
  return new Promise<boolean>(done=>{resolve.current=done;setRequest({message,title,acceptLabel:label,cancelLabel:'Cancel',destructive:['Delete','Discard','Remove'].includes(verb),...options});});
 },[]);
 const finish=useCallback((value:boolean)=>{const done=resolve.current;resolve.current=null;setRequest(null);done?.(value);},[]);
 useEffect(()=>{
  if(!request)return;
  const previous=document.activeElement as HTMLElement|null,root=document.getElementById('root'),release=lockBackground(root);
  dialog.current?.querySelector<HTMLButtonElement>('[data-cancel],.confirm-accept')?.focus();
  const key=(event:KeyboardEvent)=>{
   if(event.key==='Escape'){event.preventDefault();event.stopPropagation();finish(false);}
   if(event.key==='Tab'){
    const controls=[...dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled)')??[]],first=controls[0],last=controls.at(-1);
    if(!dialog.current?.contains(document.activeElement)){event.preventDefault();first?.focus();}
    else if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
    else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
   }
  };
  document.addEventListener('keydown',key,true);
  return()=>{
   document.removeEventListener('keydown',key,true);release();
   // The async file action re-enables its controls when the confirmation resolves.
   // Restore focus after that render; the original trigger may have lost focus
   // when it was disabled while inspecting the file.
   requestAnimationFrame(()=>{
    if(document.querySelector('[role="alertdialog"]'))return;
    if(previous?.isConnected&&!previous.closest('[inert]')&&previous.matches('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),[tabindex="0"]'))previous.focus();
    else root?.querySelector<HTMLElement>('[role="dialog"] input:not(:disabled),[role="dialog"] button:not(:disabled)')?.focus();
   });
  };
 },[request,finish]);
 return <Context.Provider value={ask}>{children}{request&&createPortal(<div className="modal-backdrop confirm-backdrop"><section ref={dialog} className="dialog confirm-dialog" role="alertdialog" aria-modal="true" aria-labelledby="confirmation-title" aria-describedby="confirmation-message"><header><h2 id="confirmation-title">{request.destructive&&<AlertTriangle size={17}/>} {request.title}</h2><button aria-label="Close confirmation" onClick={()=>finish(false)}><X size={18}/></button></header><p id="confirmation-message">{request.message}</p><div className="dialog-actions">{request.cancelLabel!==false&&<button data-cancel onClick={()=>finish(false)}>{request.cancelLabel}</button>}<button className={`confirm-accept ${request.destructive?'danger-solid':'primary'}`} onClick={()=>finish(true)}>{request.acceptLabel}</button></div></section></div>,document.body)}</Context.Provider>;
}
