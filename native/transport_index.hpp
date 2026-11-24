// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Complete CRC/semantic validation and compact M2 indexing, in bounded chunks.
#pragma once
#include "stream_crc.hpp"
#include "vendor/json.hpp"
#include <future>
#include <unordered_map>
#include <cstring>
#include <cmath>
#include <limits>
#include <algorithm>
#include <vector>
#include <stdexcept>
#include <cstdint>

namespace transport_index {
using json=nlohmann::json;
template<class T>T read(const unsigned char* p){T v;std::memcpy(&v,p,sizeof v);return v;}
inline void require(bool test,const char* message){if(!test)throw std::runtime_error(message);}
struct Arrays {
    double *values,*starts,*spans,*peaks,*prefixes;
    uint64_t *index,*provenance;
    uint32_t *flags;
    unsigned char* origins;
};
struct Summary { uint64_t interaction[2]{},response[2]{},origins[8]{},eligible[2]{};double maximum[2]{},eligibleMaximum[2]{}; };
class Reader {
    const unsigned char* mapped;uint64_t limit,position=0,total,row=0;Arrays out;
    const unsigned char* window=nullptr;uint64_t windowOffset=0,windowEnd=0;
    double threshold,tails[2];int mask,components,polarity[2];bool cherenkov;
    struct Bytes {
        const unsigned char* ptr=nullptr;size_t length=0;
        const unsigned char* data()const{return ptr;}
        size_t size()const{return length;}
    };
    Bytes payload,analog;uint32_t counts[2]{};uint64_t analogAt=0,provAt=0,provLength=0;
    bool hasAnalog=false,hasProvenance=false,finished=false;
    std::unordered_map<std::string,std::size_t> dictionaries;
    std::string footer,error;
    Summary summary;
    const unsigned char* address(uint64_t offset,size_t n)const{
        if(window&&offset>=windowOffset&&offset<=windowEnd&&n<=windowEnd-offset)return window+(offset-windowOffset);
        return mapped+offset;
    }
    Bytes take(size_t n){
        require(n<=limit-position,"Truncated stream frame");Bytes result{address(position,n),n};position+=n;return result;
    }
    static json object(const unsigned char* p,std::size_t n){auto value=json::parse(p,p+n);require(value.is_object(),"Stream JSON block must be an object");return value;}
    void analogFrame(){
        require(!hasAnalog&&payload.size()>=16,"Unpaired or incomplete analog pulse frame");
        require(read<uint64_t>(payload.data())==row,"Analog pulse IDs must match event records");
        counts[0]=read<uint32_t>(payload.data()+8);counts[1]=read<uint32_t>(payload.data()+12);
        require(payload.size()==16+34*(uint64_t(counts[0])+counts[1]),"Analog pulse count/length mismatch");
        const uint64_t count=uint64_t(counts[0])+counts[1];
        for(uint64_t i=0;i<count;++i){
            const auto* p=payload.data()+16+32*i;
            for(int k=0;k<4;++k)require(std::isfinite(read<double>(p+8*k)),"Invalid photoelectron arrival/onset time");
            require(read<double>(p)>=-1e-9,"Invalid photoelectron arrival/onset time");
            const auto* tag=payload.data()+16+32*count+2*i;
            require(tag[0]==1||tag[0]==2,"Invalid photon production mechanism");
        }
        analog=payload;analogAt=position-payload.size();hasAnalog=true;
    }
    void provenanceFrame(){
        require(hasAnalog&&!hasProvenance&&payload.size()>=24,"Unpaired or truncated transport ancestry");
        const auto* p=payload.data();const auto n=read<uint32_t>(p+8),a=read<uint32_t>(p+12),b=read<uint32_t>(p+16),j=read<uint32_t>(p+20);
        require(payload.size()==24+uint64_t(j)+uint64_t(n)*128+(uint64_t(a)+b)*4,"Invalid transport ancestry length");
        require(read<uint64_t>(p)==row&&a==counts[0]&&b==counts[1],"Transport ancestry event/count mismatch");
        const std::string encoded(reinterpret_cast<const char*>(p+24),j);std::size_t processCount;
        const auto found=dictionaries.find(encoded);
        if(found!=dictionaries.end())processCount=found->second;
        else{
            const auto names=json::parse(encoded);require(names.is_array(),"Invalid transport processes");
            for(const auto& name:names)require(name.is_string()&&!name.get_ref<const std::string&>().empty(),"Invalid transport processes");
            processCount=names.size();if(j<=4096){if(dictionaries.size()>=256)dictionaries.clear();dictionaries.emplace(encoded,processCount);}
        }
        for(uint32_t i=0;i<n;++i){
            const auto* node=p+24+j+uint64_t(i)*128;uint32_t u[8];double x[12];std::memcpy(u,node,32);std::memcpy(x,node+32,96);
            require(u[0]<i+1&&u[1]&&u[3]<=2&&u[7]<processCount&&x[4]>=0&&x[5]>=0,"Invalid transport tree node");
            for(double v:x)require(std::isfinite(v),"Invalid transport tree node");
            require(u[4]<uint32_t(components)&&u[5]<uint32_t(components),"Transport tree references an unknown component");
        }
        const auto* refs=p+24+j+uint64_t(n)*128;
        for(uint64_t i=0;i<uint64_t(a)+b;++i){const auto ref=read<uint32_t>(refs+i*4);require(ref&&ref<=n,"Photoelectron references an unknown transport node");}
        provAt=position-payload.size();provLength=payload.size();hasProvenance=true;
    }
    void eventFrame(){
        require(payload.size()==324,"EVNT record must contain exactly 324 bytes");
        require(hasAnalog&&hasProvenance,"Event has no analog pulse or transport ancestry");
        require(row<total&&read<uint64_t>(payload.data())==row,"Event IDs/count must match the checked stream");
        const auto primary=read<uint32_t>(payload.data()+8);double x[15];std::memcpy(x,payload.data()+12,120);
        require(primary==uint32_t(mask),"Primary mask disagrees with the stream source role");
        for(double v:x)require(std::isfinite(v),"Nonfinite event kinematics");
        for(int i=0;i<3;++i){
            double norm=0;for(int k=0;k<3;++k)norm+=x[3+3*i+k]*x[3+3*i+k];
            require((primary&(1u<<i))?std::abs(norm-1)<=1e-7:norm==0,"Primary directions must be unit vectors, inactive slots zero");
            require(x[12+i]>=0&&((primary&(1u<<i))||x[12+i]==0),"Invalid primary emission time");
        }
        if(primary==6){for(int k=0;k<3;++k)require(std::abs(x[6+k]+x[9+k])<=1e-7,"Na-22 annihilation-pair directions are inconsistent");require(x[13]==x[14],"Na-22 annihilation-pair times are inconsistent");}
        if(out.prefixes)std::copy(x,x+15,out.prefixes+row*15);
        const uint64_t all=uint64_t(counts[0])+counts[1];uint64_t first=0;
        for(int ch=0;ch<2;++ch){
            const auto* p=payload.data()+132+96*ch;const auto flags=read<uint32_t>(p);const auto hits=read<uint64_t>(p+4);double d[7];std::memcpy(d,p+12,56);
            for(double v:d)require(std::isfinite(v),"Nonfinite DetectorInfo values");
            require(!(flags&~255u)&&bool(flags&48)==bool(hits),"Invalid DetectorInfo flags");
            require(d[0]>=0&&d[1]>=-1e-9&&d[5]>=-1e-9&&d[6]>=0,"Negative detector energy, arrival time or path length");
            require(bool(flags&1)==bool(hits)&&bool(flags&4)==(d[0]>=threshold),"DetectorInfo validity flag disagrees with count/energy");
            require(hits||(d[1]==0&&d[6]==0),"Missing mean/path values must use zero");
            require((flags&2)||!(d[2]||d[3]||d[4]||d[5]),"Missing interaction must use zero coordinates/time");
            require(hits==counts[ch],"Photoelectron count disagrees with DetectorInfo");
            double sum=0,small=INFINITY,large=-INFINITY,maxArrival=0;unsigned origin=0;
            for(uint64_t i=first;i<first+hits;++i){
                const auto* pe=analog.data()+16+i*32;const auto arrival=read<double>(pe),onset=read<double>(pe+8);sum+=arrival;maxArrival=std::max(maxArrival,std::abs(arrival));small=std::min(small,onset);large=std::max(large,onset);
                const auto* tag=analog.data()+16+all*32+i*2;origin|=tag[0];require(tag[1]<components,"Unknown photon birth component");
            }
            if(hits){
                const double mean=sum/hits,tolerance=std::max(1e-9,1e-10*std::max(std::abs(mean),std::abs(d[1]))),difference=std::abs(mean-d[1]);
                // NumPy may group summation differently. Borderline validation
                // is delegated to the original reader rather than relaxed.
                const double roundoff=std::numeric_limits<double>::epsilon()*hits*maxArrival*2;
                require(difference+tolerance==tolerance||difference<tolerance-roundoff,"Photoelectron mean requires reference validation");
            }
            require(origin==((flags>>4)&3),"Photoelectron origin disagrees with DetectorInfo");
            require(cherenkov||!(origin&2),"Cherenkov photons in a stream with Cherenkov disabled");
            const double low=read<double>(p+80),high=read<double>(p+88);
            require(std::isfinite(low)&&std::isfinite(high)&&low<=0&&high>=0&&(hits||(!low&&!high)),"Invalid analog voltage extrema");
            require(polarity[ch]<0?high==0:low==0,"Anode extrema disagree with pulse polarity");
            const auto at=row*2+ch;out.flags[at]=flags|(d[0]>0?256u:0u);out.origins[at]=static_cast<unsigned char>(origin);
            out.values[row*4+ch*2]=(flags&4)?static_cast<double>(hits):0.;out.values[row*4+ch*2+1]=(flags&4)?d[1]:0.;
            out.starts[at]=(flags&4)&&hits?small:0.;out.spans[at]=(flags&4)&&hits?large-small+tails[ch]:0.;out.peaks[at]=(flags&4)?std::max(-low,high):0.;
            summary.interaction[ch]+=bool(flags&2)||d[0]>0;summary.response[ch]+=hits>0;summary.origins[ch*4+origin]++;summary.eligible[ch]+=hits>0&&bool(flags&4);
            summary.maximum[ch]=std::max(summary.maximum[ch],std::max(-low,high));if(flags&4)summary.eligibleMaximum[ch]=std::max(summary.eligibleMaximum[ch],std::max(-low,high));
            first+=hits;
        }
        out.index[row*3]=analogAt;out.index[row*3+1]=counts[0];out.index[row*3+2]=counts[1];out.provenance[row*2]=provAt;out.provenance[row*2+1]=provLength;
        hasAnalog=hasProvenance=false;++row;
    }
public:
    Reader(const unsigned char* data,uint64_t size,const char* configuration,const Arrays& arrays):mapped(data),limit(size),out(arrays){
        const auto cfg=json::parse(configuration);const auto& header=cfg.at("header");total=cfg.at("count");
        threshold=header.at("physics").at("minimum_energy_keV");cherenkov=header.at("physics").at("include_cherenkov");components=static_cast<int>(header.at("light_components").size());
        const std::string role=header.at("role");mask=role=="na22_prompt"?1:role=="na22_annihilation"?6:3;
        for(int i=0;i<2;++i){tails[i]=cfg.at("tails").at(i);polarity[i]=header.at("analog_response").at(i).at("polarity")=="negative"?-1:1;}
        const auto* prefix=take(12).data();require(std::memcmp(prefix,"TPSTRM06",8)==0,"Unsupported transport stream");
        const auto n=read<uint32_t>(prefix+8);require(n<=64*1024*1024,"Transport header exceeds limit");payload=take(n);
        require(object(payload.data(),n)==header,"Input stream header changed after setup validation");
    }
    int next(uint64_t records){
        try{
            const auto until=std::min(total,row+records);
            while(!finished&&(row<until||row==total)){
                require(position<limit,"Incomplete transport stream");const auto* prefix=take(12).data();
                const auto n=read<uint32_t>(prefix+4),crc=read<uint32_t>(prefix+8);require(n<=16*1024*1024,"Frame exceeds the 16 MiB format limit");
                payload=take(n);require(stream_crc::calculate(payload.data(),payload.size())==crc,"CRC mismatch in transport stream");
                if(std::memcmp(prefix,"APLS",4)==0)analogFrame();
                else if(std::memcmp(prefix,"PROV",4)==0)provenanceFrame();
                else if(std::memcmp(prefix,"EVNT",4)==0)eventFrame();
                else if(std::memcmp(prefix,"TRAK",4)==0)object(payload.data(),payload.size());
                else if(std::memcmp(prefix,"DONE",4)==0){
                    require(!hasAnalog&&!hasProvenance&&row==total,"Unpaired records at transport completion");
                    const auto done=object(payload.data(),payload.size());require(done.at("status")=="completed"&&done.at("events").is_number_integer()&&done.at("events")==row,"Invalid transport completion count/status");
                    require(position==limit,"Unexpected bytes after DONE footer");footer=done.dump();finished=true;
                }else throw std::runtime_error("Unknown stream frame tag");
            }
            return finished?1:0;
        }catch(const std::exception& e){error=e.what();return -1;}
    }
    // Only split immediately after a complete EVNT. Every worker still reads
    // and validates every frame in its byte range, including optional TRAKs.
    int nextWindow(const unsigned char* buffer,uint64_t offset0,uint64_t size,unsigned workers){
        try{
            require(offset0<=position&&position<=offset0+size&&size<=limit-offset0,"Unexpected input buffer position");
            window=buffer;windowOffset=offset0;windowEnd=offset0+size;
            if(row==total)return next(1);
            struct Chunk {uint64_t offset,first,length,end;};
            std::vector<Chunk> chunks;
            auto offset=position, first=row;
            for(unsigned w=0;w<workers&&first<total;++w){
                const auto start=offset, boundary=windowOffset+size*(w+1)/workers;
                uint64_t length=0;
                do{
                    require(limit-offset>=12,"Incomplete transport frame header");
                    const auto* prefix=address(offset,12);const auto bytes=read<uint32_t>(prefix+4);
                    require(bytes<=16*1024*1024&&bytes<=limit-offset-12,"Invalid transport frame length");
                    offset+=12+bytes;
                    if(!std::memcmp(prefix,"EVNT",4)){
                        ++length;
                        if(offset>=boundary||first+length==total)break;
                    }
                }while(true);
                chunks.push_back({start,first,length,first+length==total?limit:offset});first+=length;
                if(offset>=windowEnd)break;
            }
            struct Result {Summary stats;bool finished;std::string footer;};
            auto validate=[this](Chunk chunk){
                Reader child=*this;child.summary={};child.position=chunk.offset;child.row=chunk.first;
                const int code=child.next(chunk.length);
                if(code<0)throw std::runtime_error(child.failure());
                require(child.position==chunk.end&&child.row==chunk.first+chunk.length&&!child.hasAnalog&&!child.hasProvenance,"Unpaired transport frames");
                return Result{child.summary,child.finished,std::move(child.footer)};
            };
            std::vector<std::future<Result>> futures;
            for(size_t i=1;i<chunks.size();++i)futures.push_back(std::async(std::launch::async,validate,chunks[i]));
            std::vector<Result> results{validate(chunks.front())};
            for(auto& task:futures)results.push_back(task.get());
            for(const auto& result:results){
                const auto& s=result.stats;
                for(int ch=0;ch<2;++ch){
                    summary.interaction[ch]+=s.interaction[ch];summary.response[ch]+=s.response[ch];summary.eligible[ch]+=s.eligible[ch];
                    summary.maximum[ch]=std::max(summary.maximum[ch],s.maximum[ch]);summary.eligibleMaximum[ch]=std::max(summary.eligibleMaximum[ch],s.eligibleMaximum[ch]);
                }
                for(int i=0;i<8;++i)summary.origins[i]+=s.origins[i];
                if(result.finished){finished=true;footer=result.footer;}
            }
            row=first;position=chunks.back().end;return finished?1:0;
        }catch(const std::exception& e){error=e.what();return -1;}
    }
    uint64_t completed()const{return row;}
    bool packOnsets(uint64_t first,double* packed,uint64_t capacity)const{
        uint64_t written=0;
        for(auto i=first;i<row;++i){
            const auto* index=out.index+3*i;
            const uint64_t hits=index[1]+index[2];
            if(hits>capacity-written)return false;
            if(!hits)continue;
            const auto* analogData=address(index[0],static_cast<size_t>(16+34*hits));
            const auto begin=written;
            for(uint64_t j=0;j<hits;++j)packed[written++]=read<double>(analogData+24+32*j);
            std::sort(packed+begin,packed+begin+index[1]);
            std::sort(packed+begin+index[1],packed+written);
        }
        return written==capacity;
    }
    uint64_t bytePosition()const{return position;}
    const char* completion()const{return footer.c_str();}
    const char* failure()const{return error.c_str();}
    Summary counters()const{return summary;}
};
}
