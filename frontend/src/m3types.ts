// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

export type LifetimeGate={phs:{low:number;high:number};area:{enabled:boolean;slope:number;intercept:number;below:number;above:number};shape:{enabled:boolean;rise:number;fall:number;radius_rise:number;radius_fall:number;angle_deg:number}};
export type LifetimeChannel={polarity:'negative'|'positive';interpolation?:'linear'|'cubic'|'akima';intra_steps?:number;cfd_percent:number;baseline_samples:number;baseline_mode?:'readout'|'pre_pulse';baseline_gap?:number;median_samples:number;minimum_height_mV:number;reject_clipped:boolean;start:LifetimeGate;stop:LifetimeGate};
export type LifetimeProfile={format:'twinpals-module3';version:1;input_paths:string[];pulse_selection?:'first'|'highest';channels:LifetimeChannel[];workers:number;preview_count:number};
export type SpectrumDirection='merged'|'AB'|'BA'|'SS';
export type HeightViewport={mode:'full'|'start'|'stop'|'custom';limits?:[number,number]|null};
export type SpectrumDisplay={show_total?:boolean;show_superimposed?:boolean;subtype_overlays?:string[];phs_views?:[HeightViewport,HeightViewport];time_view?:[number,number]|null;bin_ps:number;zero_ps:number;low_ns:number;high_ns:number;category:string;categories?:string[]|null;individual?:boolean;origin:string;scatter:string;phs_bins:[number,number];log_scale:boolean};
export type SpectrumAnalysis={direction:SpectrumDirection;displays:Partial<Record<SpectrumDirection,SpectrumDisplay>>};
export type SpectrumHistogram={bins:[number,number][];counts:number;sublayers?:Record<string,[number,number][]>;layers:Record<string,[number,number][]>};
export type SpectrumStage={lifetime:SpectrumHistogram;phs:SpectrumHistogram[];subclasses?:Record<string,number>;classes:Record<string,number>};
export type SpectrumComparison={extent:[number,number]|null;filter_active:boolean;gated_pairs:number;stages:[SpectrumStage,SpectrumStage]};
export type AnalysisData=LifetimeJob & {comparisons:Partial<Record<SpectrumDirection,SpectrumComparison>>;categories:string[];cable_delays_ns:(number|null)[];adc_heights:number[]};
export type LifetimeViews={analysis?:SpectrumAnalysis;tab:'setup'|'analysis';monitor?:MonitorView;section:string;bin_ps:number;zero_ps:number;low_ns:number;high_ns:number;category:string;categories?:string[]|null;individual?:boolean;origin:string;scatter:string};
export type LifetimeJob={id:string;stream_id:string|null;status:string;error:string;processed:number;total_processed:number;accepted:number;rejected:Record<string,number>;epoch:number;file_index:number;file_sizes:number[];file_pairs:number[];bytes_read:number;spectrum_first:number[];revision:number;pending:boolean;revision_first:number;progress:number;elapsed:number;eta_s:number|null;estimated_finish:string|null;preview_generation:number;measurement_ns:number;preview:{sequence:number;id:number;direction:string|null;category:string}[];profile:LifetimeProfile};
export type PHS={channel:string;step_mV:number;before:number[];accepted:number[];measured:number;selected:number;overflow?:number[]};
export type Contribution={category:string;points:[number,number][];counts:number};
export type LifetimeData=LifetimeJob & {plots:MeasurementGrid[];spectra:{direction:string;points:[number,number][];counts:number;contributions:Contribution[]}[];diagnostics:{channel:string;area:[number,number][];shape:[number,number,number][]}[];categories:string[];category_counts:Record<string,number>;origins:string[];phs:PHS[];revision:number;epoch_start:number;pending:boolean;history:{revision:number;epoch?:number;first:number;last:number;processed:number;accepted:number;reason:string}[];note:string};
export type LifetimeFeature={valid:boolean;reason:string;baseline:number;baseline_region?:{count:number;start_ns:number;end_ns:number};noise:number;height:number;peak_ns:number;cfd_ns:number;cfd_percent?:number;cfd_level_mV?:number;rise_ns:number|null;fall_ns:number|null;area:number;t10?:number|null;t90?:number|null;f90?:number|null;f10?:number|null;support:[number,number]};
export type PulseRoute={detector:string;primary:number;count:number;cathode_arrival_ns?:[number,number];by_cf?:Record<string,number>;steps:{component:string;process:string;angle_deg:number|null;backscatter:boolean}[];origin:string;birth:string;birth_volume?:string};
export type WaveTransport={role:number;record:number;volumes?:string[];paths?:PulseRoute[];provenance?:{crystal?:{routes?:{detector:string;primary:number;visits:string[];count:number}[]};anode?:{routes?:{detector:string;primary:number;visits:string[];count:number}[]}}};
export type LifetimeWave={primary_roles:string[];revision:number;sequence:number;id:number;direction:string|null;dt_ns:number|null;features:LifetimeFeature[];gates:[string|null,string][];samples:number[][];truth:{category:string;subtype?:string|null;annihilation_path?:string|null;prompt_path?:string|null;origin:string;attribution:string;selected:{channel:number;role:number;record:number;decay:number;onset_ns:number;light_origin:string}[][]};transport_truth:WaveTransport[]};
export const plotDelayMs=1250;
export const lifetimeActive=(j:LifetimeJob|null)=>!!j&&['running','pausing','stopping'].includes(j.status);
export const primaryLabels:Record<string,string>={na22_prompt:'1275 keV',na22_annihilation:'511 keV (pair)',co60_1173:'1173 keV',co60_1332:'1332 keV'};
export const categoryNames:Record<string,string>={correlated:'Same decay · different gamma roles',annihilation_pair:'Same annihilation · two 511 keV photons',same_primary:'Same gamma in A and B',accidental:'Accidental background',pileup_same_decay:'Pile-up · same decay',pileup_multiple_decays:'Pile-up · multiple decays',unresolved:'Unresolved provenance'};
export const categoryHelp:Record<string,string>={
 correlated:'One contributor in each channel, both from the same decay with different emitted gamma roles.',
 annihilation_pair:'One contributor per channel from the same Na-22 decay. Both are in the annihilation role and their recorded primary IDs identify different 511 keV gammas.',
 same_primary:'One contributor per channel from the same decay and gamma role. Each traces back to the same single primary gamma.',
 accidental:'One contributor per channel. The two contributors have different recorded source decay IDs.',
 pileup_same_decay:'Two or more transport responses reach the selected pulse in one channel. The partner channel also has a response, and all matched responses carry the same source decay ID.',
 pileup_multiple_decays:'Two or more transport responses reach the selected pulse in one channel. The partner channel also has a response, and at least two decay IDs occur across the pair.',
 unresolved:'A selected pulse has no contributor overlapping its measured time support, or the available gamma ancestry cannot resolve the class.'
};
export const gateReason=(text:string)=>text.replaceAll('CF'+'D','CF').replaceAll('Incomplete leading or trailing edge','Missing leading CF crossing');
export type Axes=[number,number,number,number];
export type DensityView={nx:number;ny:number;axes:Axes|null};
export type FitPercentiles={low:number;high:number};
export type ShapeFit=FitPercentiles & {fence:number;coverage:number};
export const defaultAreaFit:FitPercentiles={low:2.5,high:97.5};
export const defaultShapeFit:ShapeFit={low:25,high:75,fence:1.5,coverage:95};
export type ShapeFitCount={inside:number;total:number;first:number;signature:string};
export type MonitorView={filter_kind:'area'|'shape';plots:Record<string,DensityView>;traces:[boolean,boolean];autoscale:[boolean,boolean];show_baseline:boolean|[boolean,boolean];phs_bins:[number,number];area_fit?:Record<string,FitPercentiles>;shape_fit?:Record<string,ShapeFit>};
export function baselineRegions(value:MonitorView['show_baseline']):[boolean,boolean]{return Array.isArray(value)?[...value]:[value,value];}
export const defaultMonitor:MonitorView={filter_kind:'area',plots:{},traces:[false,false],autoscale:[false,false],show_baseline:false,phs_bins:[512,512]};
export type MeasurementGrid={kind:'phs'|'area'|'shape';channel:number;role:'start'|'stop';nx:number;ny:number;axes:Axes;diagonal_axes?:Axes|null;fixed?:boolean;max_cell?:number;cells_from?:number;cells:[number,number][];total:number;visible:number;incomplete?:number;above_adc?:number;windows:number[];first:number};
export type Adc={low:number;high:number;height:number;baseline:number;polarity:'negative'|'positive'};
export type RecordedApparatus={source:Record<string,string>;detectors:Partial<Record<'A'|'B',Record<string,string>>>;instrument?:Partial<Record<'A'|'B',Record<string,string>>>};
export type TransportInput={path:string;role:string|null;setup?:import('./m1types').Profile;entries?:Pick<import('./types').Entry,'id'|'name'|'properties'>[];maximum_mV?:number[]|null;apparatus?:RecordedApparatus};
export type SourceStream={path:string;name:string;stream_id:string;run_id:string;class_filter:string;bytes:number;partial:boolean;source:string;activity_Bq:number;created_utc:string;adc:Adc[];lifetimes:{name:string;tau_ns:number;intensity:number;distribution:string}[]; channels:{name?:string;pmt_id?:string;hv_V?:number;threshold_mV?:number;attenuation_dB?:number;cable_delay_ns?:number;tau_ns?:number;order?:number}[];digitizer:{name?:string;adc_bits?:number;samples?:number;rate_GSps?:number};acquisition:{trigger?:string;coincidence_ns?:number;trigger_delay_ns?:number};electronics?:{profile:import('./m2types').RuntimePulseProfile;device:import('./m2types').Component;responses:import('./m2types').AnalogResponse[]};inputs:TransportInput[]};
export type InputInspection={streams:(SourceStream|null)[];errors:{index:number;message:string}[];conflict:string};
