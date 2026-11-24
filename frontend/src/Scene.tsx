// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import { useEffect, useMemo, useRef, useState } from 'react';
import type {ReactNode} from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { Scan } from 'lucide-react';
import {usePreference,usePreferences} from './Preferences';
import type { Detector, M1Run, Profile } from './m1types';
import type { Entry } from './types';

const rad=(degrees:number)=>degrees*Math.PI/180;
export function frameQuaternion(axis:THREE.Vector3,up=new THREE.Vector3(0,1,0)){const z=axis.clone().normalize();if(Math.abs(up.clone().normalize().dot(z))>.9999)up=new THREE.Vector3(1,0,0);const x=up.clone().cross(z).normalize(),y=z.clone().cross(x).normalize();return new THREE.Quaternion().setFromRotationMatrix(new THREE.Matrix4().makeBasis(x,y,z));}
export function detectorPose(d:Detector){const front:[number,number,number]=[d.distance_mm*Math.cos(rad(d.azimuth_deg)),d.distance_mm*Math.sin(rad(d.azimuth_deg)),d.vertical_offset_mm];const v=new THREE.Vector3(Math.cos(rad(d.tilt_deg))*Math.cos(rad(d.azimuth_deg)),Math.cos(rad(d.tilt_deg))*Math.sin(rad(d.azimuth_deg)),Math.sin(rad(d.tilt_deg)));return {front,axis:[v.x,v.y,v.z] as [number,number,number]};}
function dispose(object:THREE.Object3D){object.traverse(o=>{const mesh=o as THREE.Mesh;mesh.geometry?.dispose();if(mesh.material)(Array.isArray(mesh.material)?mesh.material:[mesh.material]).forEach(m=>{(m as THREE.MeshBasicMaterial).map?.dispose();m.dispose();});});}
function crystalGeometry(d:Detector){const p=d.dimensions;if(d.shape==='box')return new THREE.BoxGeometry(p.width_mm,p.height_mm,p.length_mm);if(d.shape==='pyramid'){const v=[-p.front_width_mm/2,-p.front_height_mm/2,0,p.front_width_mm/2,-p.front_height_mm/2,0,p.front_width_mm/2,p.front_height_mm/2,0,-p.front_width_mm/2,p.front_height_mm/2,0,-p.rear_width_mm/2,-p.rear_height_mm/2,p.length_mm,p.rear_width_mm/2,-p.rear_height_mm/2,p.length_mm,p.rear_width_mm/2,p.rear_height_mm/2,p.length_mm,-p.rear_width_mm/2,p.rear_height_mm/2,p.length_mm];const geo=new THREE.BufferGeometry();geo.setAttribute('position',new THREE.Float32BufferAttribute(v,3));geo.setIndex([0,2,1,0,3,2,4,5,6,4,6,7,0,1,5,0,5,4,1,2,6,1,6,5,2,3,7,2,7,6,3,0,4,3,4,7]);geo.computeVertexNormals();geo.translate(0,0,-p.length_mm/2);return geo;}
 const g=new THREE.CylinderGeometry(d.shape==='cone'?p.rear_diameter_mm/2:p.diameter_mm/2,d.shape==='cone'?p.front_diameter_mm/2:p.diameter_mm/2,p.length_mm,64);g.rotateX(Math.PI/2);return g;}
type SceneEntry = Pick<Entry,'id'|'name'> & Partial<Pick<Entry,'properties'>>;

