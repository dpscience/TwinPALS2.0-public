// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Construct accepted digitizer windows on worker threads. All state belongs to
// the caller's finite batch, including its original per-window NumPy generators.
#include "acquisition_scan.hpp"
#include "adc_waveform.hpp"
#include "source_pulses.hpp"
#include "stream_crc.hpp"
#include "pulse_monitor.hpp"
#include "wave_frames.hpp"
#include "sweep_rng.hpp"
#include "sweep_shape_cache.hpp"
#ifdef TP_NUMPY_NORMAL_TABLES
#include "vendor/numpy_normal_tables.hpp"
#endif
#include <charconv>
#include <string>

#ifdef _WIN32
#define SWEEP_API extern "C" __declspec(dllexport)
#else
#define SWEEP_API extern "C"
#endif
#ifdef TP_NUMPY_RANDOM
extern "C" void random_standard_normal_fill(void*,std::intptr_t,double*);
extern "C" double random_standard_normal(void*);
extern "C" uint64_t random_bounded_uint64(void*,uint64_t,uint64_t,uint64_t,bool);

namespace sweeps {
void normals(sweep_rng::BitGenerator* rng,int n,double* output){
#ifdef TP_NUMPY_NORMAL_TABLES
    auto& generator=*static_cast<sweep_rng::Pcg*>(rng->state);
    int written=0;
    while(written<n){
        if(generator.cursor==128)generator.refill();
        unsigned cursor=generator.cursor,end=cursor+std::min<unsigned>(128-cursor,n-written);
        while(cursor<end){
            const uint64_t raw=generator.buffer[cursor];
            const unsigned strip=raw&255;
            const auto magnitude=(raw>>9)&0xfffffffffffffull;
            if(magnitude>=numpy_normal::ki_double[strip])break;
            const double value=magnitude*numpy_normal::wi_double[strip];
            output[written++]=(raw&256)?-value:value;
            ++cursor;
        }
        generator.cursor=cursor;
        // The library sees the original unconsumed word and performs all
        // rejection and tail draws, including refilling across buffer edges.
        if(cursor<end)output[written++]=random_standard_normal(rng);
    }
#else
    random_standard_normal_fill(rng,n,output);
#endif
}
using Pulse=source_pulses::Pulse;
using Crossing=acquisition_scan::Crossing;
struct Input {
    const unsigned char* data;
    uint64_t size;
    int stride;
};
struct Settings {
    int samples,switched,levels,coincidence;
    double window,delay,dead,gate,filter,baseline,jitter,irf,noise,low,high,lsb;
};
struct Result {
    uint64_t begin,end,keyBegin,keyEnd;
    uint32_t metadataSize,classification,channels,reserved;
};
struct Key {uint64_t role,record,channel;};
constexpr const char* classes[]={"single","true_A_start","true_B_start","same_primary_1",
    "same_primary_2","mixed_same_decay","accidental","pileup"};
constexpr const char* origins[]={"none","scintillation","cherenkov","mixed"};

void integer(std::string& out,uint64_t value){
    char buf[32];auto end=std::to_chars(buf,buf+sizeof(buf),value).ptr;out.append(buf,end);
}
// Both Python repr and to_chars use the shortest round-tripping decimal.
// Python switches to scientific notation outside decimal exponents [-4,15].
void number(std::string& out,double value){
    if(!std::isfinite(value))throw std::domain_error("Non-finite waveform metadata");
    if(std::signbit(value)){out+='-';value=-value;}
    char buf[40];char* end=std::to_chars(buf,buf+sizeof(buf),value,std::chars_format::scientific).ptr;
    char* e=std::find(buf,end,'e');const bool negative=e[1]=='-';
    int exponent=0;std::from_chars(e+2,end,exponent);if(negative)exponent=-exponent;
    if(exponent< -4||exponent>=16){out.append(buf,end);return;}
    char digits[24];int count=0;
    for(auto i=buf;i<e;++i)if(*i!='.')digits[count++]=*i;
    int split=exponent+1;
    if(split<=0){out+="0.";out.append(-split,'0');out.append(digits,count);}
    else if(split>=count){out.append(digits,count);out.append(split-count,'0');out+=".0";}
    else{out.append(digits,split);out+='.';out.append(digits+split,count-split);}
}
void truth(std::string& out,const Pulse& p,double start){
    out+="{\"channel\":";integer(out,p.channel);
    out+=",\"component\":";integer(out,p.component);
    out+=",\"decay\":";integer(out,p.decay);
    out+=",\"height_mV\":";number(out,p.height);
    out+=",\"lifetime_ns\":";number(out,p.life);
    out+=",\"light_origin\":\"";out+=origins[p.light];out+="\",\"onset_ns\":";number(out,p.time-start);
    out+=",\"origin_ns\":";number(out,p.origin-start);
    out+=",\"record\":";integer(out,p.record);
    out+=",\"role\":";integer(out,p.role);
    out+=",\"source_time_ns\":";number(out,p.source);out+='}';
}
int label(const std::vector<const Pulse*>& chosen,int* channels,bool& decays,bool& roles){
    const Pulse *first[2]={};
    for(auto p:chosen){
        ++channels[p->channel];first[p->channel]=p;
        decays|=p->decay!=chosen.front()->decay;roles|=p->role!=chosen.front()->role;
    }
    if(channels[0]>1||channels[1]>1)return decays?7:5;
    if(!first[0]||!first[1])return 0;
    if(decays)return 6;
    if(!roles)return 3+first[0]->role;
    return first[0]->role?2:1;
}
const char* boolean(bool v){return v?"true":"false";}
void metadata(std::string& out,const Settings& s,uint64_t serial,const Crossing& c,
              double start,double finish,double busy,double low,double high,double observed,
              const Pulse* tlBegin,const Pulse* tlEnd,const std::vector<const Pulse*>& chosen,
              uint32_t cell,const int* clipped,Result& result){
    const int ch=static_cast<int>(c.channel);int counts[2]={};bool decays=false,roles=false;
    result.classification=label(chosen,counts,decays,roles);
    result.channels=(counts[0]?1u:0u)|(counts[1]?2u:0u);result.reserved=0;
    out.clear();out+="{\"accepted_crossings_ns\":[";
    if(s.coincidence){number(out,c.a);out+=',';number(out,c.b);}
    else if(ch==0){number(out,c.time);out+=",null";}else{out+="null,";number(out,c.time);}
    out+="],\"acquisition_rate_Hz\":";number(out,(serial+1)*1e9/std::max(busy,1e-9));
    out+=",\"baseline_mV\":[";number(out,s.baseline);out+=',';number(out,s.baseline);
    out+="],\"busy_until_ns\":";number(out,busy);
    out+=",\"class\":\"";out+=classes[result.classification];out+="\",\"clipped\":[";
    out+=boolean(clipped[0]);out+=',';out+=boolean(clipped[1]);out+="],\"coincidence_window_ns\":";
    if(s.coincidence){double a=std::min(c.a,c.b);out+='[';number(out,a);out+=',';number(out,a+s.gate);out+=']';}
    else out+="null";
    out+=",\"end_ns\":";number(out,finish);
    out+=",\"flags\":{\"mixed_primaries\":";out+=boolean(roles);
    out+=",\"multiple_decays\":";out+=boolean(decays);out+=",\"pileup_A\":";out+=boolean(counts[0]>1);
    out+=",\"pileup_B\":";out+=boolean(counts[1]>1);out+="},\"id\":";integer(out,serial);
    out+=",\"pulses\":[";bool comma=false;
    for(auto p:chosen){if(comma)out+=',';truth(out,*p,start);comma=true;}
    out+="],\"start_ns\":";number(out,start);
    out+=",\"timeline\":{\"high_ns\":";number(out,high);out+=",\"known_until_ns\":";number(out,observed);
    out+=",\"low_ns\":";number(out,low);out+=",\"pulses\":[";
    for(auto p=tlBegin;p!=tlEnd;++p){if(p!=tlBegin)out+=',';truth(out,*p,start);}
    out+="],\"total\":";integer(out,tlEnd-tlBegin);out+="},\"trigger_cell\":";integer(out,cell);
    out+=",\"trigger_channel\":";integer(out,ch);out+=",\"trigger_ns\":";number(out,c.time);out+='}';
}

}

