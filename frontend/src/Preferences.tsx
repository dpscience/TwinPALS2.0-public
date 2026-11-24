// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import {createContext, useCallback, useContext, useMemo, useRef, useState} from 'react';
import type {Dispatch, ReactNode, SetStateAction} from 'react';
import {defaultCurveImport} from './curveText';
import type {CurveImportOptions} from './curveText';
import type {AnalysisSelection} from './m1types';

export type PlotView={x:[number,number]|null;y:[number,number]|null;hidden:string[]};
export type SceneView={transparent:boolean;camera:{position:[number,number,number];target:[number,number,number];up:[number,number,number]}|null;tree:Record<string,boolean>};
export type ViewSettings={preview_level:'crystal'|'anode';preview_origin:string;outcome_level:'crystal'|'anode';outcome_detector:'A'|'B';activity_unit:'Bq'|'uCi';detector_inset:{origin:string;contributions:boolean;tab:'current'|'map'|'persistence'|'arrivals';detector:'A'|'B';primary:AnalysisSelection['primary']};module3:import('./m3types').LifetimeViews;module2:import('./m2types').PulseViews;material_category:import('./types').MaterialCategory;material_selected:string;material_search:string;material_curve:string;last_session_paths:string[];material_editor_tab:'general'|'optical'|'emission'|'curves'|'references'|'window'|'timing'|'sampling'|'voltage'|'lifetime';dialog_paths:Record<string,string>;curve_import:CurveImportOptions;module:number;tab:string;section:string;simulation_panel:'monitoring'|'settings';simulation_section:string;simulation_sample_side:'left'|'right';sample_side:'left'|'right';selection:AnalysisSelection;analysis_paths:string[];preview_filter:Record<'interaction'|'transmission'|'miss',boolean>;preview_detector:'all'|'A'|'B';setup_details:Record<string,boolean>;scene_setup:SceneView;scene_simulation:SceneView;plots:Record<string,PlotView>};
export const defaultViews:ViewSettings={preview_level:'crystal',preview_origin:'all',outcome_level:'crystal',outcome_detector:'A',activity_unit:'Bq',detector_inset:{origin:"all",contributions:false,tab:'current',detector:'A',primary:'all'},module3:{tab:'setup',section:'Input',bin_ps:5,zero_ps:0,low_ns:-5,high_ns:50,category:'all',origin:'all',scatter:'all'},module2:{persistence_detector:'A',autoscale_voltage:false,tab:'setup',section:'inputs',panel:'monitoring',bins:120,analysis_paths:[]},material_category:'scintillator',material_selected:'bc422q-05',material_search:'',material_curve:'emission',last_session_paths:[],material_editor_tab:'general',dialog_paths:{},curve_import:defaultCurveImport,module:1,tab:'setup',section:'A',simulation_panel:'monitoring',simulation_section:'source',simulation_sample_side:'left',sample_side:'left',selection:{basis:'anode',detector:'all',primary:'all',category:'all',bins:120,suppress_zero:['energy','photon_count','mean_arrival','pulse_height']},analysis_paths:[],preview_filter:{interaction:true,transmission:false,miss:false},preview_detector:'all',setup_details:{},scene_setup:{transparent:true,camera:null,tree:{}},scene_simulation:{transparent:true,camera:null,tree:{}},plots:{}};
type Preferences={values:ViewSettings;dirty:boolean;generation:number;set:<K extends keyof ViewSettings>(key:K,value:SetStateAction<ViewSettings[K]>)=>void;restore:(value:ViewSettings)=>void;clean:(saved:ViewSettings)=>void};
const Context=createContext<Preferences|null>(null);
export function PreferencesProvider({children}:{children:ReactNode}){
 const [values,setValues]=useState(()=>structuredClone(defaultViews)),[dirty,setDirty]=useState(false),[generation,setGeneration]=useState(0),current=useRef(values);
 const set=useCallback(<K extends keyof ViewSettings,>(key:K,action:SetStateAction<ViewSettings[K]>)=>{const value=typeof action==='function'?(action as (v:ViewSettings[K])=>ViewSettings[K])(current.current[key]):action;if(JSON.stringify(value)===JSON.stringify(current.current[key]))return;current.current={...current.current,[key]:value};setValues(current.current);setDirty(true);},[]);
 const restore=useCallback((value:ViewSettings)=>{current.current=structuredClone(value);setValues(current.current);setDirty(false);setGeneration(v=>v+1);},[]);
 const clean=useCallback((saved:ViewSettings)=>setDirty(JSON.stringify(saved)!==JSON.stringify(current.current)),[]);
 const context=useMemo(()=>({values,dirty,generation,set,restore,clean}),[values,dirty,generation,set,restore,clean]);
 return <Context.Provider value={context}>{children}</Context.Provider>;
}
export function usePreferences(){const context=useContext(Context);if(!context)throw new Error('Preferences provider missing');return context;}
export function usePreference<K extends keyof ViewSettings>(key:K):[ViewSettings[K],Dispatch<SetStateAction<ViewSettings[K]>>]{const prefs=usePreferences();return [prefs.values[key],useCallback(value=>prefs.set(key,value),[key,prefs.set])];}
export function Disclosure({id,title,children,defaultOpen=false}:{id:string;title:string;children:ReactNode;defaultOpen?:boolean}){const [details,setDetails]=usePreference('setup_details');return <details open={details[id]??defaultOpen} onToggle={e=>{const open=e.currentTarget.open;setDetails(old=>({...old,[id]:open}));}}><summary>{title}</summary>{children}</details>;}
