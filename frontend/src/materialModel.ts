// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {Entry,MaterialCategory,Curve} from './types';
export const categories:Record<MaterialCategory,string>={scintillator:'Scintillators',coupling:'Coupling',window:'Windows',pmt:'Photomultipliers',digitizer:'Digitizers',wrapping:'Wrapping',sample:'Sample materials',foil:'Encapsulation foils',shield:'Shielding materials'};
export const categoryHelp:Record<MaterialCategory,string>={scintillator:'Light production and optical transport inside each crystal.',coupling:'Optical material between crystal and entrance window.',window:'Bulk material of the detector entrance window.',pmt:'Complete PMT: entrance window, photocathode, vacuum tube and timing.',digitizer:'Sampling, voltage and time response of the acquisition hardware.',wrapping:'Material and optical reflection model around the crystal.',sample:'Materials of the independent left and right samples.',foil:'Materials of the two source-encapsulation foils.',shield:'Materials of the optional shielding blocks.'};
export const elements='H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split(' ');
export type Component={curve:string;fraction:number;rise_time_ns:number;decay_time_ns:number;name?:string};
export const curveLabels:Record<string,string>={cathode_n:'Cathode refractive index n',cathode_k:'Cathode extinction coefficient k',gain_hv:'Gain versus HV',refractive_index:'Refractive index',absorption_length:'Absorption length',quantum_efficiency:'Quantum efficiency',reflectivity:'Reflectivity',emission:'Emission spectrum',emission_fast:'Fast emission',emission_slow:'Slow emission'};
export const curveLabel=(name:string)=>curveLabels[name]??name.replaceAll('_',' ').replace(/^./,c=>c.toUpperCase());
export function newCurve(name:string,value=1):Curve{return {name,x_unit:name==='gain_hv'?'V':'nm',y_unit:name==='absorption_length'?'mm':name.startsWith('emission')?'relative':'1',semantics:name.startsWith('emission')?'Relative photon-density spectrum per wavelength':'Pointwise physical property',points:name==='gain_hv'?[[1000,1e4],[3000,1e6]]:name.startsWith('emission')?[[300,0],[370,1],[500,0]]:[[200,value],[700,value]]};}
export function newEntry(category:MaterialCategory):Entry{
 const properties:Record<string,unknown>=category==='pmt'?{qe_reference_plane:'intrinsic_cathode'}:{density_g_cm3:1,composition_basis:'atoms',composition:{C:1}};
 let curves:Curve[]=[];
 if(category==='pmt')Object.assign(properties,{window_shape:'circle',window_diameter_mm:52,window_width_mm:40,window_height_mm:40,window_thickness_mm:2,photocathode_shape:'circle',photocathode_diameter_mm:46,photocathode_width_mm:40,photocathode_height_mm:40,cathode_gap_mm:0,tube_diameter_mm:52,tube_length_mm:121});
 if(category==='pmt')properties.window_material={...newEntry('window'),name:'Window glass'};
 if(category==='digitizer'){Object.keys(properties).forEach(k=>delete properties[k]);Object.assign(properties,{architecture:'uniform_adc',adc_bits:14,voltage_min_mV:-500,voltage_max_mV:500,baseline_mV:0,input_bandwidth_MHz:0,input_impedance_ohm:50,default_rate:5,default_samples:1024,default_dead_ns:0,default_fixed_jitter_ps:0,default_random_jitter_ps:0,default_irf_sigma_ps:0,default_noise_sigma_mV:0,cell_alternation_ps:0});}
 if(['scintillator','coupling','window'].includes(category))Object.assign(properties,{optical_extrapolation:'constant'});
 if(category==='scintillator')Object.assign(properties,{resolution_scale:1,birks_mm_per_MeV:0,spectral_interpretation:'photon_density_per_wavelength',components:[]});
 if(category==='wrapping')Object.assign(properties,{model:'unified',finish:'ground',reflectivity:.95,sigma_alpha_rad:.1});
 return {id:`custom-${crypto.randomUUID().slice(0,12)}`,revision:1,name:'New '+categories[category].toLowerCase().replace(/s$/,''),category,builtin:false,description:'',provenance:{references:[]},properties,curves};
}