function assemblyScene(profile:Profile,entries:SceneEntry[],transparent:boolean){
 const scene=new THREE.Scene();
 scene.background=new THREE.Color('#edf1f5');
 const pm=(d:Detector)=>entries.find(e=>e.id===d.pmt_id)?.properties;
 const extent=Math.max(65,...profile.detectors.map(d=>Math.hypot(d.distance_mm,d.vertical_offset_mm)+d.dimensions.length_mm+Number(pm(d)?.tube_length_mm??15)),...profile.shields.filter(s=>s.enabled).map(s=>Math.hypot(...s.position_mm)+Math.max(s.width_mm,s.height_mm,s.diameter_mm)));
 scene.add(new THREE.HemisphereLight('#ffffff','#8f9ba8',2.5));const sun=new THREE.DirectionalLight('#ffffff',3);sun.position.set(70,-100,150);scene.add(sun);const grid=new THREE.GridHelper(500,50,'#bdc8d3','#d9e1e8');grid.rotateX(Math.PI/2);grid.position.z=-28;scene.add(grid);scene.add(new THREE.AxesHelper(15));
 const mat=(color:string,opacity=1)=>new THREE.MeshPhysicalMaterial({color,transparent:opacity<1,opacity,roughness:.28,metalness:.12,side:THREE.DoubleSide,depthWrite:opacity>.8});
 const add=(parent:THREE.Object3D,geo:THREE.BufferGeometry,color:string,position:[number,number,number],opacity=1)=>{const mesh=new THREE.Mesh(geo,mat(color,opacity));mesh.position.set(...position);parent.add(mesh);return mesh;};
 const disk=(diameter:number,length:number)=>{const g=new THREE.CylinderGeometry(diameter/2,diameter/2,Math.max(.001,length),48);g.rotateX(Math.PI/2);return g;};
 profile.detectors.forEach(d=>{const transform=detectorPose(d),group=new THREE.Group();group.position.set(...transform.front);group.quaternion.copy(frameQuaternion(new THREE.Vector3(...transform.axis)));scene.add(group);const length=d.dimensions.length_mm,color=d.id==='A'?'#34a8a3':'#7494d7';const crystal=add(group,crystalGeometry(d),color,[0,0,length/2],transparent?.53:1);const edges=new THREE.LineSegments(new THREE.EdgesGeometry(crystal.geometry,24),new THREE.LineBasicMaterial({color:d.id==='A'?'#268a86':'#536fb1',transparent:true,opacity:.7}));edges.position.z=length/2;group.add(edges);const rear=d.shape==='cone'?d.dimensions.rear_diameter_mm:d.shape==='cylinder'?d.dimensions.diameter_mm:Math.max(d.dimensions.width_mm,d.dimensions.rear_width_mm),face=(thickness:number,front=false)=>d.shape==='box'||d.shape==='pyramid'?new THREE.BoxGeometry(d.shape==='box'?d.dimensions.width_mm:front?d.dimensions.front_width_mm:d.dimensions.rear_width_mm,d.shape==='box'?d.dimensions.height_mm:front?d.dimensions.front_height_mm:d.dimensions.rear_height_mm,Math.max(.001,thickness)):disk(front&&d.shape==='cone'?d.dimensions.front_diameter_mm:rear,thickness);if(d.wrapping.enabled){const outer={...d,dimensions:{...d.dimensions}};Object.keys(outer.dimensions).filter(key=>key!=='length_mm').forEach(key=>{outer.dimensions[key as keyof Detector['dimensions']]+=2*d.wrapping.side_mm;});const wrap=new THREE.LineSegments(new THREE.EdgesGeometry(crystalGeometry(outer),24),new THREE.LineBasicMaterial({color:'#adb8c4',transparent:true,opacity:.65}));wrap.position.z=length/2;group.add(wrap);if(d.wrapping.front_mm>0)add(group,face(d.wrapping.front_mm,true),'#d5d9dc',[0,0,-d.wrapping.front_mm/2],transparent?.15:.85);}if(d.coupling_mm>0)add(group,face(d.coupling_mm),'#d5dce6',[0,0,length+d.coupling_mm/2],.65);const pmt=pm(d);if(pmt){const g=(key:string)=>Number(pmt[key]),start=length+d.coupling_mm,wall=1,tubeLength=g('tube_length_mm'),square=pmt.tube_shape==='square',outer=g(square?'tube_width_mm':'tube_diameter_mm')/2,wt=g('window_thickness_mm'),gap=g('cathode_gap_mm');
 const aperture=(prefix:string,thickness:number)=>pmt[prefix+'_shape']==='rect'?new THREE.BoxGeometry(g(prefix+'_width_mm'),g(prefix+'_height_mm'),thickness):disk(g(prefix+'_diameter_mm'),thickness);
 // Open-ended outer shell shows the separately sized vacuum bore.
 if(square){
  const side=2*outer;
  for(const sign of [-1,1]){
   add(group,new THREE.BoxGeometry(wall,side,tubeLength),'#8395aa',[sign*(outer-wall/2),0,start+tubeLength/2],transparent?.16:.9);
   add(group,new THREE.BoxGeometry(side-2*wall,wall,tubeLength),'#8395aa',[0,sign*(outer-wall/2),start+tubeLength/2],transparent?.16:.9);
  }
 }else{
  const shell=new THREE.CylinderGeometry(outer,outer,tubeLength,64,1,true);shell.rotateX(Math.PI/2);
  add(group,shell,'#8395aa',[0,0,start+tubeLength/2],transparent?.16:.9);
  const rim=new THREE.RingGeometry(outer-wall,outer,64);add(group,rim,'#8395aa',[0,0,start],.7);
 }
 const envelope=(depth:number)=>square?new THREE.BoxGeometry(2*outer,2*outer,depth):disk(2*outer,depth);
 add(group,envelope(wall),'#8395aa',[0,0,start+tubeLength-wall/2],transparent?.18:.9);
 add(group,aperture('window',wt),'#7fbed3',[0,0,start+wt/2],transparent?.42:.7);
 add(group,aperture('photocathode',.05),'#53517f',[0,0,start+wt+gap+.025],.8);
 const bounds=new THREE.LineSegments(new THREE.EdgesGeometry(envelope(tubeLength),25),new THREE.LineBasicMaterial({color:'#8b9caf',transparent:true,opacity:.5}));bounds.position.z=start+tubeLength/2;group.add(bounds);
 }

 const canvas=document.createElement('canvas');canvas.width=128;canvas.height=64;const context=canvas.getContext('2d')!;context.font='600 32px system-ui';context.fillStyle=d.id==='A'?'#217b78':'#4566a2';context.textAlign='center';context.fillText(d.id,64,42);const sprite=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(canvas),depthTest:false}));sprite.position.copy(new THREE.Vector3(0,0,length/2).applyQuaternion(group.quaternion).add(group.position));sprite.position.z+=26;sprite.scale.set(14,7,1);scene.add(sprite);
 });
 const sg=profile.source_geometry,source=add(scene,sg.radius_mm>0||sg.thickness_mm>0?disk(Math.max(.03,sg.radius_mm*2),Math.max(.03,sg.thickness_mm)):new THREE.SphereGeometry(.7,24,16),'#db9d42',[0,0,0]);source.quaternion.copy(frameQuaternion(new THREE.Vector3(Math.cos(rad(profile.assembly.tilt_deg))*Math.cos(rad(profile.assembly.azimuth_deg)),Math.cos(rad(profile.assembly.tilt_deg))*Math.sin(rad(profile.assembly.azimuth_deg)),Math.sin(rad(profile.assembly.tilt_deg)))));source.userData.source=true;
 const addBlock=(shape:string,width:number,height:number,diameter:number,thickness:number,position:[number,number,number],axis:THREE.Vector3,color:string,up=new THREE.Vector3(0,1,0))=>{if(thickness<=0)return;const mesh=add(scene,shape==='cylinder'?disk(diameter,thickness):new THREE.BoxGeometry(width,height,thickness),color,position,transparent?.45:.9);mesh.quaternion.copy(frameQuaternion(axis,up));};
 const s=profile.sample,axis=(az:number,tilt:number)=>new THREE.Vector3(Math.cos(rad(tilt))*Math.cos(rad(az)),Math.cos(rad(tilt))*Math.sin(rad(az)),Math.sin(rad(tilt)));{const normal=axis(profile.assembly.azimuth_deg,profile.assembly.tilt_deg),gap=profile.source_geometry.thickness_mm/2,foil=s.foil_enabled?s.foil_thickness_mm:0;[-1,1].forEach(sign=>{const length=sign<0?s.left.thickness_mm:s.right.thickness_mm,offset=sign*(gap+foil+length/2);const side=sign<0?s.left:s.right;if(s.enabled)addBlock(side.shape,side.width_mm,side.height_mm,side.diameter_mm,length,normal.clone().multiplyScalar(offset).toArray() as [number,number,number],normal,sign<0?'#9daebb':'#bdc7cd');if(foil>0)addBlock('cylinder',0,0,s.foil_diameter_mm,foil,normal.clone().multiplyScalar(sign*(gap+foil/2)).toArray() as [number,number,number],normal,'#c7a97c');});}

 profile.shields.filter(s=>s.enabled).forEach(s=>{let position=new THREE.Vector3(...s.position_mm),normal=axis(s.azimuth_deg,s.tilt_deg),up=new THREE.Vector3(0,1,0).applyQuaternion(frameQuaternion(axis(s.azimuth_deg,s.tilt_deg)));if(s.reference==='A'||s.reference==='B'){const d=profile.detectors.find(d=>d.id===s.reference);if(d){const p=detectorPose(d),q=frameQuaternion(new THREE.Vector3(...p.axis));position.applyQuaternion(q).add(new THREE.Vector3(...p.front));normal.applyQuaternion(q);up.applyQuaternion(q);}}addBlock(s.shape,s.width_mm,s.height_mm,s.diameter_mm,s.thickness_mm,position.toArray() as [number,number,number],normal,'#6d7684',up);});
 return {scene,extent};
}

