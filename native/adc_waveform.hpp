// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Evaluate the stored ADC codes. The discriminator always uses its original
// double-precision grid. Here a fast convolution is used only when its entire
// error interval lies in one ADC code and on the same side of both clip rails.
#pragma once
#include "analog_pmt.hpp"
#include <limits>

namespace adc_waveform {
struct SampledResponse {
    double first=0.,inverseStep=0.,last=0.,unitError=0.;
    std::vector<double> knots;
    double at(double t)const{
        if(t<=first||t>=last)return 0.;
        const double u=(t-first)*inverseStep;
        const int i=static_cast<int>(u);
        const double x=u-i+3.;
        // Eight consecutive nodes with the sample in their central interval.
        constexpr double inv[8]={-1./5040,1./720,-1./240,1./144,-1./144,1./240,-1./720,1./5040};
        double prefix[8],suffix=1.,value=0.;prefix[0]=1.;
        for(int k=1;k<8;++k)prefix[k]=prefix[k-1]*(x-(k-1));
        for(int k=7;k>=0;--k){value+=knots[i+k]*(inv[k]*prefix[k]*suffix);suffix*=x-k;}
        return value;
    }
};
struct Pulse {
    const double* onsets;
    int32_t count,order;
    double origin,tau,scale,polarity,factor;
    const SampledResponse* table=nullptr;
};
struct Kernel {
    int order;
    double tau,filter,step,inverseStep,cutoff;
    std::vector<std::array<double,4>> polynomial;
    Kernel(int n,double t,double f):order(n),tau(t),filter(f),step(t/256),inverseStep(1./step){
        // Exponential tilting at half the slowest rate bounds the remaining
        // unit-area cascade density by 2^(n+1) exp(-s age) / tau.
        cutoff=2*std::max(t,f)*((n+1)*std::log(2.)-std::log(1e-14));
        const int cells=static_cast<int>(std::ceil(cutoff/step));
        std::vector<double> knots(cells+3);
        analog_pmt::Response shape;shape.order=n;shape.tau=t;
        for(int i=0;i<cells+3;++i){
            const double age=(i-1)*step;
            knots[i]=f>0?analog_pmt::filteredDensity(age,n,t,f):analog_pmt::density(age,shape);
        }
        polynomial.reserve(cells);
        for(int i=0;i<cells;++i){
            const double a=knots[i],b=knots[i+1],c=knots[i+2],d=knots[i+3];
            polynomial.push_back({b,(-2*a-3*b+6*c-d)/6,(a-2*b+c)/2,(-a+3*b-3*c+d)/6});
        }
    }
    double at(double age)const{
        const double position=age*inverseStep;
        const auto i=std::min(static_cast<size_t>(position),polynomial.size()-1);
        const auto& p=polynomial[i];const double x=position-i;
        return ((p[3]*x+p[2])*x+p[1])*x+p[0];
    }
};

inline const Kernel& kernel(int order,double tau,double filter){
    thread_local std::vector<Kernel> cache;
    for(const auto& k:cache)if(k.order==order&&k.tau==tau&&k.filter==filter)return k;
    if(cache.size()>=4)cache.clear();
    return cache.emplace_back(order,tau,filter);
}

// Project a dense cluster of PE onsets onto a regular grid. The ten Lagrange
// weights preserve polynomials up to degree nine in onset time. Adjacent nodes
// are exactly 32 fine kernel cells apart, so each sample has one fractional
// coordinate irrespective of how many photoelectrons contributed.
inline bool clustered(const Pulse& p,const Kernel& k,const std::vector<double>& relative,
                      double scale,std::vector<double>& voltage,double& weightNorm){
    if(p.order<11||p.count<48)return false;
    const auto range=std::minmax_element(p.onsets,p.onsets+p.count);
    const double first=*range.first,spacing=p.tau/8;
    const double width=(*range.second-first)/spacing;
    if(!(width>=0&&width<1024&&width+10<.75*p.count))return false;
    const int bins=static_cast<int>(width)+10;
    std::vector<double> weights(bins,0.);
    // 1 / product_{j != i} (i-j) for ten consecutive integer nodes.
    constexpr double inverse[10]={-1./362880,1./40320,-1./10080,1./4320,-1./2880,
                                   1./2880,-1./4320,1./10080,-1./40320,1./362880};
    for(int i=0;i<p.count;++i){
        const double u=(p.onsets[i]-first)/spacing;const int j=static_cast<int>(u);
        const double x=(u-j)+4;double prefix[10];prefix[0]=1.;
        for(int l=1;l<10;++l)prefix[l]=prefix[l-1]*(x-(l-1));
        double suffix=1.;
        for(int l=9;l>=0;--l){
            weights[j+l]+=prefix[l]*suffix*inverse[l];suffix*=x-l;
        }
    }
    weightNorm=0.;for(double w:weights)weightNorm+=std::abs(w);
    const int lastCell=static_cast<int>(k.polynomial.size())-1;
    for(size_t i=0;i<relative.size();++i){
        const double position=(relative[i]-first)*k.inverseStep+128.;
        if(!(position>=0&&position<(bins-1)*32+lastCell+1))continue;
        const int cell=static_cast<int>(position);
        const double x=position-cell;
        const int lo=std::max(0,(cell-lastCell+31)/32),hi=std::min(bins-1,cell/32);
        double sum=0.;
        for(int j=lo;j<=hi;++j){
            const auto& c=k.polynomial[cell-32*j];
            sum+=weights[j]*(((c[3]*x+c[2])*x+c[1])*x+c[0]);
        }
        voltage[i]+=sum*scale;
    }
    return true;
}

#if defined(TP_M2_AVX_GRID) && defined(_MSC_VER) && defined(_M_X64)
// Resolve four independent samples only if their full error intervals stay
// inside both rails and a single digitizer bin. Every other lane goes through
// the scalar rail, clipping and exact-replay checks below.
template<class Scalar>
__declspec(noinline) int quantizeFour(const double* voltage,const double* background,const double* errors,
        int length,double uncertainty,double low,double high,double lsb,unsigned levels,float* out,Scalar& scalar){
    const double eps=std::numeric_limits<double>::epsilon();
    const auto lo=_mm256_set1_pd(low),hi=_mm256_set1_pd(high),one=_mm256_set1_pd(1.);
    const auto reciprocal=_mm256_set1_pd(1./lsb),step=_mm256_set1_pd(lsb);
    const auto top=_mm256_set1_pd(double(levels)),roundoff=_mm256_set1_pd(12*eps*(levels+1.));
    const auto largest=_mm256_set1_pd(std::max(std::abs(low),std::abs(high)));
    int i=0;
    for(;i+4<=length;i+=4){
        auto e=_mm256_set1_pd(uncertainty);
        if(errors)e=_mm256_add_pd(e,_mm256_loadu_pd(errors+i));
        const auto guard=_mm256_add_pd(e,_mm256_mul_pd(_mm256_set1_pd(8*eps),
                _mm256_add_pd(_mm256_add_pd(largest,e),one)));
        const auto v=_mm256_add_pd(_mm256_loadu_pd(voltage+i),_mm256_loadu_pd(background+i));
        const auto position=_mm256_add_pd(_mm256_mul_pd(_mm256_sub_pd(v,lo),reciprocal),_mm256_set1_pd(.5));
        const auto bin=_mm256_floor_pd(position),fraction=_mm256_sub_pd(position,bin);
        const auto codeGuard=_mm256_add_pd(_mm256_mul_pd(guard,reciprocal),roundoff);
        auto valid=_mm256_and_pd(_mm256_cmp_pd(v,_mm256_add_pd(lo,guard),_CMP_GT_OQ),
                                 _mm256_cmp_pd(v,_mm256_sub_pd(hi,guard),_CMP_LT_OQ));
        valid=_mm256_and_pd(valid,_mm256_cmp_pd(position,_mm256_setzero_pd(),_CMP_GE_OQ));
        valid=_mm256_and_pd(valid,_mm256_cmp_pd(position,top,_CMP_LT_OQ));
        valid=_mm256_and_pd(valid,_mm256_cmp_pd(fraction,codeGuard,_CMP_GT_OQ));
        valid=_mm256_and_pd(valid,_mm256_cmp_pd(_mm256_sub_pd(one,fraction),codeGuard,_CMP_GT_OQ));
        const auto mask=_mm256_movemask_pd(valid);
        _mm_storeu_ps(out+i,_mm256_cvtpd_ps(_mm256_add_pd(lo,_mm256_mul_pd(bin,step))));
        if(mask!=15)for(int k=0;k<4;++k)if(!(mask&(1<<k)))scalar(i+k);
    }
    _mm256_zeroupper();
    return i;
}
#endif
inline int sample(const double* times,const double* background,int length,
                  const Pulse* pulses,int count,double filter,double low,double high,
                  double lsb,unsigned levels,float* output,int* clipped){
    thread_local std::vector<double> voltage,relative,tableError;
    voltage.assign(length,0.);relative.resize(length);tableError.clear();
    double uncertainty=0;bool exact=false;
    for(int k=0;k<count;++k){
        const auto& p=pulses[k];
        if(p.count==0)continue;
        // Keep the certified path in the well-conditioned range of the
        // archived Erlang implementation. Other poles and orders use it directly.
        if(p.order<5||p.order>24||!(p.tau>0)||p.count>65536||length>8192||
                (filter>0&&(filter/p.tau<.25||filter/p.tau>4.||std::abs(filter/p.tau-1)<1e-5))){exact=true;break;}
        for(int i=0;i<length;++i)relative[i]=times[i]-p.origin;
        const double scale=p.scale*p.polarity*p.factor;
        if(p.table){
            const auto& tab=*p.table;
            if(tableError.empty())tableError.resize(length);
            const double bound=std::abs(scale)*tab.unitError;
            const double tail=std::abs(scale)*p.count/p.tau*1e-12;
            for(int i=0;i<length;++i){
                if(relative[i]<=tab.first)continue;
                if(relative[i]>=tab.last){tableError[i]+=tail;continue;}
                voltage[i]+=scale*tab.at(relative[i]);tableError[i]+=bound;
            }
            continue;
        }
        const auto& shape=kernel(p.order,p.tau,filter);
        double weightNorm=p.count;
        const bool grouped=clustered(p,shape,relative,scale,voltage,weightNorm);
        if(!grouped)for(int j=0;j<p.count;++j){
            const double onset=p.onsets[j];
            auto i=std::upper_bound(relative.begin(),relative.end(),onset)-relative.begin();
            for(;i<length;++i){
                const double age=relative[i]-onset;
                if(age>=shape.cutoff)break;
                voltage[i]+=shape.at(age)*scale;
            }
        }
        // For n >= 5 the fourth derivative is a fourth difference of five
        // Erlang densities, hence <= 16/tau^5, also after a unit-area filter.
        // Four-node Lagrange on [-1,0,1,2] has |product| <= 1 on [0,1].
        // The remaining allowance covers the tail, kernel evaluation and
        // positive chain/PE summation at binary64 precision.
        const double propagation=128.*std::numeric_limits<double>::epsilon()*
                                 (p.order*static_cast<double>(length)+p.count+count+64);
        // The tenth derivative is bounded by 2^10/tau^11. On the central
        // interval the product of the ten distances is at most
        // (0.5*1.5*2.5*3.5*4.5)^2; spacing tau/8 gives < 2.30e-10/tau.
        const double grouping=grouped?p.count*2.30e-10:0.;
        uncertainty+=std::abs(scale)/p.tau*(weightNorm*(16./(24.*4294967296.)+1e-12+propagation)+grouping);
    }
    auto code=[&](double v){return std::clamp(std::floor((v-low)/lsb+.5),0.,static_cast<double>(levels-1));};
    auto outside=[&](double v){return v<low||v>=high;};
    *clipped=0;
    // Most samples are well inside one code. Include the rounding of the
    // subtraction, division and half-code offset in this inexpensive test.
    // Near a rail or bin edge retain the original outward-rounded check.
    const double eps=std::numeric_limits<double>::epsilon();
    const double largest=std::max(std::abs(low),std::abs(high));
    const double reciprocal=1./lsb;
    int lastUncertain=-1;thread_local std::vector<unsigned char> uncertain;
    uncertain.clear();
    auto scalar=[&](int i){
        const double v=voltage[i]+background[i];
        const double error=uncertainty+(tableError.empty()?0.:tableError[i]);
        const double railGuard=error+8*eps*(largest+error+1.);
        const double codeGuard=railGuard*reciprocal+12*eps*(levels+1.);
        const double position=(v-low)*reciprocal+.5;
        if(v>low+railGuard&&v<high-railGuard&&position>=0.&&position<levels){
            const auto bin=static_cast<unsigned>(position);
            const double fraction=position-bin;
            if(fraction>codeGuard&&1.-fraction>codeGuard){
                output[i]=static_cast<float>(low+bin*lsb);return;
            }
        }
        const double lower=std::nextafter(v-error,-INFINITY),upper=std::nextafter(v+error,INFINITY);
        if(code(lower)!=code(upper)||outside(lower)!=outside(upper)||(lower<low&&upper>=high)){
            if(uncertain.empty())uncertain.resize(length);
            uncertain[i]=1;lastUncertain=i;return;
        }
        output[i]=static_cast<float>(low+code(v)*lsb);
        if(outside(v))*clipped=1;
    };
    if(!exact){
        int i=0;
#if defined(TP_M2_AVX_GRID) && defined(_MSC_VER) && defined(_M_X64)
        if(analog_pmt::avxGrid())
            i=quantizeFour(voltage.data(),background,tableError.empty()?nullptr:tableError.data(),
                           length,uncertainty,low,high,lsb,levels,output,scalar);
#endif
        for(;i<length;++i)scalar(i);
    }
    if(exact||lastUncertain>=0){
        const int end=exact?length:lastUncertain+1;
        std::fill(voltage.begin(),voltage.begin()+end,0.);
        for(int k=0;k<count;++k){
            const auto& p=pulses[k];if(!p.count)continue;
            std::vector<double> sorted(p.onsets,p.onsets+p.count);std::sort(sorted.begin(),sorted.end());
            analog_pmt::Response r;r.order=p.order;r.tau=p.tau;r.filterTau=filter;
            analog_pmt::Chain chain(sorted,r);
            for(int i=0;i<end;++i){
                const double t=times[i]-p.origin;
                if(t>=sorted.front())voltage[i]+=((chain.at(t)*p.scale)*p.polarity)*p.factor;
            }
        }
        for(int i=0;i<end;++i){
            if(!exact&&!uncertain[i])continue;
            const double v=voltage[i]+background[i];
            output[i]=static_cast<float>(low+code(v)*lsb);
            if(outside(v))*clipped=1;
        }
    }
    return 0;
}
}
