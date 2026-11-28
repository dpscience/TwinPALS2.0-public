// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

#pragma once
#include <algorithm>
#include <complex>

// A planar absorbing film on a vacuum substrate. Wavelength and thickness in nm.
struct FilmMode {
    std::complex<double> r;
    double absorb;
};
inline FilmMode filmMode(double index, std::complex<double> film, double cosIncident,
                         double thickness, double wavelength, bool pPolarized) {
    using Complex=std::complex<double>;
    const double transverse2=index*index*(1-cosIncident*cosIncident);
    const Complex kz=std::sqrt(film*film-transverse2);
    const Complex vacuum=std::sqrt(Complex(1-transverse2,0));
    const double kz0=index*cosIncident;
    const Complex n2=pPolarized?film*film:Complex(1);
    const double n0=pPolarized?index*index:1.;
    const Complex a=kz0*n2, b=kz*n0, c=kz, d=vacuum*n2;
    if(kz0<=0) return {{-1.,0.},0.};
    constexpr double twoPi=6.2831853071795864769;
    const double scale=twoPi*thickness/wavelength;
    // At the film's critical angle kz can vanish. Use sin(delta)/kz in
    // the transfer matrix so the finite limit does not become zero over zero.
    if(std::abs(kz*scale)<1e-5){
        const Complex delta=kz*scale, cosPhase=std::cos(delta);
        const Complex sinc=Complex(0,scale)*(1.-delta*delta/6.);
        const Complex den=(a+n0*d)*cosPhase-(a*d+kz*kz*n0)*sinc;
        const Complex r=((a-n0*d)*cosPhase+(kz*kz*n0-a*d)*sinc)/den;
        const Complex t=2.*kz0*(pPolarized?index*n2:Complex(1))/den;
        return {r,std::clamp(1.-std::norm(r)-std::norm(t)*vacuum.real()/kz0,0.,1.)};
    }
    const Complex phase=std::exp(Complex(0,scale)*kz);
    const Complex denom=(a+b)*(c+d)+(a-b)*(c-d)*phase*phase;
    if(std::abs(denom)==0) return {{-1.,0.},0.};
    const Complex r=((a-b)*(c+d)+(c-d)*(a+b)*phase*phase)/denom;
    const Complex t=4.*kz0*kz*(pPolarized?index:1.)*(pPolarized?film*film:Complex(1))*phase/denom;
    const double transmission=std::norm(t)*vacuum.real()/kz0;
    return {r,std::clamp(1.-std::norm(r)-transmission,0.,1.)};
}
