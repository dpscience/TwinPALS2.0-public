// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

#include "analog_pmt.hpp"
#include "stream_crc.hpp"
#include "acquisition_scan.hpp"
#include "adc_waveform.hpp"
#include "source_pulses.hpp"
#include "wave_frames.hpp"
#include "transport_index.hpp"
#include <cstring>
#ifdef _WIN32
#define API extern "C" __declspec(dllexport)
#else
#define API extern "C"
#endif

API uint32_t tp_stream_crc32(const unsigned char* data,std::size_t size) {
    return stream_crc::calculate(data,size);
}
API int64_t tp_wave_frames(const wave_frames::Library* libraries,const uint64_t* keys,uint64_t keyCount,
        const uint32_t* perWave,const unsigned char* const* waves,const uint64_t* lengths,
        uint32_t count,unsigned char* out,uint64_t capacity,uint64_t* offsets){
    return wave_frames::pack(libraries,keys,keyCount,perWave,waves,lengths,count,out,capacity,offsets);
}

// Public ABI used by the standalone, single-channel digitizer, including older callers.
struct AdcPulseDescriptor {
    const double* onsets;
    int32_t count,order;
    double origin,tau,scale,polarity,factor;
};
API int tp_adc_waveform(const double* times,const double* background,int n,const AdcPulseDescriptor* pulses,int count,
                        double filter,double low,double high,double lsb,unsigned levels,float* output,int* clipped){
    if(n<1||count<0||!(lsb>0)||levels<2)return 1;
    try{
        std::vector<adc_waveform::Pulse> descriptors;
        descriptors.reserve(count);
        for(int i=0;i<count;++i){
            const auto& p=pulses[i];
            descriptors.push_back({p.onsets,p.count,p.order,p.origin,p.tau,p.scale,p.polarity,p.factor});
        }
        return adc_waveform::sample(times,background,n,descriptors.data(),count,filter,low,high,lsb,levels,output,clipped);
    }
    catch(...){return 2;}
}

API int tp_source_pulses(const source_pulses::Library* libs,const double* delays,const double* gains,uint64_t first,int n,
                         const int64_t* a,const int64_t* b,const double* t,const double* life,const uint16_t* components,source_pulses::Pulse* out){
    return source_pulses::generate(libs,delays,gains,first,n,a,b,t,life,components,out);
}

// Convert the two source libraries' immutable indexes directly into the scan
// descriptors. Scalar gathers avoid temporary masks and copies of entire rows.
struct ScanLibraryIndex {
    const uint64_t* index;
    const uint64_t* onsets;
    uint64_t records;
};
API int tp_scan_descriptors(const source_pulses::Pulse* pulses,size_t count,const ScanLibraryIndex* libs,
                            double filterTail,acquisition_scan::Pulse* out,double* maximum){
    double tail=0.;
    for(size_t i=0;i<count;++i){
        const auto& p=pulses[i];
        if(p.role>1||p.channel>1||p.record>=libs[p.role].records)return 1;
        const auto& lib=libs[p.role];const auto* row=lib.index+3*p.record;
        const auto base=lib.onsets?lib.onsets[p.record]:row[0]+24;
        const uint64_t stride=lib.onsets?8:32;
        out[i]={p.time,p.origin,p.span,base+(p.channel?row[1]*stride:0),row[1+p.channel],p.role,p.channel};
        tail=std::max(tail,p.span+filterTail);
    }
    *maximum=tail;return 0;
}

