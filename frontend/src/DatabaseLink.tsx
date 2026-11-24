// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {ArrowUpRight} from 'lucide-react';
import {usePreferences} from './Preferences';
import type {MaterialCategory} from './types';
export function DatabaseLink({id,category}:{id:string;category:MaterialCategory}){const prefs=usePreferences();return <button type="button" className="database-link" title="Open this entry in the database" aria-label="Open selected database entry" onClick={()=>{prefs.set('material_category',category);prefs.set('material_selected',id);prefs.set('material_search','');prefs.set('module',4);}}><ArrowUpRight size={15}/></button>;}
