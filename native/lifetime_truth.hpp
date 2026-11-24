// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Validate a TRTH frame and reduce its ordered ancestry to the information needed by CF attribution.
// The original frame address remains available for the full waveform transport diagram.
struct TruthConfig {
    const unsigned char* component_flags[2];
    std::uint32_t components[2];
    double tails[2];
};
struct TransportRef {
    std::uint64_t record;
    std::uint32_t role, length, crc;
    std::uint32_t reserved;
};
const std::vector<unsigned char>& scattering_processes(const unsigned char* dict,std::uint32_t length){
    thread_local std::unordered_map<std::string,std::vector<unsigned char>> cache;
    thread_local std::vector<unsigned char> large;
    std::string key(reinterpret_cast<const char*>(dict),length);
    if(length<=4096){
        const auto found=cache.find(key);
        if(found!=cache.end())return found->second;
    }
    auto names=Json::parse(dict,dict+length);
    need(names.is_array(),"Invalid transport processes");
    std::vector<unsigned char> result;
    result.reserve(names.size());
    for(const auto& entry:names){
        need(entry.is_string(),"Invalid transport processes");
        auto name=entry.get<std::string>();
        need(!name.empty(),"Invalid transport processes");
        for(char& c:name)if(c>='A'&&c<='Z')c+=char('a'-'A');
        result.push_back(name=="compt"||name=="compton"||name=="rayl"||name=="rayleigh");
    }
    if(length>4096){large=std::move(result);return large;}
    if(cache.size()>=256)cache.clear();
    return cache.emplace(std::move(key),std::move(result)).first->second;
}

Support decode_truth(const unsigned char* frame,std::size_t bytes,Index offset,const TruthConfig& cfg){
    need(bytes>=12 && std::memcmp(frame,"TRTH",4)==0,"Invalid transport truth frame");
    const auto size=read<std::uint32_t>(frame+4),crc=read<std::uint32_t>(frame+8);
    need(size>=32 && size<=32*1024*1024 && size<=bytes-12,"Invalid transport frame length");
    const auto* p=frame+12;
    need(stream_crc::calculate(p,size)==crc,"Pulse frame CRC mismatch");
    const auto role=read<std::uint32_t>(p),analog_bytes=read<std::uint32_t>(p+12);
    const Index record=read<Index>(p+4);
    need(role<2 && analog_bytes>=16 && analog_bytes<=size-16,"Invalid contribution truth reference");
    const auto* analog=p+16;
    const auto a=read<std::uint32_t>(analog+8),b=read<std::uint32_t>(analog+12);
    const Index pe_count=Index(a)+b;
    need(read<Index>(analog)==record && 16+34*pe_count==analog_bytes,"Analog pulse count or ID mismatch");
    const auto* tree=analog+analog_bytes;
    const auto tree_bytes=size-16-analog_bytes;
    need(tree_bytes>=24,"Truncated transport ancestry");
    const auto n=read<std::uint32_t>(tree+8),j=read<std::uint32_t>(tree+20);
    need(read<Index>(tree)==record && read<std::uint32_t>(tree+12)==a && read<std::uint32_t>(tree+16)==b,"Transport ancestry event/count mismatch");
    need(24+Index(j)+Index(n)*128+pe_count*4==tree_bytes,"Invalid transport ancestry length");
    const auto& scatter=scattering_processes(tree+24,j);
    const auto* nodes=tree+24+j;
    const auto* refs=nodes+Index(n)*128;
    const auto* tags=analog+16+32*pe_count;
    // Each parent precedes its children. Inherit the path flags once per node,
    // independent of the number of photoelectrons sharing that path.
    thread_local std::vector<std::uint16_t> paths;
    paths.resize(n+1);paths[0]=0;
    for(unsigned i=0;i<n;++i){
        const auto* node=nodes+Index(i)*128;
        std::uint32_t u[8];double x[12];std::memcpy(u,node,32);std::memcpy(x,node+32,96);
        need(u[0]<=i&&u[1]&&u[3]<=2&&u[7]<scatter.size()&&x[4]>=0&&x[5]>=0,"Invalid transport tree node");
        need(u[4]<cfg.components[role]&&u[5]<cfg.components[role],"Transport tree references an unknown component");
        for(double v:x)need(std::isfinite(v),"Invalid transport tree node");
        auto flags=paths[u[0]];
        const unsigned component=cfg.component_flags[role][u[4]];
        const bool scattered=u[6]==22 && scatter[u[7]];
        if(scattered){
            flags|=1|component;
            if(u[2]==0 && component!=8 && component!=16)flags|=512;
        }
        if(u[6]==22 && u[2]==0 && (scattered || x[4]>x[5]) && !(flags&(1024|2048|4096)))
            flags|=component==8?1024:component==16?2048:4096;
        if(u[6]==22 && u[2]==0 && (component==8 || component==16)){
            if(scattered || x[4]>x[5]) flags|=component==8?128:256;
            if(scattered && x[5]>0 && x[6]*x[9]+x[7]*x[10]+x[8]*x[11]<0)
                flags|=component==8?32:64;
        }
        paths[i+1]=flags;
    }
    Support support{};support.role=role;support.record=record;support.offset=offset;
    for(int ch=0;ch<2;++ch){
        const Index first=ch?a:0,last=ch?pe_count:a;
        double lo=INFINITY,hi=-INFINITY;
        int ids=0,flags=0;
        for(Index i=first;i<last;++i){
            double values[4];std::memcpy(values,analog+16+i*32,32);
            for(double v:values)need(std::isfinite(v),"Invalid photoelectron arrival/onset time");
            need(values[0]>=-1e-9,"Invalid photoelectron arrival/onset time");
            need(tags[2*i]==1 || tags[2*i]==2,"Invalid photon production mechanism");
            const auto head=read<std::uint32_t>(refs+4*i);
            need(head && head<=n,"Photoelectron references an unknown transport node");
            const unsigned primary=1u<<read<std::uint32_t>(nodes+(Index(head)-1)*128+12);
            const auto ancestry=paths[head];
            ids|=primary;flags|=ancestry;
            if(ancestry&(ch?256:128))support.local[ch]|=primary;
            if(ancestry&(ch?2048:1024))support.direct[ch]|=primary;
            if(ancestry&(ch?32:64))support.backward[ch]|=primary;
            lo=std::min(lo,values[1]);hi=std::max(hi,values[1]);
        }
        support.primary_mask[ch]=ids;support.external[ch]=(flags&512)!=0;
        support.scatter[ch]=(flags&7)|((flags&(ch?8:16))?8:0);
        support.span[ch]=(first==last?0.:hi-lo)+cfg.tails[ch];
    }
    support.length=size;support.crc=crc;
    return support;
}
