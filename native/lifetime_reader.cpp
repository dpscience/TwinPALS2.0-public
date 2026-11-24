// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

#include "vendor/json.hpp"
#include "stream_crc.hpp"
#include "pulse_monitor.hpp"
#include <algorithm>
#include <charconv>
#include <string_view>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <limits>
#include <mutex>
#include <shared_mutex>
#include <stdexcept>
#include <string>
#include <unordered_map>
#include <vector>
#ifdef _WIN32
#define TP_API extern "C" __declspec(dllexport)
#else
#define TP_API extern "C"
#endif

namespace {
using Json=nlohmann::json;
using Index=std::uint64_t;
struct Channel {int positive,baseline,median; double cfd,minimum; int interpolation,steps,first,pre_pulse,gap;};
struct Support {
    Index role,record,offset;
    double span[2];
    std::uint8_t primary_mask[2],local[2],direct[2],backward[2],scatter[2],external[2];
    std::uint32_t length,crc;
};
struct Truth {
    std::array<std::unordered_map<Index,Support>,2> roles;
    mutable std::shared_mutex mutex;
};
struct Result {
    Index id; double start;
    double features[2][5]; // height, area, rise, fall, CFD
    std::uint8_t reason[2],clipped[2],category,origin,scatter,reserved;
    std::uint32_t contributions[2][2]; // channel, then source role
};
static_assert(sizeof(Result)==120);
struct Interval {double from=0,to=0;};
void need(bool ok,const char* msg){if(!ok)throw std::runtime_error(msg);}
template<class T>T read(const unsigned char* at){T x;std::memcpy(&x,at,sizeof(x));return x;}
#include "lifetime_truth.hpp"
Index integer(const Json& j){need(j.is_number_unsigned(),"Invalid nonnegative waveform identifier");return j.get<Index>();}
double number(const Json& j){need(j.is_number(),"Invalid waveform number");const double x=j.get<double>();need(std::isfinite(x),"Nonfinite waveform number");return x;}
// The two inner values of four samples are max(lower pair) and min(upper pair).
// The median of these two and the fifth sample gives the rolling median of five.
double median3(double a,double b,double c){
    return std::max(std::min(a,b),std::min(std::max(a,b),c));
}
void short_median(const std::vector<double>& in,std::vector<double>& out,int width){
    const int radius=width/2,n=static_cast<int>(in.size());
    const auto sample=[&](int i){return in[std::clamp(i,0,n-1)];};
    const auto one=[&](int i){
        const double a=sample(i-1),b=sample(i),c=sample(i+1);
        if(width==3)return median3(a,b,c);
        const double d=sample(i-2),e=sample(i+2);
        return median3(std::max(std::min(d,a),std::min(b,c)),std::min(std::max(d,a),std::max(b,c)),e);
    };
    int i=0;
    for(;i<radius;++i)out[i]=one(i);
#if defined(_M_X64)
    const auto mid=[](__m128d a,__m128d b,__m128d c){return _mm_max_pd(_mm_min_pd(a,b),_mm_min_pd(_mm_max_pd(a,b),c));};
    for(;i+1<n-radius;i+=2){
        const double* p=&in[i];
        auto a=_mm_loadu_pd(p-1),b=_mm_loadu_pd(p),c=_mm_loadu_pd(p+1);
        if(width==3)_mm_storeu_pd(&out[i],mid(a,b,c));
        else{
            auto d=_mm_loadu_pd(p-2),e=_mm_loadu_pd(p+2);
            auto low=_mm_max_pd(_mm_min_pd(d,a),_mm_min_pd(b,c));
            auto high=_mm_min_pd(_mm_max_pd(d,a),_mm_max_pd(b,c));
            _mm_storeu_pd(&out[i],mid(low,high,e));
        }
    }
#endif
    for(;i<n;++i)out[i]=one(i);
}
template<class T> T median(std::vector<T>& a) {
    auto middle=a.begin()+a.size()/2;
    std::nth_element(a.begin(),middle,a.end());
    if(a.size()%2)return *middle;
    return (*std::max_element(a.begin(),middle)+*middle)/T(2);
}
void cubic_derivatives(const std::vector<float>& t,const std::vector<double>& y,std::vector<double>& d){
    const int n=static_cast<int>(t.size());
    thread_local std::vector<double> h,delta,diag,rhs,m;
    h.resize(n-1);delta.resize(n-1);d.resize(n);
    for(int i=0;i<n-1;++i){h[i]=double(t[i+1])-t[i];delta[i]=(y[i+1]-y[i])/h[i];}
    diag.resize(n-2);rhs.resize(n-2);m.resize(n);m.front()=m.back()=0;
    for(int i=0;i<n-2;++i){
        diag[i]=2*(h[i]+h[i+1]);rhs[i]=6*(delta[i+1]-delta[i]);
        if(i){const double r=h[i]/diag[i-1];diag[i]-=r*h[i];rhs[i]-=r*rhs[i-1];}
    }
    for(int i=n-3;i>=0;--i)m[i+1]=(rhs[i]-h[i+1]*m[i+2])/diag[i];
    for(int i=0;i<n-1;++i)d[i]=delta[i]-h[i]*(2*m[i]+m[i+1])/6;
    d.back()=delta.back()+h.back()*(m[n-2]+2*m[n-1])/6;
}
double akima_at(const std::vector<float>& t,const std::vector<double>& y,int i){
    const int last=static_cast<int>(t.size())-2;
    const auto secant=[&](int j){return (y[j+1]-y[j])/(double(t[j+1])-t[j]);};
    const auto delta=[&](int j){
        if(j>=0 && j<=last)return secant(j);
        if(j<0){const double a=secant(0),b=2*a-secant(1);return j==-1?b:2*b-a;}
        const double a=secant(last),b=2*a-secant(last-1);return j==last+1?b:2*b-a;
    };
    const double m0=delta(i-2),m1=delta(i-1),m2=delta(i),m3=delta(i+1);
    const double a=std::abs(m3-m2),b=std::abs(m1-m0);
    return a+b>0?(a*m1+b*m2)/(a+b):.5*(m1+m2);
}
double cross(const std::vector<float>& t,const std::vector<double>& y,double level,int a,int b,bool rising,
             const std::vector<double>* d,int steps,bool last_cross=false){
    for(int k=0;k<b-a;++k){
        const int i=last_cross?b-1-k:a+k;
        const auto crosses=[&](double lo,double hi){return rising?(lo<=level&&level<hi):(lo>=level&&level>hi);};
        if(!crosses(y[i],y[i+1]))continue;
        if(!d)return t[i]+(level-y[i])*(t[i+1]-t[i])/(y[i+1]-y[i]);
        const double d0=d->empty()?akima_at(t,y,i):(*d)[i],d1=d->empty()?akima_at(t,y,i+1):(*d)[i+1];
        const double h=double(t[i+1])-t[i];double last=y[i],found=std::numeric_limits<double>::quiet_NaN();
        for(int j=1;j<=steps;++j){
            const double u=double(j)/steps;
            const double v=j==steps?y[i+1]:y[i]+u*((3-2*u)*u*(y[i+1]-y[i])+h*(1-u)*((1-u)*d0-u*d1));
            if(crosses(last,v)){found=t[i]+h*((j-1)+(level-last)/(v-last))/steps;if(!last_cross)return found;}
            last=v;
        }
        if(std::isfinite(found))return found;
    }
    return std::numeric_limits<double>::quiet_NaN();
}
// Validate four ADC samples at a time. Ordered comparisons reject NaN as well as infinity.
bool valid_samples(const float* t,const float* v,int n){
    if(!std::isfinite(t[0])||!std::isfinite(v[0]))return false;
    int i=1;
#if defined(_M_X64)
    const auto magnitude=_mm_castsi128_ps(_mm_set1_epi32(0x7fffffff));
    const auto max_value=_mm_set1_ps(std::numeric_limits<float>::max());
    auto valid=_mm_castsi128_ps(_mm_set1_epi32(-1));
    for(;i+3<n;i+=4){
        const auto ts=_mm_loadu_ps(t+i),volts=_mm_loadu_ps(v+i);
        valid=_mm_and_ps(valid,_mm_cmpgt_ps(ts,_mm_loadu_ps(t+i-1)));
        valid=_mm_and_ps(valid,_mm_cmple_ps(_mm_and_ps(ts,magnitude),max_value));
        valid=_mm_and_ps(valid,_mm_cmple_ps(_mm_and_ps(volts,magnitude),max_value));
    }
    if(_mm_movemask_ps(valid)!=15)return false;
#endif
    for(;i<n;++i)if(!std::isfinite(t[i])||!std::isfinite(v[i])||t[i]<=t[i-1])return false;
    return true;
}
// Calculate adjacent trapezoids in parallel, then add them in their original order.
double pulse_area(const std::vector<float>& t,const std::vector<double>& y){
    const int last=static_cast<int>(y.size())-1;
    double area=0;
    int i=0;
#if defined(_M_X64)
    const auto half=_mm_set1_pd(.5),sign=_mm_set1_pd(-0.0);
    for(;i+3<last;i+=4){
        const auto dt=_mm_sub_ps(_mm_loadu_ps(&t[i+1]),_mm_loadu_ps(&t[i]));
        const auto pair=[&](int at,__m128d times){
            const auto sum=_mm_add_pd(_mm_loadu_pd(&y[at]),_mm_loadu_pd(&y[at+1]));
            return _mm_andnot_pd(sign,_mm_mul_pd(_mm_mul_pd(sum,half),times));
        };
        const auto a=pair(i,_mm_cvtps_pd(dt)),b=pair(i+2,_mm_cvtps_pd(_mm_movehl_ps(dt,dt)));
        area+=_mm_cvtsd_f64(a);area+=_mm_cvtsd_f64(_mm_unpackhi_pd(a,a));
        area+=_mm_cvtsd_f64(b);area+=_mm_cvtsd_f64(_mm_unpackhi_pd(b,b));
    }
#endif
    for(;i<last;++i)area+=std::abs((y[i]+y[i+1])*.5*(t[i+1]-t[i]));
    return area;
}
// Timestamps in each channel retain the calibrated, non-equidistant sample grid.
int extract(const unsigned char* raw,int n,const Channel& c,double* out,Interval& interval){
    thread_local std::vector<float> t,v,base;
    thread_local std::vector<double> y,filtered,window;
    t.resize(n);v.resize(n);y.resize(n);
    std::memcpy(t.data(),raw,n*4);std::memcpy(v.data(),raw+n*4,n*4);
    need(valid_samples(t.data(),v.data(),n),"Invalid waveform samples or channel time axis");
    if(n<=c.baseline+4)return 1;
    const int seed=c.pre_pulse?std::min(8,c.baseline):c.baseline;
    const auto reference=[&](int start,int count,double& noise){
        base.assign(v.begin()+start,v.begin()+start+count);
        const float level=median(base);
        for(int i=0;i<count;++i)base[i]=std::abs(v[start+i]-level);
        noise=float(1.4826f*median(base));return level;
    };
    double noise;
    const float baseline=reference(0,seed,noise);
    for(int i=0;i<n;++i)y[i]=(c.positive?1:-1)*(double(v[i])-baseline);
    if(c.median>1){
        filtered.resize(n);window.resize(c.median);
        if(c.median==3||c.median==5)short_median(y,filtered,c.median);
        else{
            const int radius=c.median/2;
            for(int k=0;k<c.median;++k)window[k]=y[std::clamp(k-radius,0,n-1)];
            std::sort(window.begin(),window.end());
            for(int i=0;i<n;++i){
                filtered[i]=window[radius];
                if(i+1==n)break;
                const double old=y[std::max(0,i-radius)],next=y[std::min(n-1,i+radius+1)];
                auto pos=std::lower_bound(window.begin(),window.end(),old);
                if(next>old){auto end=std::lower_bound(pos,window.end(),next);std::move(pos+1,end,pos);*(end-1)=next;}
                else if(next<old){auto start=std::lower_bound(window.begin(),pos,next);std::move_backward(start,pos,pos+1);*start=next;}
            }
        }
        y.swap(filtered);
    }
    int peak=-1;
    if(c.first){
        const double threshold=std::max(c.minimum,5*noise);
        for(int i=seed+1;i<n;++i){
            if(peak<0){if(y[i]>=threshold&&y[i-1]<threshold)peak=i;}
            else if(y[i]>y[peak])peak=i;
            else if(y[peak]-y[i]>=std::max(5*noise,.1*y[peak]))break;
        }
        if(peak<0)return 2;
    }else peak=static_cast<int>(std::max_element(y.begin(),y.end())-y.begin());
    if(c.pre_pulse){
        if(y[peak]<std::max(c.minimum,5*noise)||peak>=n-2)return 2;
        const double tolerance=std::max(3*noise,.005*y[peak]),prominence=std::max(5*noise,.1*y[peak]);
        int left=peak;
        for(int i=peak-1;i>=0;--i){
            if(y[i]<=y[left])left=i;
            if(y[i]<=tolerance||y[i]-y[left]>=prominence)break;
        }
        int edge=left;
        for(int i=left+1;i<peak;++i)if(y[i+1]-y[i]>y[edge+1]-y[edge])edge=i;
        int onset=0;
        for(int j=edge;j>=2;--j){
            const auto range=std::minmax({y[j-2],y[j-1],y[j]});
            if(range.second-range.first<=tolerance){onset=j+1;break;}
        }
        const int end=onset-c.gap;
        if(end<c.baseline)return 8;
        const double local=reference(end-c.baseline,c.baseline,noise);
        const double shift=(c.positive?1:-1)*(double(baseline)-local);
        for(double& value:y)value+=shift;
    }
    const double height=y[peak];out[0]=height;
    if(height<std::max(c.minimum,5*noise)||peak<=seed||peak>=n-2)return 2;
    const double floor=std::max(3*noise,height*.005);
    const double edge_level=std::min({floor,.1*height,height*c.cfd*.01});
    const double prominence=std::max(5*noise,.1*height);
    const auto edge=[&](int step){
        int valley=peak;
        for(int i=peak+step;i>=0&&i<n;i+=step){
            if(y[i]<=y[valley])valley=i;
            if(y[i]<=edge_level||y[i]-y[valley]>=prominence)break;
        }
        return valley;
    };
    const int lo=edge(-1);
    int hi=n-1,quiet=0;
    for(int i=peak+1;i<n;++i){
        quiet=std::abs(y[i])<=floor?quiet+1:0;
        if(quiet==3){hi=i;break;}
    }
    thread_local std::vector<double> slope;
    if(c.interpolation==1)cubic_derivatives(t,y,slope);
    else slope.clear();
    const auto* d=c.interpolation?&slope:nullptr;
    const double t10=cross(t,y,.1*height,lo,peak,true,d,c.steps),t90=cross(t,y,.9*height,lo,peak,true,d,c.steps);
    const double cfd=cross(t,y,c.cfd*.01*height,lo,peak,true,d,c.steps);
    const double missing=std::numeric_limits<double>::quiet_NaN();
    const double f10=quiet==3?cross(t,y,.1*height,peak,hi,false,d,c.steps,true):missing;
    const int end=std::isfinite(f10)?int(std::upper_bound(t.begin()+peak,t.begin()+hi+1,f10)-t.begin()):peak;
    const double f90=cross(t,y,.9*height,peak,std::min(hi,end),false,d,c.steps,true);
    if(!std::isfinite(cfd))return 3;
    int left=peak;
    while(left>lo&&y[left]>floor)--left;
    out[1]=pulse_area(t,y);out[2]=t90-t10;out[3]=f10-f90;out[4]=cfd;
    if(f10<f90)out[3]=missing;
    interval={t[left],t[quiet==3?hi-2:hi]};
    return 0;
}
struct Pulse {Index ch,role,decay,record;int origin;double onset;};
Pulse pulse(const Json& p){
    Pulse z{integer(p.at("channel")),integer(p.at("role")),integer(p.at("decay")),integer(p.at("record")),0,number(p.at("onset_ns"))};
    need(z.ch<=1&&z.role<=1,"Invalid contributor channel or role");
    integer(p.at("component"));number(p.at("origin_ns"));number(p.at("source_time_ns"));
    need(number(p.at("lifetime_ns"))>=0&&number(p.at("height_mV"))>0,"Invalid pulse origin values");
    const auto& o=p.at("light_origin");z.origin=o=="scintillation"?0:o=="cherenkov"?1:o=="mixed"?2:-1;
    need(z.origin>=0,"Unknown light origin");return z;
}
#include "lifetime_metadata.hpp"

const unsigned char* read_wave(const unsigned char* p,std::size_t bytes,int samples,const char* filter,WaveMeta& m){
    need(bytes>=16&&std::memcmp(p,"WAVE",4)==0,"Invalid waveform frame");
    const auto n=read<std::uint32_t>(p+4),crc=read<std::uint32_t>(p+8);
    need(n<=32*1024*1024&&n<=bytes-12&&n>=4,"Invalid waveform frame size");
    need(stream_crc::calculate(p+12,n)==crc,"Pulse frame CRC mismatch");
    const auto metadata=read<std::uint32_t>(p+12);
    need(metadata<=16*1024*1024&&4ull+metadata+std::size_t(samples)*16==n,"Pulse record length disagrees with sample count");
    m.clear();
    try{WaveCursor(p+16,metadata).decode(filter,m);}
    catch(const OtherLayout&){m.clear();general_metadata(p+16,metadata,filter,m);}
    m.verify(samples);
    return p+16+metadata;
}

void analyze(const unsigned char* p,std::size_t bytes,Index offset,int samples,const Channel* channels,
             const Truth& truth,const char* filter,bool sodium,Result& r){
    thread_local WaveMeta m;
    const auto* adc=read_wave(p,bytes,samples,filter,m);
    r=Result{};r.id=m.id;r.start=m.start;
    std::array<Interval,2> lobes;
    for(int ch=0;ch<2;++ch){
        r.clipped[ch]=m.clipped[ch];
        r.reason[ch]=static_cast<std::uint8_t>(extract(adc+std::size_t(ch)*samples*8,samples,channels[ch],r.features[ch],lobes[ch]));
    }
    std::array<int,2> counts{},primaries{},roles{};Index first_decay=0;bool several=false;
    std::array<Index,2> record_ids{};
    int light=-1;int scatter=0;
    for(const auto& z:m.contributors){
        const auto& records=truth.roles[z.role];
        const auto it=records.find(z.record);
        need(it!=records.end()&&it->second.offset<offset,"Waveform has an unresolved transport contribution");
        const auto& tr=it->second;const auto ch=z.ch;
        if(r.reason[ch]||z.onset>lobes[ch].to||z.onset+tr.span[ch]<lobes[ch].from)continue;
        if(!counts[0]&&!counts[1])first_decay=z.decay;else if(first_decay!=z.decay)several=true;
        ++counts[ch];roles[ch]=static_cast<int>(z.role);primaries[ch]=tr.primary_mask[ch];record_ids[ch]=z.record;
        ++r.contributions[ch][z.role];
        light=light<0?z.origin:light==z.origin?light:2;scatter|=tr.scatter[ch];
    }
    r.origin=light<0?3:light;r.scatter=static_cast<std::uint8_t>(scatter);r.category=6;
    if(!counts[0]||!counts[1])return;
    if(counts[0]>1||counts[1]>1){
        r.category=several?5:4;
    }
    else if(several)r.category=3;
    else if(roles[0]!=roles[1])r.category=0;
    else if(primaries[0] && !(primaries[0]&(primaries[0]-1)) && primaries[1] && !(primaries[1]&(primaries[1]-1))){
        // Primary IDs are local to each transport record.
        if(record_ids[0]!=record_ids[1])return;
        if(primaries[0]==primaries[1])r.category=2;
        else if(sodium && roles[0]==1)r.category=1;
    }
}
}
TP_API void* tp_lifetime_create(){try{return new Truth;}catch(...){return nullptr;}}
TP_API int tp_lifetime_abi(){return 8;}
TP_API void tp_lifetime_destroy(void* value){delete static_cast<Truth*>(value);}
TP_API int tp_lifetime_lookup(const void* value, unsigned role, Index record, Index* offset,
                              std::uint32_t* length, std::uint32_t* crc){
    if(role>=2)return 0;
    const auto& truth=*static_cast<const Truth*>(value);
    std::shared_lock guard(truth.mutex);
    const auto& records=truth.roles[role];
    const auto it=records.find(record);
    if(it==records.end())return 0;
    const auto& entry=it->second;
    *offset=entry.offset+12;*length=entry.length;*crc=entry.crc;
    return 1;
}
TP_API int tp_lifetime_truth(void* context,const unsigned char* data,std::size_t bytes,Index base,
    const std::uint32_t* offsets,int count,const TruthConfig* config,int workers,TransportRef* refs,char* message,int capacity){
    int first=count;std::string error;
    try {
        std::vector<Support> supports(count);
        #pragma omp parallel for schedule(dynamic,8) num_threads(workers) if(workers>1 && count>=24)
        for(int i=0;i<count;++i){
            try{
                const auto at=offsets[i];need(at<=bytes,"Invalid truth offset");
                const auto s=decode_truth(data+at,bytes-at,base+at,*config);
                if(refs)refs[i]={s.record,static_cast<std::uint32_t>(s.role),s.length,s.crc,0};
                supports[i]=s;
            }catch(const std::exception& e){
                #pragma omp critical(tp_lifetime_truth_error)
                {if(i<first){first=i;error=e.what();}}
            }
        }
        if(first<count){std::snprintf(message,capacity,"Transport at byte %llu: %s",static_cast<unsigned long long>(base+offsets[first]),error.c_str());return 1;}
        auto& truth=*static_cast<Truth*>(context);
        std::unique_lock guard(truth.mutex);
        for(const auto& s:supports)need(truth.roles[s.role].emplace(s.record,s).second,"Duplicate transport truth record");
        return 0;
    }catch(const std::exception& e){std::snprintf(message,capacity,"%s",e.what());return 1;}
}
TP_API int tp_lifetime_batch(const void* context,const unsigned char* data,std::size_t bytes,Index base,
    const std::uint32_t* offsets,int count,int samples,const Channel* settings,const char* filter,
    int sodium,int workers,Result* rows,char* message,int capacity){
    int first=count;std::string error;
    const auto& truth=*static_cast<const Truth*>(context);
    std::shared_lock guard(truth.mutex);
    #pragma omp parallel for schedule(dynamic,12) num_threads(workers) if(workers>1 && count>=64)
    for(int i=0;i<count;++i){
        try{
            const auto at=offsets[i];need(at<=bytes,"Invalid waveform offset");
            analyze(data+at,bytes-at,base+at,samples,settings,truth,filter,sodium!=0,rows[i]);
        }catch(const std::exception& e){
            #pragma omp critical(tp_lifetime_error)
            {if(i<first){first=i;error=e.what();}}
        }
    }
    if(first<count){std::snprintf(message,capacity,"Waveform at byte %llu: %s",static_cast<unsigned long long>(base+offsets[first]),error.c_str());return 1;}
    return 0;
}


