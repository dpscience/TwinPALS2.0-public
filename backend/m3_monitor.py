# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Full-population plot accumulators; the compact channel journal supports exact rebinning."""
from collections import OrderedDict
from copy import copy
from typing import Literal
import numpy as np
from pydantic import Field, model_validator
from .m3_models import FitPercentiles,Model,ShapeFit,Window


class PlotSpec(Model):
    kind:Literal['phs','area','shape']
    channel:int=Field(ge=0,le=1)
    role:Literal['start','stop']='start'
    nx:int=Field(256,ge=8,le=2048)
    ny:int=Field(256,ge=8,le=512)
    axes:tuple[float,float,float,float]|None=None
    windows:tuple[Window,Window]|None=None

    @model_validator(mode='after')
    def valid(self):
        if self.kind=='phs' and 'nx' not in self.model_fields_set:self.nx=512
        if self.kind!='phs' and self.nx>512:raise ValueError('Use 8 to 512 density bins per axis.')
        if self.axes and (self.kind=='phs' or min(self.axes)<0 or self.axes[0]>=self.axes[1] or self.axes[2]>=self.axes[3]):
            raise ValueError('Fixed density limits must be increasing and nonnegative.')
        return self

    def key(self):
        windows=tuple((w.low,w.high) for w in self.windows) if self.kind=='phs' and self.windows else ()
        return self.kind,self.channel,self.nx,self.ny if self.kind!='phs' else 1,self.axes,windows


