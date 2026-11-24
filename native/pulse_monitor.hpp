// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

#pragma once
#include <algorithm>
#include <cmath>

namespace pulse_monitor {
// NumPy's contiguous float64 sum uses eight accumulators and recursively
// divides blocks above 128 elements. Preserve that order for saved pulse area.
inline double pairwise(const double* v,int n){
    if(n<8){double sum=-0.;for(int i=0;i<n;++i)sum+=v[i];return sum;}
    if(n>128){int middle=(n/2)/8*8;return pairwise(v,middle)+pairwise(v+middle,n-middle);}
    double a[8];std::copy_n(v,8,a);int i=8;
    for(;i+7<n;i+=8)for(int k=0;k<8;++k)a[k]+=v[i+k];
    double sum=((a[0]+a[1])+(a[2]+a[3]))+((a[4]+a[5])+(a[6]+a[7]));
    for(;i<n;++i)sum+=v[i];return sum;
}
inline void monitor(const float* axis,const float* signal,int n,double base,double offset,
             const double* coordinates,int bins,double* norm,double* work,double* out,
             double& peak,double& area,float& peakTime){
    peak=-1.;
    for(int i=0;i<n;++i){
        norm[i]=std::abs(static_cast<double>(signal[i])-base);
        if(norm[i]>peak){peak=norm[i];peakTime=axis[i];}
        if(i)work[i-1]=static_cast<double>(axis[i]-axis[i-1])*(norm[i]+norm[i-1])/2.;
    }
    area=pairwise(work,n-1);if(!coordinates||!out||!(area>0.))return;
    int j=0;
    for(int b=0;b<bins;++b){
        const double x=coordinates[b];
        while(j+1<n&&static_cast<double>(axis[j+1])-offset<=x)++j;
        const double x0=static_cast<double>(axis[j])-offset;
        if(x<x0||x>static_cast<double>(axis[n-1])-offset){out[b]=NAN;continue;}
        const double y=norm[j]/area;
        if(x==x0||j+1==n){out[b]=y;continue;}
        const double slope=(norm[j+1]/area-y)/((static_cast<double>(axis[j+1])-offset)-x0);
        out[b]=slope*(x-x0)+y;
    }
}
}
