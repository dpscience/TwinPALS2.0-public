// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Scalar uint64 SeedSequence and PCG64 XSL-RR for the independent acquisition
// seeds. The normal and bounded integer distributions come from NumPy itself.
// Reference: numpy/random/bit_generator.pyx and numpy/random/src/pcg64.
// Copyright (c) 2014-2015 Melissa E. O'Neill and 2019 NumPy Developers.
// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:
// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.
// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.
#pragma once
#include <array>
#include <cstdint>
#ifdef _MSC_VER
#include <intrin.h>
#endif
namespace sweep_rng {
struct BitGenerator {
    void* state;
    uint64_t (*next64)(void*);
    uint32_t (*next32)(void*);
    double (*uniform)(void*);
    uint64_t (*raw)(void*);
};
inline std::array<uint64_t,4> seedWords(uint64_t seed){
    std::array<uint32_t,4> pool{uint32_t(seed),uint32_t(seed>>32),0,0};
    uint32_t factor=0x43b0d7e5;
    auto hash=[&](uint32_t value){
        value^=factor;factor*=0x931e8875;value*=factor;return value^(value>>16);
    };
    for(auto& p:pool)p=hash(p);
    for(size_t src=0;src<4;++src)for(size_t dest=0;dest<4;++dest)if(src!=dest){
        uint32_t mixed=0xca01f9dd*pool[dest]-0x4973f715*hash(pool[src]);
        pool[dest]=mixed^(mixed>>16);
    }
    std::array<uint64_t,4> words{};factor=0x8b51f9dd;
    for(unsigned i=0;i<8;++i){
        uint32_t value=pool[i%4]^factor;factor*=0x58f38ded;value*=factor;
        words[i/2]|=uint64_t(value^(value>>16))<<(32*(i%2));
    }
    return words;
}
struct Pcg {
    struct State {uint64_t high,low;};
    static constexpr State multiplier{2549297995355413924ull,4865540595714422341ull};
    static constexpr State stride{17644330877953211035ull,15101941458738108273ull}; // multiplier^4
    static constexpr State incrementSum{6993546655799173219ull,9331354557045783068ull};
    State lanes[4],strideIncrement;
    uint64_t buffer[128];unsigned cursor=128;
    uint32_t spare=0;bool hasSpare=false;
    static State step(State x,State m,State inc){
        uint64_t upper;
#ifdef _MSC_VER
        const uint64_t product=_umul128(x.low,m.low,&upper);
#else
        const auto wide=static_cast<__uint128_t>(x.low)*m.low;
        const uint64_t product=static_cast<uint64_t>(wide);upper=wide>>64;
#endif
        const uint64_t low=product+inc.low;
        return {upper+x.high*m.low+x.low*m.high+inc.high+(low<product),low};
    }
    explicit Pcg(uint64_t seed){
        const auto words=seedWords(seed);
        State inc{2*words[2]+(words[3]>>63),2*words[3]+1};
        State current{inc.high+words[0]+(inc.low+words[1]<inc.low),inc.low+words[1]};
        current=step(current,multiplier,inc);
        for(auto& lane:lanes){current=step(current,multiplier,inc);lane=current;}
        strideIncrement=step(inc,incrementSum,{0,0}); // (1 + m + m^2 + m^3) * increment
    }
    void refill(){
        // Four disjoint subsequences of the same generator. Interleaving them
        // recovers its exact output order while the CPU can advance lanes independently.
        auto a=lanes[0],b=lanes[1],c=lanes[2],d=lanes[3];
        auto output=[](State x){
            const uint64_t value=x.high^x.low;const unsigned rot=unsigned(x.high>>58);
            return (value>>rot)|(value<<((-rot)&63));
        };
        for(unsigned i=0;i<128;i+=4){
            buffer[i]=output(a);buffer[i+1]=output(b);buffer[i+2]=output(c);buffer[i+3]=output(d);
            a=step(a,stride,strideIncrement);b=step(b,stride,strideIncrement);
            c=step(c,stride,strideIncrement);d=step(d,stride,strideIncrement);
        }
        lanes[0]=a;lanes[1]=b;lanes[2]=c;lanes[3]=d;cursor=0;
    }
    static uint64_t bits(void* ptr){
        auto& g=*static_cast<Pcg*>(ptr);
        if(g.cursor==128)g.refill();
        return g.buffer[g.cursor++];
    }
    static uint32_t half(void* ptr){
        auto& g=*static_cast<Pcg*>(ptr);
        if(g.hasSpare){g.hasSpare=false;return g.spare;}
        const uint64_t value=bits(ptr);g.spare=static_cast<uint32_t>(value>>32);
        g.hasSpare=true;return static_cast<uint32_t>(value);
    }
    static double uniform(void* p){return (bits(p)>>11)*0x1.0p-53;}
    BitGenerator interface(){return {this,bits,half,uniform,bits};}
};
}
