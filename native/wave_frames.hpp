// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Assemble a bounded group of existing WAVE frames and newly referenced M1
// histories in file order. The input frame CRCs have already been verified.
#pragma once
#include "stream_crc.hpp"
#include <algorithm>
#include <limits>

namespace wave_frames {
struct Library {
    const unsigned char* data;const uint64_t *index,*provenance;uint64_t size,count;
};
inline uint32_t multiply(uint32_t a,uint32_t b){
    uint32_t product=0;
    for(uint32_t mask=1u<<31;mask;mask>>=1){
        if(a&mask)product^=b;
        b=(b>>1)^(b&1?0xedb88320u:0);
    }
    return product;
}
// Multiplication by x^(8*length) in the reflected IEEE CRC field.
inline uint32_t combine(uint32_t left,uint32_t right,uint64_t length){
    static const auto powers=[]{
        std::array<uint32_t,64> p{};uint32_t x=1u<<30;
        for(int i=0;i<3;++i)x=multiply(x,x);
        for(auto& v:p){v=x;x=multiply(x,x);}
        return p;
    }();
    for(int i=0;length;length>>=1,++i)if(length&1)left=multiply(powers[i],left);
    return left^right;
}
inline int64_t pack(const Library* libs,const uint64_t* keys,uint64_t keyCount,
                    const uint32_t* perWave,const unsigned char* const* waves,const uint64_t* lengths,
                    uint32_t count,unsigned char* out,uint64_t capacity,uint64_t* offsets){
    uint64_t cursor=0,key=0;
    for(uint32_t i=0;i<count;++i){
        for(uint32_t j=0;j<perWave[i];++j){
            if(key>=keyCount)return -1;
            const auto role=keys[2*key],record=keys[2*key+1];++key;
            if(role>1||record>=libs[role].count)return -1;
            const auto& lib=libs[role];const auto* index=lib.index+3*record;
            const auto a=index[0],an=16+34*(index[1]+index[2]),p=lib.provenance[record*2],pn=lib.provenance[2*record+1];
            const auto payload=16+an+pn;
            if(payload>32*1024*1024||a<4||a>lib.size||an>lib.size-a||p<4||p>lib.size||pn>lib.size-p)return -1;
            if(cursor+12+payload<=capacity){
                auto* prefix=out+cursor;auto* header=prefix+12;
                const uint32_t r=static_cast<uint32_t>(role),length=static_cast<uint32_t>(payload),analogBytes=static_cast<uint32_t>(an);
                std::memcpy(prefix,"TRTH",4);std::memcpy(prefix+4,&length,4);
                std::memcpy(header,&r,4);std::memcpy(header+4,&record,8);std::memcpy(header+12,&analogBytes,4);
                uint32_t ca,cp;std::memcpy(&ca,lib.data+a-4,4);std::memcpy(&cp,lib.data+p-4,4);
                const uint32_t crc=combine(combine(stream_crc::calculate(header,16),ca,an),cp,pn);
                std::memcpy(prefix+8,&crc,4);std::memcpy(header+16,lib.data+a,an);std::memcpy(header+16+an,lib.data+p,pn);
            }
            cursor+=12+payload;
        }
        offsets[i]=cursor;
        if(cursor+lengths[i]<=capacity)std::memcpy(out+cursor,waves[i],lengths[i]);
        cursor+=lengths[i];
    }
    return key==keyCount?static_cast<int64_t>(cursor):-1;
}
}
