// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {M1Run} from './m1types';
export type RunUpdate=M1Run&{trajectory_order?:string[];trajectory_revision?:number};
const key=(t:M1Run['trajectories'][number])=>`${t.role}:${t.event_id}`;

// Merge transport deltas before publishing React state. Components receive
// the same complete preview list, including its original order and evictions.
export function mergeRunUpdate(previous:RunUpdate|null,next:RunUpdate|null):RunUpdate|null{
 if(!next||!next.trajectory_order)return next;
 if(previous?.id!==next.id)throw new Error('Preview snapshot required');
 const known=new Map(previous.trajectories.map(t=>[key(t),t]));
 for(const t of next.trajectories)known.set(key(t),t);
 const trajectories=next.trajectory_order.map(id=>{const t=known.get(id);if(!t)throw new Error('Preview snapshot required');return t;});
 const {trajectory_order:_,...snapshot}=next;
 return {...snapshot,trajectories};
}
