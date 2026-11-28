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
    double order=8;
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
public:
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

// Draw once per recorded event, detector and chronological PE rank. Both the
// trigger and every replay reuse this independent sequence, including equal times.
struct ChargeLaw {
    double cutoff=0., scale=0.;
    uint64_t seed=0;
    uint64_t forEvent(uint64_t event) const {return seed^((event+1)*0xd1b54a32d192ed03ULL);}
    void fill(double* out,size_t count,uint64_t key) const {
        Random rng(key);
        const double rate=(cutoff+std::hypot(cutoff,2.))/2;
        for(size_t i=0;i<count;++i){
            double y;
            if(cutoff<0){
                do {
                    const double radial=rng.uniform();
                    const double angle=rng.uniform();
                    y=std::sqrt(-2*std::log(radial))*std::cos(6.2831853071795864769*angle)-cutoff;
                } while(y<=0);
            }
            else {double error;
                do {y=-std::log(rng.uniform())/rate;error=y-1/rate;}
                while(rng.uniform()>std::exp(-.5*error*error));
            }
            out[i]=y*scale;
        }
    }
    std::vector<double> weights(size_t count,uint64_t event) const {
        if(!scale)return {};
        std::vector<double> result(count);fill(result.data(),count,forEvent(event));return result;
    }
};

inline std::vector<double> onsets(const std::vector<double>& arrivals,const Response& r,uint64_t seed) {
    Random rng(seed);std::vector<double> result;result.reserve(arrivals.size());
    for(double t:arrivals) result.push_back(t+r.delay+r.sigma*rng.normal());
    return result;
}

inline double logGamma(double n) {
    return n == std::floor(n) ? integerLogGamma(static_cast<int>(n)) : std::lgamma(n);
}
inline double density(double t,const Response& r) {
    if(t<=0)return 0;
    const double u=t/r.tau;
    return std::exp((r.order-1)*std::log(u)-u-logGamma(r.order))/r.tau;
}
inline double value(const std::vector<double>& onsets,const Response& r,double t,const double* weights=nullptr) {
    const double normalization=logGamma(r.order);
    double y=0;for(size_t i=0;i<onsets.size();++i)if(t>onsets[i]){const double u=(t-onsets[i])/r.tau;y+=(weights?weights[i]:1.)*std::exp((r.order-1)*std::log(u)-u-normalization)/r.tau;}
    return y;
}

// Convolve a real-order gamma pulse with a unit-area single-pole low pass.
inline double fractionalFiltered(double t, const Response& r) {
    if (t <= 0) return 0;
    const double n=r.order, u=t/r.tau, v=t/r.filterTau, x=u-v;
    const double prefactor=n*std::log(u)-std::lgamma(n+1)-std::log(r.filterTau);
    if (x >= 0 && x > n+40*std::sqrt(n)+60)
        return std::exp(-v-n*std::log1p(-r.tau/r.filterTau))/r.filterTau;
    if (x < -90) {
        // Endpoint expansion of the convolution. The discarded endpoint is O(exp(x)).
        double term=1, sum=1;
        for (int i=1;i<70;++i) {
            term *= (n-i)/x;
            sum += term;
            if (std::abs(term) < 1e-16*std::abs(sum)) break;
        }
        return density(t,r)*v/(-x)*sum;
    }
    double term=1, sum=1;
    for (int i=1;i<1000;++i) {
        term *= x>=0 ? x/(n+i) : (-x/i)*(n+i-1)/(n+i);
        sum += term;
        if (term < 1e-16*sum) break;
    }
    return std::exp(prefactor-(x>=0?u:v)+std::log(sum));
}

// Move the Erlang chain exactly between requested coordinates; new PE impulses
// are added analytically. This avoids evaluating every PE at every grid point.
class Chain {
    const double* times;const double* weights;const size_t length;const Response& response;
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
        const int n=static_cast<int>(response.order);const double a=delta/response.tau;
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
    Chain(const double* sorted,size_t count,const Response& r,bool reuse=false,const double* amplitudes=nullptr):
        times(sorted),weights(amplitudes),length(count),response(r),previous(sorted[0]),reuseGrid(reuse){}
    Chain(const std::vector<double>& sorted,const Response& r,bool reuse=false):
        Chain(sorted.data(),sorted.size(),r,reuse){}
    double at(double t) {
        if (response.order != std::floor(response.order)) {
            while(next<length && times[next]<=t) ++next;
            if (!response.filterTau) {
                const double norm=logGamma(response.order);
                double sum=0;
                for(size_t i=0;i<next;++i){
                    const double u=(t-times[i])/response.tau;
                    if(u>0) sum+=(weights?weights[i]:1.)*std::exp((response.order-1)*std::log(u)-u-norm);
                }
                return sum/response.tau;
            }
            double sum=0;
            for(size_t i=0;i<next;++i) sum+=(weights?weights[i]:1.)*fractionalFiltered(t-times[i],response);
            return sum;
        }
        return reuseGrid&&response.order==12?advance<12>(t):advance<0>(t);
    }
private:
    template<int fixedOrder> double advance(double t){
        const int n=fixedOrder?fixedOrder:static_cast<int>(response.order);
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
            const double weight=weights?weights[next]:1.;
            const double age=t-times[next++],u=age/response.tau;double term=weight*std::exp(-u);
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
                    const double upper=weight*2*fourth*fourth*fourth/(479001600.*response.filterTau);
                    negligible=upper<filtered*0x1.0p-54;
                }
                if(!negligible)
#endif
                filtered+=weight*filteredDensity(age,n,response.tau,response.filterTau);
            }
            for(int k=0;k<n;++k){state[k]+=term;term*=u/(k+1);}
        }
        previous=t;return response.filterTau>0?filtered:state[n-1]/response.tau;
    }
};

inline double peak(const std::vector<double>& times,const Response& r,const double* rankedWeights=nullptr) {
    if(times.empty())return 0;
    std::vector<double> sorted=times;std::sort(sorted.begin(),sorted.end());
    const double step=r.tau/8, end=sorted.back()+(r.order-1)*r.tau;
    Chain chain(sorted.data(),sorted.size(),r,false,rankedWeights);double best=0,bestT=sorted.front();
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
        if(value(sorted,r,a,rankedWeights)<value(sorted,r,b,rankedWeights))lo=a;else hi=b;
    }
    return std::max(best,value(sorted,r,(lo+hi)/2,rankedWeights))*r.voltageScale;
}
}