export function assemblySnapshot(profile:Profile,entries:SceneEntry[]):string|null {
 if(!profile?.detectors?.length || !profile.assembly || !profile.sample || !profile.shields || !profile.source_geometry)return null;
 let renderer:THREE.WebGLRenderer;
 try { renderer=new THREE.WebGLRenderer({antialias:true}); } catch { return null; }
 let assembly:THREE.Scene|undefined;
 try {
  const {scene,extent}=assemblyScene(profile,entries,true);
  assembly=scene;
  const width=1200,height=460;
  const camera=new THREE.PerspectiveCamera(34,width/height,.1,Math.max(3000,extent*30));
  camera.up.set(0,0,1);
  camera.position.set(.7,-2.0,.83).multiplyScalar(extent);
  camera.lookAt(0,0,0);
  renderer.setSize(width,height,false);
  renderer.render(scene,camera);
  return renderer.domElement.toDataURL('image/png');
 } finally {
  if(assembly)dispose(assembly);
  renderer.dispose();
  renderer.forceContextLoss();
 }
}

export default function Scene({overlay,profile,trajectories=[],entries=[],live=false,archived=false}:{overlay?:ReactNode;profile:Profile;trajectories?:M1Run['trajectories'];entries?:SceneEntry[];live?:boolean;archived?:boolean}){
 const [preference,setPreference]=usePreference(live?'scene_simulation':'scene_setup'),{generation}=usePreferences();
 const [archiveView,setArchiveView]=useState<typeof preference>({transparent:true,camera:null,tree:{assembly:false}});
 const sceneView=archived?archiveView:preference,setSceneView=archived?setArchiveView:setPreference;
 const saved=useRef(sceneView);saved.current=sceneView;
 const transparent=sceneView.transparent;
 const setTransparent=(value:boolean)=>setSceneView(v=>({...v,transparent:value}));
 const tree=(id:string)=>({open:sceneView.tree[id]??true,onToggle:(event:React.SyntheticEvent<HTMLDetailsElement>)=>{const open=event.currentTarget.open;setSceneView(v=>(v.tree[id]??true)===open?v:{...v,tree:{...v.tree,[id]:open}});}});
 const geometryKey=useMemo(()=>JSON.stringify([profile.detectors,profile.assembly,profile.source_geometry,profile.sample,profile.shields,entries.map(e=>[e.id,e.properties])]),[profile,entries]);
 const trajectoryKey=trajectories.at(-1);
 const compass=useRef<SVGSVGElement>(null),host=useRef<HTMLDivElement>(null),reset=useRef<()=>void>(()=>{}),view=useRef<(name:string)=>void>(()=>{}),tracks=useRef<THREE.Group|null>(null),[error,setError]=useState('');
 const name=(id:string)=>entries.find(e=>e.id===id)?.name??id;
 useEffect(()=>{const container=host.current;if(!container)return;let renderer:THREE.WebGLRenderer;try{renderer=new THREE.WebGLRenderer({antialias:true,alpha:false});}catch{setError('3D rendering unavailable. Enable WebGL in this browser.');return;}setError('');container.append(renderer.domElement);renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.setClearColor('#edf1f5');renderer.outputColorSpace=THREE.SRGBColorSpace;const {scene,extent}=assemblyScene(profile,entries,transparent);const camera=new THREE.PerspectiveCamera(36,1,.1,3000);camera.up.set(0,0,1);camera.far=Math.max(3000,extent*30);camera.updateProjectionMatrix();camera.position.set(extent*1.8,-extent*2,extent*1.4);const controls=new OrbitControls(camera,renderer.domElement);controls.enableDamping=!archived;controls.minDistance=5;controls.maxDistance=Math.max(1500,extent*10);if(saved.current.camera){camera.position.fromArray(saved.current.camera.position);camera.up.fromArray(saved.current.camera.up);controls.target.fromArray(saved.current.camera.target);}const remember=()=>setSceneView(v=>({...v,camera:{position:camera.position.toArray() as [number,number,number],target:controls.target.toArray() as [number,number,number],up:camera.up.toArray() as [number,number,number]}}));controls.addEventListener('end',remember);view.current=(name)=>{controls.target.set(0,0,0);camera.up.set(0,0,1);if(name==='Top'){camera.up.set(0,1,0);camera.position.set(0,0,extent*3);}else if(name==='Front')camera.position.set(0,-extent*3,0);else if(name==='Side')camera.position.set(extent*3,0,0);else camera.position.set(extent*1.8,-extent*2,extent*1.4);camera.lookAt(controls.target);controls.update();remember();};reset.current=()=>view.current('ISO');
 const liveTracks=new THREE.Group();scene.add(liveTracks);tracks.current=liveTracks;
 const resize=new ResizeObserver(()=>{const w=container.clientWidth,h=container.clientHeight;if(w&&h){renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();if(archived)draw();}});resize.observe(container);let frame=0;const draw=()=>{if(!archived)controls.update();renderer.render(scene,camera);const inverse=camera.quaternion.clone().invert();if(compass.current){const groups:Array<{element:SVGGElement;z:number}>=[];['X','Y','Z'].forEach((axis,index)=>{[-1,1].forEach(sign=>{const direction=new THREE.Vector3(index===0?sign:0,index===1?sign:0,index===2?sign:0).applyQuaternion(inverse),x=50+direction.x*31,y=50-direction.y*31,g=compass.current!.querySelector<SVGGElement>(`[data-axis="${axis}"][data-sign="${sign}"]`)!,line=g.querySelector('line')!,dot=g.querySelector('circle')!,label=g.querySelector('text');line.setAttribute('x2',String(x));line.setAttribute('y2',String(y));dot.setAttribute('cx',String(x));dot.setAttribute('cy',String(y));if(label){label.setAttribute('x',String(x));label.setAttribute('y',String(y+3.5));}g.setAttribute('opacity',direction.z<-.15?'.45':'1');groups.push({element:g,z:direction.z});});});groups.sort((a,b)=>a.z-b.z).forEach(g=>compass.current!.append(g.element));}if(!archived)frame=requestAnimationFrame(draw);};if(archived)controls.addEventListener('change',draw);draw();return()=>{controls.removeEventListener('change',draw);cancelAnimationFrame(frame);resize.disconnect();controls.dispose();tracks.current=null;dispose(scene);renderer.dispose();renderer.domElement.remove();};
 },[geometryKey,transparent,generation,archived]);
 useEffect(()=>{const group=tracks.current;if(!group)return;for(const child of [...group.children]){group.remove(child);dispose(child);}for(const event of trajectories.slice(-1))for(const track of event.tracks){if(track.points_mm.length<2)continue;const geo=new THREE.BufferGeometry().setFromPoints(track.points_mm.map(p=>new THREE.Vector3(...p)));const color=track.particle==='gamma'?'#ca7012':track.particle==='opticalphoton'?'#dfb31d':'#87df78';group.add(new THREE.Line(geo,new THREE.LineBasicMaterial({color,transparent:true,opacity:.95,depthTest:false})));if(track.particle!=='opticalphoton')group.add(new THREE.Points(geo.clone(),new THREE.PointsMaterial({color,size:3,sizeAttenuation:false,depthTest:false})));}
 for(const event of trajectories.slice(-1)){const births=(event.cherenkov_births??[]).flat();if(births.length){const geo=new THREE.BufferGeometry().setFromPoints(births.map((b:any)=>new THREE.Vector3(...b.position_mm as [number,number,number])));group.add(new THREE.Points(geo,new THREE.PointsMaterial({color:'#dc8b26',size:6,sizeAttenuation:false,depthTest:false})));}}
 },[geometryKey,trajectoryKey,transparent]);
 return <div className="scene-panel">{overlay}<div className="scene-host" ref={host}/><div className="scene-label"><strong>Geometry</strong><span>mm · Z vertical</span></div><div className="scene-controls"><button onClick={()=>reset.current()} title="Fit complete geometry" aria-label="Fit complete geometry"><Scan size={16}/></button>{['ISO','Top','Front','Side'].map(v=><button key={v} onClick={()=>view.current(v)} title={`${v} view`}>{v}</button>)}<button className={transparent?'selected':''} title="Show internal layers through transparent surfaces" onClick={()=>setTransparent(!transparent)}>Transparent</button></div><div className="component-tree"><details {...tree("assembly")}><summary>Assembly</summary><ul><li><details {...tree("source")}><summary>{profile.source==='na22'?'²²Na':'⁶⁰Co'} · source</summary><ul>{profile.sample.enabled&&<><li>Left · {name(profile.sample.left.material_id)}</li><li>Right · {name(profile.sample.right.material_id)}</li></>}{profile.sample.foil_enabled&&<li>Foils · {name(profile.sample.foil_material_id)}</li>}</ul></details></li>{profile.detectors.map(d=><li key={d.id}><details {...tree(d.id)}><summary><span className="tree-detector-label"><i className={`detector-dot ${d.id}`}/>Detector {d.id} · {name(d.scintillator_id)}</span></summary><ul><li>{d.shape}</li>{d.wrapping.enabled&&<li>Wrap · {name(d.surface_id)}</li>}<li>Coupling · {name(d.coupling_id)}</li><li>PMT · {name(d.pmt_id)}</li><li className="tree-vacuum">Interior · vacuum behind window</li></ul></details></li>)}{profile.shields.filter(s=>s.enabled).map((s,i)=><li key={s.id}>Shield {i+1} · {name(s.material_id)}</li>)}</ul></details></div><svg ref={compass} className="orientation-compass" viewBox="0 0 100 100" aria-label="Camera orientation axes"><circle cx="50" cy="50" r="4" fill="#8294a4"/>{[['X','#d96568'],['Y','#41a987'],['Z','#628ed8']].flatMap(([axis,color])=>[-1,1].map(sign=><g key={`${axis}${sign}`} data-axis={axis} data-sign={sign}><line x1="50" y1="50" x2="50" y2="50" stroke={color} strokeWidth={sign===1?3:1.4} strokeLinecap="round"/><circle cx="50" cy="50" r={sign===1?8.5:4} fill={sign===1?color:'#f8fafc'} stroke={color} strokeWidth="1.5"/>{sign===1&&<text x="50" y="53.5" textAnchor="middle" fill="white" fontSize="10" fontWeight="700">{axis}</text>}</g>))}</svg>{error&&<div className="scene-error">{error}</div>}</div>;
}
