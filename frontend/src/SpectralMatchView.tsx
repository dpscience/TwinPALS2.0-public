// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {useEffect,useState} from 'react';
import {api} from './api';
import {Field} from './Fields';
import {Plot} from './Plot';
import type {PlotData} from './Plot';
import {photocathodeSpectrum,spectralMatch} from './spectralMatch';
import type {Entry} from './types';

type Point=[number,number,number,number];

export function SpectralMatchView({detector,scint,pmt,reflections}:{detector:string;scint?:Entry;pmt?:Entry;reflections:boolean}){
 const [view,setView]=useState('emission');
 const [rows,setRows]=useState<Point[]>([]);
 const [error,setError]=useState('');
 const film=view==='film'&&reflections;
 useEffect(()=>{
  let current=true;
  setRows([]);setError('');
  if(film&&pmt)api<Point[]>('/m1/cathode-optics',{method:'POST',body:JSON.stringify(pmt)})
   .then(v=>{if(current)setRows(v);}).catch(e=>{if(current)setError(e.message);});
  return ()=>{current=false;};
 },[film,pmt]);
 const data:PlotData=film?photocathodeSpectrum(rows,scint):spectralMatch(scint,pmt);
 return <>{reflections&&<Field label="Spectrum" help="Compare crystal emission with tube QE, or inspect light at the film surface."><select value={view} onChange={e=>setView(e.target.value)}><option value="emission">Emission and QE</option><option value="film">Photocathode optics</option></select></Field>}
 {film&&error?<p className="inline-error">{error}</p>:<Plot compact preview preferenceKey={`match.${detector}.${scint?.id}.${pmt?.id}${film?'.film':''}`} data={data}/>}</>;
}
