// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Effective, charge-normalized Erlang response. No Geant4 RNG or digitizer grid.
#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <vector>
#include <stdexcept>
#if defined(_M_X64) || defined(__SSE2__)
#include <emmintrin.h>
#endif
#if defined(TP_M2_AVX_GRID) && defined(_MSC_VER) && defined(_M_X64)
#include <immintrin.h>
#include <intrin.h>
#endif

namespace analog_pmt {
#if defined(TP_M2_AVX_GRID) && defined(_MSC_VER) && defined(_M_X64)
inline bool avxGrid(){
    static const bool supported=[](){
        int cpu[4];__cpuid(cpu,1);
        return (cpu[2]&(1<<27))&&(cpu[2]&(1<<28))&&(_xgetbv(0)&6)==6;
    }();
    return supported;
}
// Each lane accumulates precisely the original j=0..k terms. Keep the three
// four-stage sums in registers and avoid touching the unused 20 chain stages.
__declspec(noinline) inline void move12(double* state,const double* coefficients){
    alignas(32) double padded[16]={};std::copy_n(state,12,padded+4);
    auto a=_mm256_setzero_pd(),b=a,c=a;
    for(int j=0;j<12;++j){
        const auto w=_mm256_set1_pd(coefficients[j]);
        if(j<4)a=_mm256_add_pd(a,_mm256_mul_pd(_mm256_loadu_pd(padded+4-j),w));
        if(j<8)b=_mm256_add_pd(b,_mm256_mul_pd(_mm256_loadu_pd(padded+8-j),w));
        c=_mm256_add_pd(c,_mm256_mul_pd(_mm256_loadu_pd(padded+12-j),w));
    }
    _mm256_storeu_pd(state,a);_mm256_storeu_pd(state+4,b);_mm256_storeu_pd(state+8,c);
    _mm256_zeroupper();
}
#endif
inline double integerLogGamma(int n) {
    static const auto values=[] {std::array<double,34> v{};for(int i=1;i<34;++i)v[i]=std::lgamma(i);return v;}();
    return values[n];
}
struct Response {
    int order=8;
    double tau=1, delay=0, sigma=0, voltageScale=1;
    int polarity=-1;
    double filterTau=0;
};

// Exact convolution Gamma(n,tau) * Exp(filterTau). Stable series for nearby
// poles and short times; finite incomplete-gamma formula away from cancellation.
inline double filteredDensity(double t,int n,double tau,double filterTau) {
    if(t<=0)return 0;
    const double u=t/tau,x=t*(1/tau-1/filterTau);
    if(std::abs(x)<1e-8)return std::exp(-u+n*std::log(u)-integerLogGamma(n+1))/filterTau;
    if(x>0){
        double probability;
        if(x<n+1){
            double term=1,sum=1;
            for(int k=1;k<1000;++k){term*=x/(n+k);sum+=term;if(term<sum*1e-15)break;}
            // Combining exponentials here avoids underflow in probability.
            return std::exp(-u+n*std::log(u)-integerLogGamma(n+1))*sum/filterTau;
        }
        double term=1,sum=1;for(int k=1;k<n;++k){term*=x/k;sum+=term;}
        probability=1-std::exp(-x)*sum;
        return std::exp(-t/filterTau-n*std::log1p(-tau/filterTau))*probability/filterTau;
    }
    const double b=-x;
    if(b<2*n+20){
        // exp(-t/filterTau) * M(n;n+1;b), all-positive series.
        double term=1,sum=1;
        for(int k=1;k<1000;++k){term*=b/k*(n+k-1.)/(n+k);sum+=term;if(term<sum*1e-15)break;}
        return std::exp(-t/filterTau+n*std::log(u)-integerLogGamma(n+1))*sum/filterTau;
    }
    double term=1,sum=1;for(int k=1;k<n;++k){term*=-(n-k)/b;sum+=term;}
    // The lower integration endpoint is negligible here (b > 2n+20).
    const double endpoint=(n%2?1.:-1.)*std::exp(-b+integerLogGamma(n)-(n-1)*std::log(b));
    return std::exp(-u+(n-1)*std::log(u)-integerLogGamma(n))*u/b*(sum-endpoint)/filterTau;
}

// Defined integer generator + Box-Muller; reproducible across thread schedules.
// Separate stream from transport: HV/TTS cannot affect optical histories.
class Random {
    uint64_t state;
    double uniform() {
        uint64_t z=(state+=0x9e3779b97f4a7c15ULL);
        z=(z^(z>>30))*0xbf58476d1ce4e5b9ULL;
        z=(z^(z>>27))*0x94d049bb133111ebULL;
        z^=z>>31;
        return (static_cast<double>(z>>11)+.5)*0x1.0p-53;
    }
public:
    explicit Random(uint64_t seed):state(seed){}
    double normal(){ return std::sqrt(-2*std::log(uniform()))*std::cos(6.2831853071795864769*uniform()); }
};

inline std::vector<double> onsets(const std::vector<double>& arrivals,const Response& r,uint64_t seed) {
    Random rng(seed);std::vector<double> result;result.reserve(arrivals.size());
    for(double t:arrivals) result.push_back(t+r.delay+r.sigma*rng.normal());
    return result;
}

inline double density(double t,const Response& r) {
    if(t<=0)return 0;
    const double u=t/r.tau;
    return std::exp((r.order-1)*std::log(u)-u-integerLogGamma(r.order))/r.tau;
}
inline double value(const std::vector<double>& onsets,const Response& r,double t) {
    const double normalization=integerLogGamma(r.order);
    double y=0;for(double onset:onsets)if(t>onset){const double u=(t-onset)/r.tau;y+=std::exp((r.order-1)*std::log(u)-u-normalization)/r.tau;}
    return y;
}

// Move the Erlang chain exactly between requested coordinates; new PE impulses
// are added analytically. This avoids evaluating every PE at every grid point.
class Chain {
    const double* times;const size_t length;const Response& response;
    std::array<double,32> state{};std::size_t next=0;double previous,filtered=0;
    struct Transition {
        double delta=-1, filterDecay=0;
        std::array<double,32> p{}, filter{};
    };
    // Trigger searches repeatedly use exactly the same coordinate differences.
    // Cache the exact transition, never round coordinates or change the kernel.
    std::array<Transition,8> transitions{};unsigned replacement=0;bool reuseGrid;
    const Transition& transition(double delta) {
        for(const auto& q:transitions)if(q.delta==delta)return q;
        auto& q=transitions[replacement++%transitions.size()];
        struct Shared {int order=0;double tau=0,pole=0;Transition q;};
        thread_local std::array<Shared,8> grid{};
        thread_local unsigned nextGrid=0;
        if(reuseGrid)for(const auto& entry:grid){
            if(entry.q.delta==delta&&entry.order==response.order&&entry.tau==response.tau&&entry.pole==response.filterTau){
                q=entry.q;return q;
            }
        }
        q.delta=delta;
        const int n=response.order;const double a=delta/response.tau;
        q.p[0]=std::exp(-a);
        for(int k=1;k<n;++k)q.p[k]=q.p[k-1]*a/k;
        if(response.filterTau>0){
            q.filterDecay=std::exp(-delta/response.filterTau);
            for(int k=0;k<n;++k)q.filter[k]=filteredDensity(delta,n-k,response.tau,response.filterTau);
        }
        if(reuseGrid)grid[nextGrid++%grid.size()]={n,response.tau,response.filterTau,q};
        return q;
    }
public:
    Chain(const double* sorted,size_t count,const Response& r,bool reuse=false):
        times(sorted),length(count),response(r),previous(sorted[0]),reuseGrid(reuse){}
    Chain(const std::vector<double>& sorted,const Response& r,bool reuse=false):
        Chain(sorted.data(),sorted.size(),r,reuse){}
    double at(double t) {
        return reuseGrid&&response.order==12?advance<12>(t):advance<0>(t);
    }
private:
    template<int fixedOrder> double advance(double t){
        const int n=fixedOrder?fixedOrder:response.order;
        if(next!=0||!reuseGrid){
            const auto& q=transition(t-previous);
            if(response.filterTau>0){
                filtered*=q.filterDecay;
                for(int k=0;k<n;++k)filtered+=state[k]*q.filter[k];
            }
            // Each stage retains its j=0..k summation order. SSE2 advances
            // two independent doubles without reassociation or FMA.
#if defined(TP_M2_AVX_GRID) && defined(_MSC_VER) && defined(_M_X64)
            if(fixedOrder==12&&avxGrid())move12(state.data(),q.p.data());
            else
#endif
            {
            std::array<double,32> moved{};
            for(int j=0;j<n;++j){
                int k=j;
#if defined(_M_X64) || defined(__SSE2__)
                const auto coefficient=_mm_set1_pd(q.p[j]);
                for(;k+1<n;k+=2)_mm_storeu_pd(moved.data()+k,_mm_add_pd(_mm_loadu_pd(moved.data()+k),_mm_mul_pd(_mm_loadu_pd(state.data()+k-j),coefficient)));
#endif
                for(;k<n;++k)moved[k]+=state[k-j]*q.p[j];
            }
            state=moved;
            }
        }
        while(next<length && times[next]<=t){
            const double age=t-times[next++],u=age/response.tau;double term=std::exp(-u);
            if(response.filterTau>0){
#ifdef TP_M2_AVX_GRID
                // Convolution with the unit-area low-pass has density no larger
                // than u^12 / (12! * pole). Both exponential factors are <= 1.
                // On this short, well-conditioned interval a factor of two also
                // covers arithmetic rounding. Below 2^-54 of the accumulator
                // adding that positive term cannot change the stored double.
                bool negligible=false;
                if(fixedOrder==12&&u<=.5&&filtered>0&&response.filterTau>=.25*response.tau&&
                   response.filterTau<=4*response.tau){
                    const double sq=u*u,fourth=sq*sq;
                    const double upper=2*fourth*fourth*fourth/(479001600.*response.filterTau);
                    negligible=upper<filtered*0x1.0p-54;
                }
                if(!negligible)
#endif
                filtered+=filteredDensity(age,n,response.tau,response.filterTau);
            }
            for(int k=0;k<n;++k){state[k]+=term;term*=u/(k+1);}
        }
        previous=t;return response.filterTau>0?filtered:state[n-1]/response.tau;
    }
};

inline double peak(const std::vector<double>& times,const Response& r) {
    if(times.empty())return 0;
    std::vector<double> sorted=times;std::sort(sorted.begin(),sorted.end());
    const double step=r.tau/8, end=sorted.back()+(r.order-1)*r.tau;
    Chain chain(sorted,r);double best=0,bestT=sorted.front();
    // A long optical delay must not allocate a dense waveform. Between isolated
    // arrivals skip only intervals where all kernels are past their own maxima.
    std::size_t cluster=0;
    for(double t=sorted.front();t<=end+step;t+=step){
        const double y=chain.at(t);if(y>best){best=y;bestT=t;}
        while(cluster+1<sorted.size() && sorted[cluster+1]<=t)++cluster;
        if(cluster+1<sorted.size() && t>sorted[cluster]+(r.order-1)*r.tau && sorted[cluster+1]>t+step)
            t=sorted[cluster+1]-step;
    }
    // Refine the largest coarse local maximum using exact continuous values.
    // The scan is tau/8 (at least 8 samples per intrinsic scale); regression tests
    // compare multi-modal/clustered pulses against a much finer independent grid.
    double lo=bestT-step,hi=bestT+step;
    for(int i=0;i<36;++i){
        const double a=lo+(hi-lo)/3,b=hi-(hi-lo)/3;
        if(value(sorted,r,a)<value(sorted,r,b))lo=a;else hi=b;
    }
    return std::max(best,value(sorted,r,(lo+hi)/2))*r.voltageScale;
}
}
