// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

#pragma once
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstring>
#if defined(TP_M2_FOLDING_CRC) && defined(_M_X64) && defined(_MSC_VER)
#include <intrin.h>
#include <wmmintrin.h>
#endif

namespace stream_crc {
// IEEE CRC-32, identical to the stream format and zlib.crc32. Process eight
// independent table lookups per group; never substitute SSE4's CRC-32C.
inline uint32_t update(uint32_t c,const unsigned char* data,std::size_t size) {
    static const auto table=[] {
        std::array<std::array<uint32_t,256>,8> t{};
        for(uint32_t i=0;i<256;++i){
            uint32_t c=i;
            for(int n=0;n<8;++n)c=(c&1)?0xedb88320u^(c>>1):c>>1;
            t[0][i]=c;
        }
        for(int k=1;k<8;++k)for(int i=0;i<256;++i)t[k][i]=t[0][t[k-1][i]&255]^(t[k-1][i]>>8);
        return t;
    }();
    while(size>=8){
        uint32_t a=uint32_t(data[0])|(uint32_t(data[1])<<8)|(uint32_t(data[2])<<16)|(uint32_t(data[3])<<24);
        a^=c;
        c=table[7][a&255]^table[6][(a>>8)&255]^table[5][(a>>16)&255]^table[4][a>>24]
          ^table[3][data[4]]^table[2][data[5]]^table[1][data[6]]^table[0][data[7]];
        data+=8;size-=8;
    }
    while(size--){c=table[0][(c^*data++)&255]^(c>>8);}
    return c;
}
#if defined(TP_M2_FOLDING_CRC) && defined(_M_X64) && defined(_MSC_VER)
inline __m128i fold(__m128i previous,__m128i next,__m128i factors){
    return _mm_xor_si128(next,_mm_xor_si128(_mm_clmulepi64_si128(previous,factors,0x00),
                                            _mm_clmulepi64_si128(previous,factors,0x11)));
}
inline uint32_t folded(const unsigned char* data,std::size_t size){
    // Four independent reflected IEEE polynomial remainders. These pairs of
    // factors advance the low and high halves by 64 bytes or 16 bytes.
    const auto four=_mm_set_epi64x(0x1c6e41596ull,0x154442bd4ull);
    const auto one=_mm_set_epi64x(0xccaa009eull,0x1751997d0ull);
    auto load=[](const unsigned char* p){return _mm_loadu_si128(reinterpret_cast<const __m128i*>(p));};
    auto a=_mm_xor_si128(load(data),_mm_cvtsi32_si128(-1));
    auto b=load(data+16),c=load(data+32),d=load(data+48);
    data+=64;size-=64;
    while(size>=64){
        a=fold(a,load(data),four);b=fold(b,load(data+16),four);
        c=fold(c,load(data+32),four);d=fold(d,load(data+48),four);
        data+=64;size-=64;
    }
    a=fold(fold(fold(a,b,one),c,one),d,one);
    while(size>=16){a=fold(a,load(data),one);data+=16;size-=16;}
    alignas(16) unsigned char tail[16];_mm_store_si128(reinterpret_cast<__m128i*>(tail),a);
    return update(update(0,tail,16),data,size)^0xffffffffu;
}
#endif
inline uint32_t calculate(const unsigned char* data,std::size_t size) {
#if defined(TP_M2_FOLDING_CRC) && defined(_M_X64) && defined(_MSC_VER)
    static const bool supported=[](){int regs[4];__cpuid(regs,1);return (regs[2]&2)!=0;}();
    if(supported&&size>=128)return folded(data,size);
#endif
    return update(0xffffffffu,data,size)^0xffffffffu;
}
}
