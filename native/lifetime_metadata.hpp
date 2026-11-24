// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// Both metadata paths check the paired WAVE timing, pulse values and timeline.
// The canonical reader recognizes the exact schema emitted by native/sweep_library.cpp.
// Other valid layouts, including reordered keys, go through the general JSON decoder.
struct WaveMeta {
    Index id;
    double baseline[2];
    unsigned classification;
    double start,trigger,end,busy,low,high,known;
    Index cell,trigger_channel,total;
    std::size_t history_count;
    double first_history,last_history;
    bool clipped[2];
    std::vector<Pulse> contributors;
    void clear(){
        contributors.clear();history_count=0;first_history=INFINITY;last_history=-INFINITY;
    }
    void history(double onset){
        ++history_count;first_history=std::min(first_history,onset);last_history=std::max(last_history,onset);
    }
    void verify(int samples)const{
        need(start<=trigger && trigger<=end && end<=busy && start<end,"Invalid waveform timing");
        need(cell<Index(samples) && trigger_channel<2,"Invalid trigger channel or cell");
        need(low<=start && busy<=high && end<=known && known<=high && history_count==std::min<Index>(256,total),"Invalid acquisition timeline");
        if(history_count)need(low-1e-6<=start+first_history && start+last_history<=known+1e-6,"Invalid timeline pulse time");
        need(!contributors.empty(),"Missing waveform contributions");
    }
};
unsigned check_class(std::string_view name,std::string_view filter){
    static constexpr std::string_view classes[]={"single","true_A_start","true_B_start","same_primary_1","same_primary_2","mixed_same_decay","accidental","pileup"};
    const auto entry=std::find(std::begin(classes),std::end(classes),name);
    need(entry!=std::end(classes) && (filter=="all"||filter==name),"Invalid pulse class");
    return static_cast<unsigned>(entry-classes);
}
void general_metadata(const unsigned char* p,std::size_t bytes,const char* filter,WaveMeta& w){
    const auto m=Json::parse(p,p+bytes);
    w.classification=check_class(m.at("class").get_ref<const std::string&>(),filter);
    w.id=integer(m.at("id"));w.start=number(m.at("start_ns"));
    w.trigger=number(m.at("trigger_ns"));w.end=number(m.at("end_ns"));w.busy=number(m.at("busy_until_ns"));
    w.cell=integer(m.at("trigger_cell"));w.trigger_channel=integer(m.at("trigger_channel"));
    const auto& base=m.at("baseline_mV");const auto& clip=m.at("clipped");
    need(base.is_array()&&base.size()==2&&clip.is_array()&&clip.size()==2,"Invalid waveform channels");
    for(int ch=0;ch<2;++ch){
        w.baseline[ch]=number(base[ch]);need(clip[ch].is_boolean(),"Invalid clipping flag");w.clipped[ch]=clip[ch].get<bool>();
    }
    const auto& tl=m.at("timeline");w.low=number(tl.at("low_ns"));w.high=number(tl.at("high_ns"));w.known=number(tl.at("known_until_ns"));
    const auto& history=tl.at("pulses");
    need(history.is_array(),"Invalid acquisition timeline");w.total=integer(tl.at("total"));
    for(const auto& item:history)w.history(pulse(item).onset);
    const auto& contributors=m.at("pulses");need(contributors.is_array(),"Missing waveform contributions");
    for(const auto& item:contributors)w.contributors.push_back(pulse(item));
}
struct OtherLayout {};
class WaveCursor {
    const char *pos,*end;
    template<std::size_t N> bool take(const char(&s)[N]){
        if(std::size_t(end-pos)<N-1 || std::memcmp(pos,s,N-1)!=0)return false;
        pos+=N-1;return true;
    }
    template<std::size_t N> void expect(const char(&s)[N]){if(!take(s))throw OtherLayout{};}
    bool boolean(){if(take("true"))return true;expect("false");return false;}
    Index uint_value(){
        Index value=0;const char* start=pos;
        auto r=std::from_chars(pos,end,value);
        if(r.ec!=std::errc()||(*start=='0'&&r.ptr>start+1))throw OtherLayout{};
        pos=r.ptr;return value;
    }
    double numeric(){
        const char* digit=pos+(pos!=end&&*pos=='-'?1:0);
        if(digit==end||*digit<'0'||*digit>'9')throw OtherLayout{};
        double value;auto r=std::from_chars(pos,end,value,std::chars_format::general);
        if(r.ec!=std::errc() || (*digit=='0' && digit+1<r.ptr && digit[1]>='0' && digit[1]<='9')
           || r.ptr[-1]=='.' || !std::isfinite(value))throw OtherLayout{};
        // from_chars also accepts a decimal point followed directly by an exponent.
        if(const char* dot=static_cast<const char*>(std::memchr(pos,'.',r.ptr-pos)); dot && (dot[1]<'0'||dot[1]>'9'))throw OtherLayout{};
        pos=r.ptr;return value;
    }
    // Many observational fields are only checked for a finite value or a positive
    // magnitude. Short decimals with a modest exponent are finite, and a nonzero
    // digit cannot round to zero in this range. Keep full rounding for measured
    // times, extreme exponents and long decimals.
    int numeric_sign(){
        const char* q=pos;
        const bool negative=q!=end && *q=='-';
        if(negative)++q;
        const auto digit=[&](const char* p){return p!=end && *p>='0' && *p<='9';};
        if(!digit(q))throw OtherLayout{};
        int nonzero=0;
        if(*q=='0')++q;
        else do{nonzero|=*q++-'0';}while(digit(q));
        if(q!=end && *q=='.'){
            ++q;if(!digit(q))throw OtherLayout{};
            do{nonzero|=*q++-'0';}while(digit(q));
        }
        const bool short_mantissa=q-pos<=32;
        int exponent=0;
        if(q!=end && (*q=='e'||*q=='E')){
            ++q;if(q!=end && (*q=='-'||*q=='+'))++q;
            if(!digit(q))throw OtherLayout{};
            do{if(exponent<=200)exponent=10*exponent+(*q-'0');++q;}while(digit(q));
        }
        if(short_mantissa && exponent<=200 && q!=end && (*q==','||*q==']'||*q=='}')){
            pos=q;return nonzero?(negative?-1:1):0;
        }
        const double v=numeric();return (v>0)-(v<0);
    }
    void nullable_pair(){
        if(take("null"))return;
        expect("[");if(!take("null"))numeric_sign();expect(",");if(!take("null"))numeric_sign();expect("]");
    }
    std::string_view quoted(){
        expect("\"");const auto* next=static_cast<const char*>(std::memchr(pos,'"',end-pos));
        if(!next)throw OtherLayout{};
        std::string_view value(pos,next-pos);pos=next+1;return value;
    }
    Pulse one_pulse(){
        Pulse z{};
        expect("{\"channel\":");z.ch=uint_value();expect(",\"component\":");uint_value();
        expect(",\"decay\":");z.decay=uint_value();expect(",\"height_mV\":");const int height=numeric_sign();
        expect(",\"lifetime_ns\":");const int life=numeric_sign();expect(",\"light_origin\":");auto light=quoted();
        z.origin=light=="scintillation"?0:light=="cherenkov"?1:light=="mixed"?2:-1;
        if(z.origin<0)throw OtherLayout{};
        expect(",\"onset_ns\":");z.onset=numeric();expect(",\"origin_ns\":");numeric_sign();
        expect(",\"record\":");z.record=uint_value();expect(",\"role\":");z.role=uint_value();
        expect(",\"source_time_ns\":");numeric_sign();expect("}");
        need(z.ch<=1&&z.role<=1&&height>0&&life>=0,"Invalid pulse origin values");
        return z;
    }
public:
    WaveCursor(const unsigned char* p,size_t n):pos(reinterpret_cast<const char*>(p)),end(pos+n){}
    void decode(const char* filter,WaveMeta& w){
        expect("{\"accepted_crossings_ns\":");nullable_pair();
        expect(",\"acquisition_rate_Hz\":");numeric_sign();
        expect(",\"baseline_mV\":[");w.baseline[0]=numeric();expect(",");w.baseline[1]=numeric();expect("],\"busy_until_ns\":");w.busy=numeric();
        expect(",\"class\":");auto name=quoted();
        if(name.find('\\')!=std::string_view::npos)throw OtherLayout{};
        w.classification=check_class(name,filter);
        expect(",\"clipped\":[");w.clipped[0]=boolean();expect(",");w.clipped[1]=boolean();
        expect("],\"coincidence_window_ns\":");nullable_pair();expect(",\"end_ns\":");w.end=numeric();
        expect(",\"flags\":{\"mixed_primaries\":");boolean();expect(",\"multiple_decays\":");boolean();
        expect(",\"pileup_A\":");boolean();expect(",\"pileup_B\":");boolean();expect("},\"id\":");w.id=uint_value();
        expect(",\"pulses\":[");if(!take("]")){do{w.contributors.push_back(one_pulse());}while(take(","));expect("]");}
        expect(",\"start_ns\":");w.start=numeric();expect(",\"timeline\":{\"high_ns\":");w.high=numeric();
        expect(",\"known_until_ns\":");w.known=numeric();expect(",\"low_ns\":");w.low=numeric();
        expect(",\"pulses\":[");if(!take("]")){do{w.history(one_pulse().onset);}while(take(","));expect("]");}
        expect(",\"total\":");w.total=uint_value();expect("},\"trigger_cell\":");w.cell=uint_value();
        expect(",\"trigger_channel\":");w.trigger_channel=uint_value();expect(",\"trigger_ns\":");w.trigger=numeric();expect("}");
        if(pos!=end)throw OtherLayout{};
    }
};
