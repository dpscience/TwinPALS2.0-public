// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Filtered response of an original M1 pulse; acquisition jitter, noise and
// sampling coordinates always belong to the particular accepted M2 window.
#pragma once
#include "adc_waveform.hpp"
#include <deque>
#include <memory>
#include <mutex>
#include <unordered_map>

namespace sweep_shape {
using Table=adc_waveform::SampledResponse;
using Entry=std::shared_ptr<const Table>;

inline Entry build(const adc_waveform::Pulse& p,double filter){
    if(p.order!=std::floor(p.order)||p.order<12||p.order>24||p.count<16||p.count>65536||!(p.tau>0)||
       (filter>0&&(filter/p.tau<.25||filter/p.tau>4||std::abs(filter/p.tau-1)<1e-5)))return {};
    std::vector<double> sorted(p.onsets,p.onsets+p.count);
    if(!std::is_sorted(sorted.begin(),sorted.end()))std::sort(sorted.begin(),sorted.end());
    const double step=p.tau/3,first=sorted.front();
    const double tail=2*std::max(p.tau,filter)*((p.order+1)*std::log(2.)-std::log(1e-14));
    const double cells=std::ceil((sorted.back()-first+tail)/step);
    if(!(cells>0&&cells<=2048))return {};
    auto table=std::make_shared<Table>();
    table->first=first;table->inverseStep=1./step;table->last=first+cells*step;
    analog_pmt::Response shape;shape.order=p.order;shape.tau=p.tau;shape.filterTau=filter;
    auto weights=p.charge.weights(sorted.size(),p.event);
    analog_pmt::Chain chain(sorted.data(),sorted.size(),shape,true,weights.empty()?nullptr:weights.data());
    table->knots.resize(static_cast<size_t>(cells)+8);
    for(size_t i=3;i<table->knots.size();++i)
        table->knots[i]=chain.at(first+(i-3)*step);
    // Fourier inversion bounds the eighth derivative of an order >= 12 Erlang
    // by B(4.5,1.5)/(2*pi*tau^9) = 0.013671875/tau^9. A unit-area low-pass
    // preserves that bound. Eight-node central interpolation at tau/3 therefore
    // contributes <= 2.226e-9/tau per PE. Include knot and sample arithmetic,
    // the coordinate subtraction, and the positive binary64 chain sums.
    const double rounding=512*std::numeric_limits<double>::epsilon()*
        (p.order*(8192.+cells)+p.count+64+(std::abs(first)+std::abs(sorted.back())+tail)/p.tau);
    double total=p.count;
    if(!weights.empty()){total=0;for(double w:weights)total+=w;}
    table->chargeSum=total;
    table->unitError=total/p.tau*(2.23e-9+rounding);
    return table;
}

class Cache {
    struct Shard {
        std::mutex lock;
        std::unordered_map<uint64_t,Entry> tables;
        std::deque<uint64_t> order;
        size_t bytes=0;
    };
    std::array<Shard,32> shards;
    static size_t cost(const Entry& v){return 128+sizeof(Table)+v->knots.size()*sizeof(double);}
public:
    Entry get(uint64_t record,unsigned role,unsigned channel,const adc_waveform::Pulse& pulse,double filter){
        if(pulse.count<16||pulse.order<12)return {};
        const uint64_t key=(record*2+role)*2+channel;
        auto& shard=shards[(key*11400714819323198485ull)>>59];
        {
            std::lock_guard<std::mutex> guard(shard.lock);
            const auto it=shard.tables.find(key);
            if(it!=shard.tables.end())return it->second;
        }
        Entry table;
        try{table=build(pulse,filter);}catch(const std::bad_alloc&){return {};}
        if(!table)return {};
        std::lock_guard<std::mutex> guard(shard.lock);
        const auto existing=shard.tables.find(key);
        if(existing!=shard.tables.end())return existing->second;
        constexpr size_t budget=16*1024*1024;
        while(shard.bytes+cost(table)>budget&&!shard.order.empty()){
            auto it=shard.tables.find(shard.order.front());shard.order.pop_front();
            shard.bytes-=cost(it->second);shard.tables.erase(it);
        }
        try{
            shard.order.push_back(key);
            try{shard.tables.emplace(key,table);}catch(const std::bad_alloc&){shard.order.pop_back();return {};}
        }catch(const std::bad_alloc&){return {};}
        shard.bytes+=cost(table);
        return table;
    }
};
}
