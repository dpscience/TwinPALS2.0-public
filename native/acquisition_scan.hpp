// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Ordered M2 discriminator scan. The Python reference remains the specification.
// Long dead-time mode only: no speculative blocks, no RNG, no waveform changes.
#pragma once
#include "analog_pmt.hpp"
#include <cstring>
#include <limits>
#include <memory>
#include <future>
#include <optional>
#include <stdexcept>

namespace acquisition_scan {
struct Pulse {
    double time, origin, span;
    uint64_t onsetOffset, onsetCount;
    uint32_t role, channel;
};
static_assert(sizeof(Pulse)==48);
struct Response { int32_t order, polarity; double tau, scale, factor; };
struct Crossing { double time, channel, a, b; };
struct State { double busy, trigger, crossA, crossB, previousA, previousB, cursor; };
struct Config { double step, filterTau, filterTail, coincidence, delay, dead, stopAt, thresholdA, thresholdB; int32_t logic, prune, stride[2]; };

class Scanner {
    const Pulse* pulses;std::size_t count;
    const unsigned char* maps[2];uint64_t sizes[2];Response responses[4];Config cfg;
    State state;double lastTime,position;std::size_t lo=0,hi=0;
    struct Grid {
        int64_t first=1,last=0;double step=0,baseTime=0;bool base=false;
        bool empty()const{return last<first&&!base;}
        std::size_t size()const{return static_cast<std::size_t>(last-first+1)+(base?1:0);}
        double operator[](size_t j)const{
            if(base&&j==0)return baseTime;
            return static_cast<double>(first+static_cast<int64_t>(j)-(base?1:0))*step;
        }
        double front()const{return (*this)[0];}
        double back()const{return static_cast<double>(last)*step;}
        void clear(){*this=Grid{};}
    };
    std::vector<double> ends,opposite[2];
    Grid deferredTimes;
    std::size_t deferredLo=0,deferredHi=0;
    uint64_t accepted=0,limit;
    bool finished=false;
    bool deferredCrossings=false;

    struct Signal {
        const Pulse& pulse;const Response& response;
        std::vector<double> owned;const double* sorted=nullptr;analog_pmt::Response shape;
        std::optional<analog_pmt::Chain> chain;
        Signal(const Pulse& p,const Response& r,const unsigned char* map,int stride,double filter):pulse(p),response(r){
            if(!p.onsetCount)return;
            if(stride==8){
                // The compact run-local index stores each channel already sorted.
                sorted=reinterpret_cast<const double*>(map+p.onsetOffset);
            }else{
                owned.resize(p.onsetCount);
                for(std::size_t k=0;k<owned.size();++k)std::memcpy(&owned[k],map+p.onsetOffset+k*stride,8);
                std::sort(owned.begin(),owned.end());sorted=owned.data();
            }
            shape.order=r.order;shape.tau=r.tau;shape.filterTau=filter;
            chain.emplace(sorted,p.onsetCount,shape,true);
        }
        double at(double time){
            const double relative=time-pulse.origin;
            double value=!chain||relative<sorted[0]?0.:chain->at(relative);
            value*=response.scale;value*=response.polarity;value*=response.factor;
            value*=response.factor<0?-response.polarity:response.polarity;return value;
        }
    };