// Same ordered bin doubling and integer increments as AcquiredPersistence.
// One short call avoids per-waveform NumPy dispatch in the serial publisher.
API double tp_acquired_density(const double* values,uint64_t* grid,int bins,double maximum){
    if(bins<=0||bins>4096||bins%2||!std::isfinite(maximum)||maximum<=0)return -1;
    double peak=0;for(int x=0;x<bins;++x)if(std::isfinite(values[x])&&values[x]>peak)peak=values[x];
    while(peak>=maximum){
        for(int y=0;y<bins/2;++y)for(int x=0;x<bins;++x)grid[y*bins+x]=grid[2*y*bins+x]+grid[(2*y+1)*bins+x];
        std::fill(grid+(bins/2)*bins,grid+bins*bins,uint64_t(0));maximum*=2;
    }
    for(int x=0;x<bins;++x)if(std::isfinite(values[x])&&values[x]>0){
        const int y=static_cast<int>((values[x]*bins)/maximum);if(y<0||y>=bins)return -2;++grid[y*bins+x];
    }
    return maximum;
}

API int tp_acquired_density_batch(const double* y,const uint8_t* valid,int count,uint64_t* grids,int bins,double* maxima){
    for(int i=0;i<count;++i)for(int ch=0;ch<2;++ch)if(valid[i*2+ch]){
        const auto v=tp_acquired_density(y+(i*2+ch)*bins,grids+ch*bins*bins,bins,maxima[ch]);
        if(v<=0)return -1;
        maxima[ch]=v;
    }
    return 0;
}

API void* tp_acquisition_scan_create(const acquisition_scan::Pulse* pulses,uint64_t count,const unsigned char* a,uint64_t as,const unsigned char* b,uint64_t bs,
        const acquisition_scan::Response* response,const acquisition_scan::Config* config,const acquisition_scan::State* state,uint64_t limit){
    try{return new acquisition_scan::Scanner(pulses,count,a,as,b,bs,response,*config,*state,limit);}catch(...){return nullptr;}
}
API int tp_acquisition_scan_next(void* handle,int blocks,acquisition_scan::Crossing* output,int capacity,acquisition_scan::State* state,int* done){
    if(!handle||blocks<=0||capacity<blocks)return -1;
    try{auto* scanner=static_cast<acquisition_scan::Scanner*>(handle);const int n=scanner->next(blocks,output,capacity);*state=scanner->snapshot();*done=scanner->done();return n;}catch(...){return -2;}
}
API void tp_acquisition_scan_destroy(void* handle){delete static_cast<acquisition_scan::Scanner*>(handle);}
API int tp_acquisition_independent(const acquisition_scan::Pulse* pulses,uint64_t count,const unsigned char* a,uint64_t as,const unsigned char* b,uint64_t bs,
        const acquisition_scan::Response* response,const acquisition_scan::Config* config,acquisition_scan::State* state,uint64_t limit,
        acquisition_scan::Crossing* out,int capacity,unsigned workers){
    try{return acquisition_scan::independent(pulses,count,a,as,b,bs,response,*config,*state,limit,out,capacity,workers);}
    catch(...){return -1;}
}

API void* tp_transport_index_map(const unsigned char* data,uint64_t size,const char* config,const transport_index::Arrays* arrays){
    try{return new transport_index::Reader(data,size,config,*arrays);}catch(...){return nullptr;}
}
API int tp_transport_index_window(void* handle,const unsigned char* buffer,uint64_t size,unsigned workers,uint64_t* offset,uint64_t* count,transport_index::Summary* summary){
    if(!handle||!buffer||!size||workers<1||workers>64)return -1;
    auto* reader=static_cast<transport_index::Reader*>(handle);
    int result=reader->nextWindow(buffer,*offset,size,workers);
    *count=reader->completed();*offset=reader->bytePosition();*summary=reader->counters();return result;
}
API const char* tp_transport_index_footer(void* handle){return static_cast<transport_index::Reader*>(handle)->completion();}
API const char* tp_transport_index_error(void* handle){return static_cast<transport_index::Reader*>(handle)->failure();}
API void tp_transport_index_destroy(void* handle){delete static_cast<transport_index::Reader*>(handle);}
API int tp_transport_index_sorted_onsets(void* handle,uint64_t first,double* out,uint64_t capacity){
    return static_cast<transport_index::Reader*>(handle)->packOnsets(first,out,capacity)?0:1;
}

