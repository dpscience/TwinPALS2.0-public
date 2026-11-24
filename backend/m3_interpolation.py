# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Interpolants on the digitizer's individual, calibrated sample coordinates."""
import numpy as np


def slopes(t, y, method):
    h=np.diff(t.astype(float));delta=np.diff(y)/h;n=len(y)
    if method=='akima':
        d=np.pad(delta,(2,2))
        d[1]=2*d[2]-d[3];d[0]=2*d[1]-d[2]
        d[-2]=2*d[-3]-d[-4];d[-1]=2*d[-2]-d[-3]
        left=np.abs(d[3:]-d[2:-1]);right=np.abs(d[1:-2]-d[:-3])
        weight=left+right
        return np.divide(left*d[1:-2]+right*d[2:-1],weight,
                         out=(d[1:-2]+d[2:-1])*.5,where=weight>0)
    # Natural cubic spline. Solve the tridiagonal system for second derivatives.
    diagonal=2*(h[:-1]+h[1:]);rhs=6*np.diff(delta)
    for i in range(1,n-2):
        ratio=h[i]/diagonal[i-1]
        diagonal[i]-=ratio*h[i];rhs[i]-=ratio*rhs[i-1]
    m=np.zeros(n)
    for i in range(n-3,-1,-1):m[i+1]=(rhs[i]-h[i+1]*m[i+2])/diagonal[i]
    return np.r_[delta-h*(2*m[:-1]+m[1:])/6, delta[-1]+h[-1]*(m[-2]+2*m[-1])/6]


def evaluate(t,y,d,i,u):
    return y[i]+u*((3-2*u)*u*(y[i+1]-y[i])+
                   (t[i+1].astype(float)-t[i])*(1-u)*((1-u)*d[i]-u*d[i+1]))


def refined_crossing(t,y,d,level,i,steps,rising,last=False):
    u=np.arange(steps+1,dtype=float)/steps
    v=evaluate(t,y,d,i,u);v[0],v[-1]=y[i],y[i+1]
    ix=np.flatnonzero((v[:-1]<=level)&(v[1:]>level) if rising else (v[:-1]>=level)&(v[1:]<level))
    j=int(ix[-1] if last else ix[0]);fraction=(j+(level-v[j])/(v[j+1]-v[j]))/steps
    return float(t[i]+fraction*(float(t[i+1])-t[i]))


def trace(t,y,method,steps):
    t=np.asarray(t,dtype=float);y=np.asarray(y,dtype=float)
    if method=='linear':return np.column_stack((t,y)).tolist()
    d=slopes(t,y,method)
    # All timing decisions use the requested subdivisions. Cap only display vertices.
    total=(len(t)-1)*steps
    at=np.linspace(0,total,min(total+1,32768)).round().astype(int)
    i=np.minimum(len(t)-2,at//steps);u=at/steps-i
    return np.column_stack((t[i]+u*(t[i+1]-t[i]),evaluate(t,y,d,i,u))).tolist()