SWEEP_API void* tp_sweep_cache_create(){try{return new sweep_shape::Cache;}catch(...){return nullptr;}}
SWEEP_API void tp_sweep_cache_destroy(sweep_shape::Cache* cache){delete cache;}
SWEEP_API int tp_accepted_sweeps_v2(const sweeps::Settings* settings,const sweeps::Input* maps,
        const acquisition_scan::Response* response,const double* baseAxes,const sweeps::Pulse* pulses,
        int pulseCount,const uint64_t* addresses,double maximumTail,double filterTail,double known,
        const sweeps::Crossing* crossings,const uint64_t* seeds,uint64_t serial,int batch,
        const double* xA,const double* xB,int bins,unsigned char* buffer,uint64_t capacity,
        sweeps::Result* rows,sweeps::Key* keys,uint64_t keyCapacity,double* features,double* densities,
        sweep_shape::Cache* cache){
    using namespace sweeps;
    try{
        const auto& s=*settings;const int n=s.samples;
        if(n<2||n>8192||pulseCount<0||batch<1||bins<1)return 1;
        std::vector<double> random(4*n+2),evaluation(n),background(n),norm(n),work(n);
        std::vector<float> samples(4*n);std::vector<const Pulse*> chosen;
        std::vector<adc_waveform::Pulse> signals[2];std::vector<std::vector<double>> copied;
        std::vector<sweep_shape::Entry> tables;
        uint64_t cursor=0,keyCount=0;std::string json;json.reserve(8192);
        auto lower=[&](double time){return std::lower_bound(pulses,pulses+pulseCount,time,
                      [](const Pulse& p,double t){return p.time<t;});};
        for(int i=0;i<batch;++i){
            const auto& c=crossings[i];auto& row=rows[i];
            const double end=c.time+s.delay,start=end-s.window,busy=end+s.dead,margin=(end-start)*.2;
            const double low=start-margin,high=busy+margin,observed=std::max(end,std::min(high,known));
            const auto tlBegin=lower(low),tlEnd=lower(observed);
            // Dense timeline decimation remains in the reference worker.
            if(tlEnd-tlBegin>256)return 1;
            chosen.clear();copied.clear();tables.clear();signals[0].clear();signals[1].clear();row.keyBegin=keyCount;
            for(auto p=lower(start-maximumTail),last=lower(end);p!=last;++p){
                if(p->time+p->span+filterTail<=start)continue;
                if(p->channel>1||p->role>1||p->light>3)return -1;
                const auto& map=maps[p->role];const auto* addr=addresses+2*(p-pulses);
                if(keyCount>=keyCapacity)return 1;
                if(map.stride<8||addr[0]>map.size||addr[1]>INT32_MAX||
                   (addr[1]&&(map.size-addr[0]<8||(addr[1]-1)>(map.size-addr[0]-8)/map.stride)))return -1;
                const auto* data=map.data+addr[0];const auto* onsets=reinterpret_cast<const double*>(data);
                if(map.stride!=8){auto& v=copied.emplace_back(addr[1]);
                    for(size_t j=0;j<v.size();++j)std::memcpy(&v[j],data+j*map.stride,8);
                    onsets=v.data();
                }
                const auto& r=response[2*p->role+p->channel];
                signals[p->channel].push_back({onsets,static_cast<int>(addr[1]),r.order,p->origin,r.tau,r.scale,
                                               static_cast<double>(r.polarity),r.factor});
                if(cache){
                    auto& signal=signals[p->channel].back();
                    tables.push_back(cache->get(p->record,p->role,p->channel,signal,s.filter));
                    signal.table=tables.back().get();
                }
                chosen.push_back(p);keys[keyCount++]={p->role,p->record,p->channel};
            }
            row.keyEnd=keyCount;
            sweep_rng::Pcg generator(seeds[i]);auto bitgen=generator.interface();auto* rng=&bitgen;
            uint32_t cell=s.switched?static_cast<uint32_t>(random_bounded_uint64(rng,0,n-1,0,false)):0;
            const auto* base=baseAxes+static_cast<size_t>(cell)*2*n;
            bool valid=false;int clipped[2]={};
            for(int attempt=0;attempt<32&&!valid;++attempt){
                normals(rng,2*n,random.data());valid=true;
                for(int ch=0;ch<2;++ch)for(int j=0;j<n;++j){
                    int k=ch*n+j;random[k]=base[k]+s.jitter*random[k];
                    auto* axis=samples.data()+2*ch*n;axis[j]=static_cast<float>(random[k]);
                    if(j&&axis[j]<=axis[j-1])valid=false;
                }
            }
            if(!valid)return 1;
            normals(rng,2*n+2,random.data()+2*n);
            float peakTime[2];double* f=features+5*i;
            for(int ch=0;ch<2;++ch){
                double shift=s.irf*random[2*n+ch];
                for(int j=0;j<n;++j){
                    evaluation[j]=(start+random[ch*n+j])-shift;
                    background[j]=s.baseline+s.noise*random[2*n+2+ch*n+j];
                }
                auto axis=samples.data()+2*ch*n;auto values=axis+n;
                adc_waveform::sample(evaluation.data(),background.data(),n,signals[ch].data(),
                    static_cast<int>(signals[ch].size()),s.filter,s.low,s.high,s.lsb,s.levels,values,&clipped[ch]);
                pulse_monitor::monitor(axis,values,n,s.baseline,c.time-start,ch?xB:xA,bins,norm.data(),work.data(),
                        densities+(2*i+ch)*bins,f[ch],f[2+ch],peakTime[ch]);
            }
            f[4]=peakTime[1]-peakTime[0];
            metadata(json,s,serial+i,c,start,end,busy,low,high,observed,tlBegin,tlEnd,chosen,cell,clipped,row);
            const uint32_t jsonBytes=static_cast<uint32_t>(json.size());
            const uint32_t bytes=4+jsonBytes+static_cast<uint32_t>(samples.size()*sizeof(float));
            if(bytes>32*1024*1024||cursor+12+bytes>capacity)return 1;
            auto frame=buffer+cursor;std::memcpy(frame,"WAVE",4);std::memcpy(frame+4,&bytes,4);
            std::memcpy(frame+12,&jsonBytes,4);std::memcpy(frame+16,json.data(),jsonBytes);
            std::memcpy(frame+16+jsonBytes,samples.data(),samples.size()*sizeof(float));
            auto crc=stream_crc::calculate(frame+12,bytes);std::memcpy(frame+8,&crc,4);
            row.begin=cursor;cursor+=12+bytes;row.end=cursor;row.metadataSize=jsonBytes;
        }
        return 0;
    }catch(...){return -1;}
}
#endif

