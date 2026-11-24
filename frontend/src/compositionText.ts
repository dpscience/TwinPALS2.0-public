// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {percent} from './api';
import type {Entry} from './types';
const sub=(value:string)=>value.replace(/[0-9]/g,c=>'₀₁₂₃₄₅₆₇₈₉'[Number(c)]);
export function compositionText(entry:Entry){
 const p=entry.properties,parts=Object.entries((p.composition??{}) as Record<string,number>);
 if(typeof p.formula==='string'&&p.formula)return sub(p.formula);
 if(parts.length===1)return parts[0][0];
 if(parts.length&&p.composition_basis!=='mass_fraction')return parts.map(([element,amount])=>element+(amount===1?'':sub(String(Number(amount.toPrecision(7)))))).join('');
 if(parts.length)return parts.map(([element,amount])=>`${element} ${percent(amount*100)}`).join(' · ');
 return p.nist_material?String(p.nist_material):'Composition unspecified';
}