    std::vector<double> voltage(const Grid& times,std::size_t first,std::size_t last) {
        const auto n=times.size();std::vector<double> result(n*2,0.);
        for(std::size_t i=first;i<last;++i){
            const auto& p=pulses[i];if(!p.onsetCount)continue;
            Signal signal(p,responses[p.role*2+p.channel],maps[p.role],cfg.stride[p.role],cfg.filterTau);
            for(std::size_t j=0;j<n;++j){
                result[p.channel*n+j]+=signal.at(times[j]);
            }
        }
        return result;
    }
    bool cannotCoincide(const Grid& times,bool base) const {
        if(cfg.logic!=0||!cfg.prune||base||lo==hi)return false;
        const auto ch=pulses[lo].channel;
        for(auto i=lo;i<hi;++i)if(pulses[i].channel!=ch)return false;
        const double margin=cfg.coincidence+2*cfg.step;
        const double other=ch==0?state.crossB:state.crossA;
        if(times.front()-other<=margin||times.back()+margin>=cfg.stopAt)return false;
        const auto& future=opposite[ch];const auto it=std::lower_bound(future.begin(),future.end(),times.front());
        return it==future.end()||*it>times.back()+margin;
    }
    void retireDeferred(){
        if(!deferredTimes.empty()){
            const auto values=voltage(deferredTimes,deferredLo,deferredHi);
            if(deferredCrossings){
                const auto n=deferredTimes.size();const double thresholds[2]={cfg.thresholdA,cfg.thresholdB};
                double previous[2]={state.previousA,state.previousB};
                for(std::size_t i=0;i<n;++i)for(int ch=0;ch<2;++ch){
                    const double value=values[ch*n+i];
                    if(previous[ch]<thresholds[ch]&&value>=thresholds[ch])
                        (ch==0?state.crossA:state.crossB)=deferredTimes[i]-cfg.step+cfg.step*(thresholds[ch]-previous[ch])/(value-previous[ch]);
                    previous[ch]=value;
                }
            }
            state.previousA=values[deferredTimes.size()-1];state.previousB=values.back();deferredTimes.clear();
            deferredCrossings=false;
        }
    }
    void finalize(){
        retireDeferred();
        finished=true;
    }
public:
    Scanner(const Pulse* input,uint64_t length,const unsigned char* a,uint64_t as,const unsigned char* b,uint64_t bs,
            const Response* r,const Config& c,const State& s,uint64_t maximum,double continuation=-INFINITY):pulses(input),count(length),cfg(c),state(s),position(s.cursor),limit(maximum){
        maps[0]=a;maps[1]=b;sizes[0]=as;sizes[1]=bs;std::copy(r,r+4,responses);
        for(auto stride:cfg.stride)if(stride!=8&&stride!=32)throw std::runtime_error("Invalid onset stride");
        if(!count||!(cfg.step>0)||cfg.dead<cfg.step*2048)throw std::runtime_error("Unsupported ordered scanner configuration");
        for(const auto& response:responses)
            if(response.order<2||response.order>32||!std::isfinite(response.tau)||!(response.tau>0)||!std::isfinite(response.scale)||!std::isfinite(response.factor))throw std::runtime_error("Invalid analog response");
        ends.reserve(count);lastTime=-INFINITY;
        for(std::size_t i=0;i<count;++i){
            if(input[i].channel>1||input[i].role>1)throw std::runtime_error("Invalid pulse channel");
            const auto& pulse=input[i];const auto size=sizes[pulse.role];
            if(pulse.onsetCount&&(pulse.onsetOffset>size||size-pulse.onsetOffset<8||(pulse.onsetCount-1)>(size-pulse.onsetOffset-8)/cfg.stride[pulse.role]))throw std::runtime_error("Invalid analog pulse offset");
            const double end=input[i].time+(input[i].span+cfg.filterTail);ends.push_back(end);lastTime=std::max(lastTime,end);
            opposite[1-input[i].channel].push_back(input[i].time);
        }
        lastTime=std::min(std::max(lastTime,continuation),cfg.stopAt);
    }
    int next(int blocks,Crossing* output,int capacity){
        int written=0;
        for(int block=0;block<blocks&&!finished;++block){
            if(position>=lastTime){finalize();break;}
            while(lo<count&&ends[lo]<position)++lo;
            if(lo>=count){finalize();break;}
            const bool jump=position<state.busy-cfg.coincidence-2*cfg.step;
            if(jump){
                position=std::min(lastTime,std::floor((state.busy-cfg.coincidence-2*cfg.step)/cfg.step)*cfg.step);
                if(position>=lastTime){finalize();break;}
                while(lo<count&&ends[lo]<position)++lo;
                if(lo>=count){finalize();break;}
            }
            const bool reset=pulses[lo].time>position+cfg.step;
            if(reset)position=(std::floor(pulses[lo].time/cfg.step)-1)*cfg.step;
            const double stop=std::min(position+cfg.step*2048,lastTime+cfg.step);
            while(hi<count&&pulses[hi].time<=stop)++hi;
            const auto first=static_cast<int64_t>(std::floor(position/cfg.step+.25))+1;
            const auto last=static_cast<int64_t>(std::floor(stop/cfg.step+.1));
            if(first>last){finalize();break;}
            const bool base=jump&&!reset;
            const Grid times{first,last,cfg.step,position,base};
            if(cannotCoincide(times,base)){
                deferredTimes=times;deferredLo=lo;deferredHi=hi;deferredCrossings=false;
                state.cursor=times.back();position=times.back();continue;
            }
            if(!deferredTimes.empty()){
                if(!reset&&!base)retireDeferred();
                deferredTimes.clear();deferredCrossings=false;
            }
            const auto n=times.size();
            std::vector<Signal> signals;signals.reserve(hi-lo);
            for(auto i=lo;i<hi;++i)signals.emplace_back(pulses[i],responses[pulses[i].role*2+pulses[i].channel],maps[pulses[i].role],cfg.stride[pulses[i].role],cfg.filterTau);
            // Beyond this point even simultaneous residual tails cannot reach
            // either threshold. Defer the last grid value until a following
            // block actually needs it, just as during readout dead time.
            double quietAfter=-INFINITY;
            for(const auto& s:signals){
                if(!s.pulse.onsetCount)continue;
                const auto& r=s.response;
                const double threshold=s.pulse.channel?cfg.thresholdB:cfg.thresholdA;
                const double scale=std::abs(r.scale*r.factor)*s.pulse.onsetCount/r.tau;
                const double logBound=std::log(std::max(1.,4*signals.size()*scale/threshold))+(r.order+1)*std::log(2.);
                const double duration=2*std::max(r.tau,cfg.filterTau)*logBound;
                quietAfter=std::max(quietAfter,(s.pulse.origin+s.sorted[s.pulse.onsetCount-1])+duration+2*cfg.step);
            }
            auto sample=[&](std::size_t j){std::array<double,2> v{};for(auto& s:signals)v[s.pulse.channel]+=s.at(times[j]);return v;};
            double previous[2]={state.previousA,state.previousB};
            if(base){const auto v=sample(0);previous[0]=v[0];previous[1]=v[1];state.crossA=state.crossB=-INFINITY;}
            else if(reset)previous[0]=previous[1]=0.;
            const double thresholds[2]={cfg.thresholdA,cfg.thresholdB};
            bool skipBusy=false,skipTail=false;
            for(std::size_t j=base?1:0;j<n;++j){
                if(cfg.prune&&times[j]>quietAfter){skipTail=true;break;}
                const auto values=sample(j);
                double crossed[2];bool fired[2];
                for(int ch=0;ch<2;++ch){
                    const double value=values[ch];fired[ch]=previous[ch]<thresholds[ch]&&value>=thresholds[ch];
                    if(fired[ch])crossed[ch]=times[j]-cfg.step+cfg.step*(thresholds[ch]-previous[ch])/(value-previous[ch]);
                    previous[ch]=value;
                }
                int order[2]={0,1};if(fired[0]&&fired[1]&&crossed[1]<crossed[0])std::swap(order[0],order[1]);
                for(int ch:order){
                    if(!fired[ch])continue;const double at=crossed[ch];
                    (ch==0?state.crossA:state.crossB)=at;
                    const bool selected=cfg.logic==1||cfg.logic==ch+2||(cfg.logic==0&&std::abs(at-(ch==0?state.crossB:state.crossA))<=cfg.coincidence);
                    if(!selected||at<state.busy||at<=state.trigger)continue;
                    if(written>=capacity)throw std::runtime_error("Trigger output capacity exceeded");
                    state.trigger=at;state.busy=(at+cfg.delay)+cfg.dead;
                    output[written++]={at,static_cast<double>(ch),state.crossA,state.crossB};
                    if(++accepted>=limit){finalize();return written;}
                    // Remaining crossings in this block expire before the DAQ
                    // becomes live again. Keep the exact grid deferred in case
                    // final state is needed; the next reset/jump can discard it.
                    if(cfg.prune&&state.busy-times.back()>cfg.coincidence+2*cfg.step){skipBusy=true;break;}
                }
                if(skipBusy)break;
            }
            if(skipBusy||skipTail){deferredTimes=times;deferredLo=lo;deferredHi=hi;deferredCrossings=skipBusy;}
            else{state.previousA=previous[0];state.previousB=previous[1];}
            state.cursor=times.back();position=times.back();
        }
        return written;
    }
    bool done()const{return finished;}
    State snapshot()const{return state;}
};

// A source-free interval longer than the entire readout, gate and two scan
// blocks forces a natural grid reset. Disjoint sections use the same scanner.
// The final section must have accepted a coincidence to replace both previous
// channel crossings and the busy/trigger state. Otherwise use the serial path.
inline int independent(const Pulse* input,size_t count,const unsigned char* a,uint64_t as,
                       const unsigned char* b,uint64_t bs,const Response* responses,const Config& cfg,
                       State& state,uint64_t limit,Crossing* out,int capacity,unsigned workers){
    const double block=2048*cfg.step;
    if(cfg.logic||!cfg.prune||cfg.dead<2*block||count<256||workers<2)return -2;
    // A quiet grid reset is sufficient once every possible earlier coincidence
    // has left dead time. Isolated pulses in either channel cannot extend it.
    // Include a full scan block on either side and the longest earlier tail:
    // Scanner retains pulse descriptors in input order until its front expires.
    const double resetGap=cfg.coincidence+3*block;
    double latest=-INFINITY,lastPossible=state.cursor+cfg.coincidence;
    double channelEnd[2]={-INFINITY,-INFINITY};
    std::vector<size_t> cuts{0};
    for(size_t i=0;i<count;++i){
        const auto& p=input[i];
        if(p.channel>1)return -2;
        if(i>=cuts.size()*count/workers&&i+64<count&&cuts.size()<workers
           &&p.time>latest+resetGap&&p.time>lastPossible+cfg.dead+cfg.delay+resetGap
           &&p.time>state.busy+2*block
           &&input[i].time<cfg.stopAt-block){
            cuts.push_back(i);
        }
        latest=std::max(latest,p.time+(p.span+cfg.filterTail));
        const double end=latest+2*block,other=channelEnd[1-p.channel];
        if(p.time-2*cfg.step<=other+cfg.coincidence)
            lastPossible=std::max(lastPossible,std::min(end,other)+cfg.coincidence+2*cfg.step);
        channelEnd[p.channel]=end;
    }
    if(cuts.size()==1)return -2;
    cuts.push_back(count);
    struct Part{std::vector<Crossing> events;State end;};
    auto run=[&](size_t i){
        const size_t first=cuts[i],last=cuts[i+1];
        State initial=state;
        if(first)initial={-INFINITY,-INFINITY,-INFINITY,-INFINITY,0,0,(std::floor(input[first].time/cfg.step)-1)*cfg.step};
        Scanner scan(input+first,last-first,a,as,b,bs,responses,cfg,initial,limit,
                     last<count?input[last].time-2*block:-INFINITY);
        Part result;std::array<Crossing,128> chunk;
        while(!scan.done()){
            const auto n=scan.next(128,chunk.data(),128);
            result.events.insert(result.events.end(),chunk.begin(),chunk.begin()+n);
            if(result.events.size()>static_cast<size_t>(capacity))break;
        }
        result.end=scan.snapshot();return result;
    };
    const size_t partitions=cuts.size()-1;
    std::vector<std::future<Part>> jobs;
    for(size_t i=1;i<partitions;++i)
        jobs.push_back(std::async(std::launch::async,run,i));
    std::vector<Part> parts;
    parts.reserve(partitions);
    parts.push_back(run(0));
    for(auto& job:jobs)parts.push_back(job.get());
    if(parts.back().events.empty())return -2;
    size_t used=0;
    for(const auto& part:parts){
        if(used+part.events.size()>static_cast<size_t>(capacity)||used+part.events.size()>=limit)return -2;
        std::copy(part.events.begin(),part.events.end(),out+used);used+=part.events.size();
    }
    state=parts.back().end;return static_cast<int>(used);
}
}