#ifdef TP_NUMPY_RANDOM
// Reserve first occurrences in stream order. The caller can then fetch disjoint
// histories for several consecutive batches concurrently, including on a cold SSD.
SWEEP_API int64_t tp_sweep_histories(const wave_frames::Library* libs,unsigned char* seenA,
        unsigned char* seenB,uint64_t frameBytes,const sweeps::Result* rows,uint32_t count,
        const sweeps::Key* keys,uint64_t keyCount,uint64_t limit,uint64_t* records,
        uint32_t* perWave,uint64_t* newCount){
    unsigned char* seen[2]={seenA,seenB};
    uint64_t size=frameBytes,used=0;
    auto rollback=[&](){for(uint64_t j=0;j<used;++j)seen[records[2*j]][records[2*j+1]]=0;};
    for(uint32_t i=0;i<count;++i){
        const auto& r=rows[i];perWave[i]=0;
        if(r.end<r.begin||r.end>frameBytes||r.keyBegin>r.keyEnd||r.keyEnd>keyCount){
            rollback();return -1;
        }
        for(auto j=r.keyBegin;j<r.keyEnd;++j){
            const auto& k=keys[j];
            if(k.role>1||k.record>=libs[k.role].count){rollback();return -1;}
            if(seen[k.role][k.record])continue;
            const auto& lib=libs[k.role];const auto* index=lib.index+3*k.record;
            size+=12+16+16+34*(index[1]+index[2])+lib.provenance[2*k.record+1];
            records[2*used]=k.role;records[2*used+1]=k.record;++used;
            seen[k.role][k.record]=1;++perWave[i];
        }
    }
    *newCount=used;
    if(size>limit)rollback();
    return static_cast<int64_t>(size);
}

SWEEP_API int64_t tp_copy_sweeps(const wave_frames::Library* libs,const unsigned char* frames,
        const sweeps::Result* rows,uint32_t count,const uint64_t* records,uint64_t newCount,
        const uint32_t* perWave,unsigned char* out,uint64_t capacity,uint64_t* offsets){
    try{
        std::vector<uint64_t> lengths(count);std::vector<const unsigned char*> waves(count);
        for(uint32_t i=0;i<count;++i){
            waves[i]=frames+rows[i].begin;lengths[i]=rows[i].end-rows[i].begin;
        }
        return wave_frames::pack(libs,records,newCount,perWave,waves.data(),lengths.data(),
                                 count,out,capacity,offsets);
    }catch(...){return -1;}
}
#endif
