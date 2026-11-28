// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

#include "../native/cathode_film.hpp"
#include <cmath>
#include <cstdio>

int main() {
    // Independent characteristic-matrix results for glass/KCsSb/vacuum at
    // 440 nm and 20 nm thickness, including incidence above the vacuum critical angle.
    struct Case { double degrees; bool p; double reflect, absorb; };
    const Case cases[] = {
        {0,false,.1656106053,.5720175976}, {0,true,.1656106053,.5720175976},
        {35,false,.1968050630,.6489282650}, {35,true,.1320236227,.5027051916},
        {60,false,.2333627907,.7666372093}, {60,true,.1126303246,.8873696754}
    };
    for(const auto& test:cases) {
        const auto actual=filmMode(1.5,{2.7,1.5},std::cos(test.degrees*std::acos(-1.)/180.),20.,440.,test.p);
        if(!(std::abs(std::norm(actual.r)-test.reflect)<1e-9 && std::abs(actual.absorb-test.absorb)<1e-9)){
            std::fprintf(stderr,"Mismatch at %.1f degrees (%s polarization)\n",test.degrees,test.p?"p":"s");
            return 1;
        }
    }
    // With no absorbing layer, the two remaining interfaces reduce to one.
    for(bool p:{false,true}) {
        const auto bare=filmMode(1.5,{2.7,1.5},1.,0.,440.,p);
        if(!(std::abs(std::norm(bare.r)-.04)<1e-12 && bare.absorb<1e-12))return 2;
        const double critical=std::sqrt(1.-std::pow(1.2/1.5,2));
        const auto edge=filmMode(1.5,{1.2,0.},critical,20.,440.,p);
        const auto nearEdge=filmMode(1.5,{1.2,0.},critical+1e-8,20.,440.,p);
        if(!(std::abs(edge.r-nearEdge.r)<1e-6 && edge.absorb<1e-9))return 3;
    }
    return 0;
}