class Grid:
    def __init__(self,spec,headroom):
        self.spec=spec;self.ny=1 if spec.kind=='phs' else spec.ny
        self.cells=np.zeros((self.ny,spec.nx),dtype=np.uint64)
        # Recorded pulse heights are baseline relative. Even a rail-clipped
        # sample can be slightly above nominal ADC headroom after subtraction.
        xmax=headroom*1.02 if spec.kind=='area' else headroom
        self.axes=list(spec.axes or ((0.,4.,0.,8.) if spec.kind=='shape' else (0.,xmax,0.,max(1,headroom*4))))
        self.total=0;self.incomplete=0;self.above_adc=0;self.windows=[0,0]

    def grow(self,axis,maximum):
        high=1 if axis==1 else 3
        while maximum>=self.axes[high]:
            # Two old bins cover exactly one new bin when the extent doubles.
            merged=np.add.reduceat(self.cells,np.arange(0,self.cells.shape[axis],2),axis=axis)
            self.cells.fill(0)
            if axis==1:self.cells[:,:merged.shape[1]]=merged
            else:self.cells[:merged.shape[0],:]=merged
            self.axes[high]*=2

    def add(self,data):
        if not len(data):return
        spec=self.spec;self.total+=len(data)
        if spec.kind=='shape':
            complete=np.isfinite(data[:,2])&np.isfinite(data[:,3])
            self.incomplete+=len(data)-int(complete.sum());data=data[complete]
            if not len(data):return
        x=data[:,2] if spec.kind=='shape' else data[:,0]
        y=data[:,3] if spec.kind=='shape' else data[:,1]
        if spec.kind!='phs' and spec.axes is None:self.grow(1,float(x.max()))
        if spec.kind!='phs' and spec.axes is None:self.grow(0,float(y.max()))
        if spec.kind=='phs' and spec.windows:
            for i,w in enumerate(spec.windows):self.windows[i]+=int(np.count_nonzero((x>=w.low)&(x<w.high)))
        a,b,c,d=self.axes
        if spec.kind=='phs':
            self.above_adc+=int(np.count_nonzero(x>b))
            x=np.minimum(x,b)
        visible=(x>=a)&(x<=b)
        if spec.kind!='phs':visible&=(y>=c)&(y<=d)
        ix=np.minimum(spec.nx-1,((x[visible]-a)*(spec.nx/(b-a))).astype(np.int64))
        iy=np.zeros_like(ix) if spec.kind=='phs' else np.minimum(self.ny-1,((y[visible]-c)*(self.ny/(d-c))).astype(np.int64))
        np.add.at(self.cells.ravel(),iy*spec.nx+ix,1)

    def diagonal_axes(self):
        """Estimate the visible ridge using the 95th area percentile in populated height strips."""
        if self.total < 20 or self.spec.kind != 'area' or self.spec.axes:
            return None
        starts = np.arange(0, self.spec.nx, max(1, self.spec.nx // 24))
        strips = np.add.reduceat(self.cells, starts, axis=1)
        counts = strips.sum(axis=0)
        if not counts.any():
            return None
        populated = counts >= max(5, self.total * .0002)
        if not populated.any():
            populated = counts > 0
        levels = np.argmax(strips[:, populated].cumsum(axis=0) >= .95 * counts[populated], axis=0)
        top = min(self.axes[3], self.axes[3] * (int(levels.max()) + 1) / self.ny * 1.12)
        return [self.axes[0], self.axes[1], 0., top]

    def copy_for_read(self):
        result = copy(self)
        result.cells = self.cells.copy()
        result.axes = self.axes.copy()
        result.windows = self.windows.copy()
        return result

    def snapshot(self,role,first):
        flat=self.cells.ravel();ix=np.flatnonzero(flat)
        return dict(kind=self.spec.kind,channel=self.spec.channel,role=role,nx=self.spec.nx,ny=self.ny,
                    axes=self.axes.copy(),cells=np.column_stack((ix,flat[ix].astype(np.int64))).tolist(),
                    max_cell=int(flat.max()),fixed=self.spec.axes is not None,diagonal_axes=self.diagonal_axes(),
                    total=self.total,visible=int(flat.sum()),incomplete=self.incomplete,above_adc=self.above_adc,windows=self.windows.copy(),first=first)


class FeatureJournal:
    def __init__(self,root,lock,headrooms,channels):
        self.lock=lock;self.headrooms=headrooms
        self.files=[open(root/('features-'+ch+'.bin'),'w+b') for ch in 'AB']
        self.length=[0,0];self.first={(kind,ch):0 for kind in ('phs','area','shape') for ch in (0,1)}
        self.cache=OrderedDict()
        for ch in (0,1):
            for kind in ('phs','area','shape'):
                spec=PlotSpec(kind=kind,channel=ch,nx=512 if kind=='phs' else 256,
                              windows=[channels[ch][r]['phs'] for r in ('start','stop')] if kind=='phs' else None)
                self.cache[spec.key()]=Grid(spec,headrooms[ch])

    def append(self,rows):
        for ch in (0,1):
            data=np.ascontiguousarray(rows['values'][rows['reason'][:,ch]==0,ch,:4],dtype='<f8')
            if not len(data):continue
            self.files[ch].write(data.tobytes());self.length[ch]+=len(data)
            for grid in self.cache.values():
                if grid.spec.channel==ch:grid.add(data)

    def reset(self,kind,ch):
        self.first[kind,ch]=self.length[ch]
        for key,grid in list(self.cache.items()):
            if key[:2]==(kind,ch):self.cache[key]=Grid(grid.spec,self.headrooms[ch])

    def blocks(self,ch,first,last):
        with open(self.files[ch].name,'rb') as source:
            source.seek(first*32)
            while first<last:
                count=min(65536,last-first)
                block=np.fromfile(source,dtype='<f8',count=count*4).reshape(-1,4)
                if len(block)!=count:raise IOError('Incomplete Module 3 feature journal.')
                yield block;first+=count

    def prepare(self,spec):
        key=spec.key();ch=spec.channel
        while True:
            with self.lock:
                if key in self.cache:
                    self.cache.move_to_end(key);return self.cache[key]
                first=self.first[spec.kind,ch];last=self.length[ch];self.files[ch].flush()
            grid=Grid(spec,self.headrooms[ch]);at=first
            while True:
                for block in self.blocks(ch,at,last):grid.add(block)
                at=last
                with self.lock:
                    if self.first[spec.kind,ch]!=first:break
                    if key in self.cache:return self.cache[key]
                    last=self.length[ch];self.files[ch].flush()
                    if last-at>4096:continue
                    if last>at:
                        for block in self.blocks(ch,at,last):grid.add(block)
                    self.cache[key]=grid
                    while len(self.cache)>20:self.cache.popitem(last=False)
                    return grid

    def prepare_many(self,raw,area_views=False):
        if not isinstance(raw,list) or len(raw)>10:raise ValueError('Select up to ten monitoring plots.')
        specs=[PlotSpec.model_validate(s) for s in raw]
        prepared=[(spec,self.prepare(spec)) for spec in specs]
        if area_views:
            for spec,grid in tuple(prepared):
                if spec.kind!='area':continue
                with self.lock:
                    axes=None if spec.axes else grid.diagonal_axes()
                if axes is None and spec.axes is None:continue
                other=spec.model_copy(update={'axes':tuple(axes) if axes else None})
                prepared.append((other,self.prepare(other)))
        return prepared

    def capture(self,prepared):
        if any(self.cache.get(s.key()) is not g for s,g in prepared):return None
        copies={}
        result=[]
        for s,g in prepared:
            if g not in copies:copies[g]=g.copy_for_read()
            result.append((s.role,copies[g],self.first[s.kind,s.channel]+1))
        return result

    @staticmethod
    def render(captured,share_cells=False):
        seen={};result=[]
        for role,grid,first in captured:
            if grid not in seen:
                seen[grid]=len(result)
                result.append(grid.snapshot(role,first))
            else:
                index=seen[grid]
                item={**result[index],'role':role}
                if share_cells:item.update(cells=[],cells_from=index)
                result.append(item)
        return result

    def snapshot(self,prepared):
        captured=self.capture(prepared)
        return self.render(captured) if captured is not None else None

    def fit(self,ch,kind,window,options=None,include_counts=False):
        params=(FitPercentiles if kind=='area' else ShapeFit).model_validate({} if options is None else options)
        with self.lock:
            first=self.first[kind,ch];last=self.length[ch];self.files[ch].flush()
        def values():
            for part in self.blocks(ch,first,last):
                sel=part[(part[:,0]>=window['low'])&(part[:,0]<window['high'])]
                if kind=='shape':sel=sel[np.isfinite(sel[:,2])&np.isfinite(sel[:,3])]
                if len(sel):yield sel[:,:2] if kind=='area' else sel[:,2:4]
        def moments(bounds=None):
            n=0;s=np.zeros(2);ss=np.zeros((2,2));lo=np.full(2,np.inf);hi=-lo
            for v in values():
                if bounds is not None:v=v[np.all((v>=bounds[0])&(v<=bounds[1]),axis=1)]
                if not len(v):continue
                n+=len(v);s+=v.sum(axis=0);ss+=v.T@v;lo=np.minimum(lo,v.min(axis=0));hi=np.maximum(hi,v.max(axis=0))
            if n<20:raise ValueError('At least 20 valid pulses in this PHS window are needed for a fit.')
            return n,s/n,(ss-np.outer(s,s)/n)/(n-1),lo,hi
        n,mean,cov,lo,hi=moments()
        if kind=='area':
            if cov[0,0]<1e-12:raise ValueError('The selected pulse heights do not span a line fit.')
            slope=cov[0,1]/cov[0,0];intercept=mean[1]-slope*mean[0]
            # Quantile widths are found from every residual with a bounded histogram.
            floor=np.inf;ceil=-np.inf
            for v in values():
                res=v[:,1]-slope*v[:,0]-intercept;floor=min(floor,res.min());ceil=max(ceil,res.max())
            edges=np.linspace(floor,ceil if ceil>floor else floor+1e-9,4097);bins=np.zeros(4096,dtype=np.int64)
            for v in values():bins+=np.histogram(v[:,1]-slope*v[:,0]-intercept,bins=edges)[0]
            low,high=np.searchsorted(bins.cumsum(),np.clip(np.array([params.low,params.high])*n/100,1,n))
            return dict(enabled=True,slope=float(slope),intercept=float(intercept),below=float(max(0,-edges[low])),above=float(max(0,edges[high+1])))
        # Restrict the covariance to the central population using full-population quantiles.
        bounds=np.array([lo,hi]);bins=np.zeros((2,4096),dtype=np.int64)
        edges=[np.linspace(lo[i],max(hi[i],lo[i]+1e-9),4097) for i in (0,1)]
        for v in values():
            for i in (0,1):bins[i]+=np.histogram(v[:,i],bins=edges[i])[0]
        for i in (0,1):
            q=np.searchsorted(bins[i].cumsum(),np.clip(np.array([params.low,params.high])*n/100,1,n));a,b=edges[i][q[0]],edges[i][q[1]+1]
            bounds[:,i]=[a-params.fence*(b-a),b+params.fence*(b-a)]
        _,mean,cov,_,_=moments(bounds)
        eigenvalues,axes=np.linalg.eigh(cov)
        axis=axes[:,-1]
        angle=float(np.degrees(np.arctan2(axis[1],axis[0])))
        theta=np.radians(angle)
        cosine,sine=np.cos(theta),np.sin(theta)
        scales=np.sqrt(np.maximum(eigenvalues[::-1],1e-12))

        def squared_distances():
            for points in values():
                x,y=(points-mean).T
                yield ((x*cosine+y*sine)/scales[0])**2+((y*cosine-x*sine)/scales[1])**2

        rank=min(n-1,int(np.ceil(n*params.coverage/100))-1)
        if rank==n-1:
            edge=max(float(block.max()) for block in squared_distances())
        elif n<=65536:
            distances=np.concatenate(list(squared_distances()))
            distances.partition(rank)
            edge=float(distances[rank])
        else:
            # Positive IEEE doubles have the same order as their unsigned bit patterns.
            # Select the rank in four bounded passes without sorting the acquisition.
            prefix=0
            for shift in (48,32,16,0):
                counts=np.zeros(65536,dtype=np.int64)
                for block in squared_distances():
                    bits=block.view(np.uint64)
                    if shift<48:bits=bits[(bits>>(shift+16))==prefix]
                    digits=((bits>>shift)&65535).astype(np.intp)
                    counts+=np.bincount(digits,minlength=len(counts))
                cumulative=counts.cumsum()
                digit=int(cumulative.searchsorted(rank+1))
                if digit:rank-=int(cumulative[digit-1])
                prefix=(prefix<<16)|digit
            edge=float(np.uint64(prefix).view(np.float64))
        # Keep the boundary sample inside when the acquisition evaluates the rotated gate.
        radii=np.maximum(1e-5,scales*np.sqrt(edge)*(1+8*np.finfo(float).eps))
        gate=dict(enabled=True,rise=float(mean[0]),fall=float(mean[1]),radius_rise=float(radii[0]),
                  radius_fall=float(radii[1]),angle_deg=angle)
        if not include_counts:return gate
        inside=0
        for points in values():
            x,y=(points-mean).T
            d=((x*cosine+y*sine)/radii[0])**2+((y*cosine-x*sine)/radii[1])**2
            inside+=int(np.count_nonzero(d<=1))
        return dict(gate=gate,inside=inside,total=n,first=first+1)

    def close(self):
        for file in self.files:file.close()
