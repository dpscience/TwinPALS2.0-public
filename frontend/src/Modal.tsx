// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect,useRef} from 'react';
import type {ReactNode} from 'react';
import {createPortal} from 'react-dom';
import {X} from 'lucide-react';
import {lockBackground} from './modalInert';

export function Modal({title,close,children,busy=false,error='',wide=false}:{title:string;close:()=>void;children:ReactNode;busy?:boolean;error?:string;wide?:boolean}){
 const layer=useRef<HTMLDivElement>(null),latest=useRef({close,busy});latest.current={close,busy};
 useEffect(()=>{
  const previous=document.activeElement as HTMLElement|null,release=lockBackground(document.getElementById('root'));
  layer.current?.querySelector<HTMLElement>('input,select,button')?.focus();
  const key=(e:KeyboardEvent)=>{
   if(document.querySelector('[role="alertdialog"]'))return;
   if(e.key==='Escape'){e.preventDefault();e.stopPropagation();if(!latest.current.busy)latest.current.close();}
   if(e.key==='Tab'){
    const list=[...layer.current?.querySelectorAll<HTMLElement>('button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href],[tabindex="0"]')??[]].filter(x=>x.getClientRects().length);
    const first=list[0],last=list.at(-1);
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}
    else if(!e.shiftKey&&document.activeElement===last||!layer.current?.contains(document.activeElement)){e.preventDefault();first?.focus();}
   }
  };
  document.addEventListener('keydown',key,true);
  return()=>{document.removeEventListener('keydown',key,true);release();requestAnimationFrame(()=>{if(previous?.isConnected&&!previous.closest('[inert]'))previous.focus();});};
 },[]);
 return createPortal(<div ref={layer} className="modal-backdrop material-modal"><section className={`dialog ${wide?'dialog-wide':''}`} role="dialog" aria-modal="true" aria-label={title} aria-busy={busy}><header><h2>{title}</h2><button aria-label="Close dialog" disabled={busy} onClick={close}><X size={18}/></button></header>{error&&<div className="error-box dialog-error" role="alert">{error}</div>}{children}</section></div>,document.body);
}
