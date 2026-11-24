// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Dialogs can close in either order; the background stays locked until the last
// owner releases it. Restoring each dialog's snapshot can leave the app inert.
const locks = new WeakMap<HTMLElement, {count:number; previous:boolean}>();
export function lockBackground(element:HTMLElement|null):()=>void {
 if(!element)return ()=>{};
 const state=locks.get(element)??{count:0,previous:element.inert};
 state.count++;locks.set(element,state);element.inert=true;
 let released=false;
 return ()=>{if(released)return;released=true;if(--state.count===0){element.inert=state.previous;locks.delete(element);}};
}
