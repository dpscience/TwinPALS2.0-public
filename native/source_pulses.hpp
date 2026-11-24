// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

#pragma once
#include <algorithm>
#include <cstdint>

namespace source_pulses {
// On-disk records have independent detector columns. This layout is the
// transient NumPy PULSE_DTYPE consumed by both discriminator implementations.
#pragma pack(push,1)
struct Pulse {
    double time,height;uint8_t channel,role;uint64_t decay,record;
    double source,life;uint16_t component;double origin,span,peakTime;uint8_t light;
};
#pragma pack(pop)
static_assert(sizeof(Pulse)==77);
struct Library {
    const uint8_t* eligible;const double *starts,*spans,*peaks;const uint8_t* light;
    uint64_t size;
};
inline int generate(const Library* libs,const double* delays,const double* gains,uint64_t first,int count,
                    const int64_t* indicesA,const int64_t* indicesB,const double* times,const double* lifetime,
                    const uint16_t* components,Pulse* output){
    auto* end=output;
    for(int i=0;i<count;++i){
        for(uint8_t role=0;role<2;++role){
            const auto& lib=libs[role];
            const uint64_t record=role?indicesB[i]:indicesA[i];
            if(record>=lib.size)return -1;
            const auto mask=lib.eligible[record];
            for(uint8_t ch=0;ch<2;++ch)if(mask&(1u<<ch)){
                const auto index=record*2+ch;
                const double origin=(times[i]+delays[ch])+(role?lifetime[i]:0.);
                const double time=origin+lib.starts[index];
                *end++={time,lib.peaks[index]*gains[ch],ch,role,first+static_cast<uint64_t>(i),record,
                        times[i],lifetime[i],components[i],origin,lib.spans[index],time,lib.light[index]};
            }
        }
    }
    auto earlier=[](const Pulse& a,const Pulse& b){
        if(a.time!=b.time)return a.time<b.time;
        if(a.height!=b.height)return a.height<b.height;
        if(a.channel!=b.channel)return a.channel<b.channel;
        if(a.role!=b.role)return a.role<b.role;
        return a.decay<b.decay; // at most one pulse per decay, role and channel
    };
    // Source clocks are ordered. Only channel delays and lifetimes can move
    // pulses past their neighbours. Bound insertion work for long delays.
    size_t moved=0;
    for(auto it=output+int(end!=output);it<end;++it){
        if(!earlier(*it,it[-1]))continue;
        const Pulse value=*it;auto pos=it;
        do{*pos=pos[-1];--pos;}while(pos>output&&earlier(value,pos[-1]));
        *pos=value;moved+=it-pos;
        if(moved>4*static_cast<size_t>(end-output)){std::sort(output,end,earlier);break;}
    }
    return static_cast<int>(end-output);
}
}