namespace {
struct MonitorRow {
    Index id;
    double features[6]; // A/B peak, A/B area, B-A peak time, source-clock start
    unsigned classification, channels;
};
static_assert(sizeof(MonitorRow)==64);
void monitor_wave(const unsigned char* frame,std::size_t bytes,Index at,int samples,
                  const char* filter,const Truth& truth,const double* coordinates,
                  int bins,MonitorRow& row,double* densities){
    thread_local WaveMeta meta;
    const auto* payload=read_wave(frame,bytes,samples,filter,meta);
    row.id=meta.id;row.features[5]=meta.start;
    row.classification=meta.classification;row.channels=0;
    for(const auto& contributor:meta.contributors){
        const auto& records=truth.roles[contributor.role];
        const auto entry=records.find(contributor.record);
        need(entry!=records.end()&&entry->second.offset<at,"Waveform has an unresolved transport contribution");
        row.channels|=1u<<contributor.ch;
    }
    // Metadata has variable length, so the file's float arrays may be unaligned.
    thread_local std::vector<float> adc;
    thread_local std::vector<double> work;
    adc.resize(2*samples);work.resize(2*samples);
    float times[2]{};
    for(int ch=0;ch<2;++ch){
        std::memcpy(adc.data(),payload+std::size_t(ch)*samples*8,adc.size()*sizeof(float));
        const auto* axis=adc.data();
        const auto* signal=axis+samples;
        bool valid=std::isfinite(axis[0])&&std::isfinite(signal[0]);
        for(int i=1;i<samples;++i)
            valid &= std::isfinite(axis[i])&&std::isfinite(signal[i])&&axis[i]>axis[i-1];
        need(valid,"Pulse samples must be finite with increasing channel time axes");
        pulse_monitor::monitor(axis,signal,samples,meta.baseline[ch],meta.trigger-meta.start,
            row.channels&(1u<<ch)?coordinates+ch*bins:nullptr,bins,work.data(),work.data()+samples,
            densities+ch*bins,row.features[ch],row.features[2+ch],times[ch]);
    }
    row.features[4]=times[1]-times[0];
}
}

TP_API int tp_pulse_monitor_batch(const void* context,const unsigned char* data,std::size_t bytes,Index base,
    const std::uint32_t* offsets,int count,int samples,const char* filter,int workers,const double* coordinates,
    int bins,MonitorRow* rows,double* densities,char* message,int capacity){
    int first=count;std::string error;
    const auto& truth=*static_cast<const Truth*>(context);
    std::shared_lock guard(truth.mutex);
    #pragma omp parallel for schedule(static) num_threads(workers) if(workers>1 && count>=24)
    for(int i=0;i<count;++i){
        try{
            const auto at=offsets[i];need(at<=bytes,"Invalid waveform offset");
            monitor_wave(data+at,bytes-at,base+at,samples,filter,truth,coordinates,
                         bins,rows[i],densities+std::size_t(i)*2*bins);
        }catch(const std::exception& e){
            #pragma omp critical(tp_monitor_error)
            {if(i<first){first=i;error=e.what();}}
        }
    }
    if(first<count){std::snprintf(message,capacity,"Waveform at byte %llu: %s",static_cast<unsigned long long>(base+offsets[first]),error.c_str());return 1;}
    return 0;
}