API int tp_analog_evaluate(const double* onsets,int count,const double* times,int points,int order,double tau,double filterTau,double* out) {
    if(count<0||points<0||order<2||order>32||!std::isfinite(tau)||tau<=0)return 1;
    try {
        if(!count){std::fill(out,out+points,0.);return 0;}
        std::vector<double> sorted(onsets,onsets+count);std::sort(sorted.begin(),sorted.end());
        analog_pmt::Response r;r.order=order;r.tau=tau;r.filterTau=filterTau;
        analog_pmt::Chain chain(sorted,r);
        double last=-INFINITY;
        for(int i=0;i<points;++i){
            if(!std::isfinite(times[i])||times[i]<last)return 2;
            last=times[i];out[i]=times[i]<sorted.front()?0.:chain.at(times[i]);
        }
        return 0;
    }catch(...){return 3;}
}

API double tp_analog_peak(const double* onsets,int count,int order,double tau) {
    if(count<0||order<2||order>32||tau<=0)return -1;
    try{analog_pmt::Response r;r.order=order;r.tau=tau;return analog_pmt::peak(std::vector<double>(onsets,onsets+count),r);}catch(...){return -1;}
}

// A bounded batch of real pulses. The spool interleaves onsets, arrivals and
// provenance, so onset offsets are in bytes and need not be double-aligned.
API int tp_persistence_batch(const unsigned char* bytes,size_t length,const uint64_t* rows,int pulses,
        const double* times,int bins,int order,double tau,double charge,double ymax,int64_t* grids) {
    if(bins<10 || bins>1000 || pulses<0 || !(ymax>0) || !(charge>0))return 1;
    try {
        std::vector<double> onsets,values(bins);
        for(int i=0;i<pulses;++i) {
            const auto offset=rows[3*i], count=rows[3*i+1], origin=rows[3*i+2];
            if(!count || count>INT32_MAX || offset>length || count>(length-offset)/sizeof(double) || origin>2)return 2;
            onsets.resize(count);
            std::memcpy(onsets.data(),bytes+offset,count*sizeof(double));
            if(tp_analog_evaluate(onsets.data(),static_cast<int>(count),times,bins,order,tau,0.,values.data()))return 3;
            for(int x=0;x<bins;++x) {
                const double value=std::abs(values[x]*(charge*1e12))/(count*charge*1e12);
                if(value<=ymax*1e-12)continue;
                const int y=std::min(bins-1,static_cast<int>(std::floor(value/ymax*bins)));
                ++grids[(origin*bins+y)*bins+x];
            }
        }
        return 0;
    }catch(...){return 4;}
}

// Validate packed, potentially unaligned stream nodes in one pass. This keeps
// every format invariant while avoiding many tiny NumPy operations per event.
API int tp_transport_validate(const unsigned char* nodes,int count,const unsigned char* refs,int refCount,int processes,int components) {
    if(count<0||refCount<0||processes<0)return 1;
    for(int i=0;i<count;++i){
        const auto* p=nodes+static_cast<std::size_t>(i)*128;
        uint32_t u[8];double x[12];std::memcpy(u,p,32);std::memcpy(x,p+32,96);
        if(u[0]>=static_cast<uint32_t>(i+1)||!u[1]||u[3]>2||u[7]>=static_cast<uint32_t>(processes)||x[4]<0||x[5]<0)return 1;
        for(double v:x)if(!std::isfinite(v))return 1;
        if(components>=0&&(u[4]>=static_cast<uint32_t>(components)||u[5]>=static_cast<uint32_t>(components)))return 2;
    }
    for(int i=0;i<refCount;++i){uint32_t ref;std::memcpy(&ref,refs+static_cast<std::size_t>(i)*4,4);if(!ref||ref>static_cast<uint32_t>(count))return 3;}
    return 0;
}
