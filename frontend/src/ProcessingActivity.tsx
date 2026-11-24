// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {percent} from './api';

export type Activity={active:boolean;processed?:number;total?:number;label?:string;description?:string};
export function ProcessingActivity({activity}:{activity?:Activity}){
 if(!activity?.active)return null;
 const progress=activity.total?Math.min(100,100*(activity.processed??0)/activity.total):undefined;
 return <span className="processing-activity" role="status" title={activity.description??(activity.total?`${activity.label==='≥'?'At least ':''}${(activity.processed??0).toLocaleString()} of ${activity.total.toLocaleString()} source events included in this view. Filters change the population, not this processing progress.`:'Accumulating recorded data; the displayed snapshot updates in the background.')}><span className="spinner"/>{activity.label??(progress===undefined?'Updating':'')}{progress!==undefined&&<span>{percent(progress)}</span>}</span>;
}
