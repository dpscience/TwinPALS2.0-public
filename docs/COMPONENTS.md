# Factory component catalogue

Choose a record in the TwinPALS **Database** tab to inspect the properties behind a detector setup. The tables below show the factory values most relevant when comparing components. Open the corresponding record for its full composition, curves, units, operating conditions and source references. A saved run records the configuration used for that measurement.

[Return to the TwinPALS guide](../README.md#component-catalogue) · [Factory data and sources](../seed/README.md)

| If you are choosing… | Compare |
| --- | --- |
| A crystal, coupling layer or reflector | [Scintillators](#scintillators), [optical coupling](#optical-coupling) and [reflector wrappings](#reflector-wrappings) |
| A readout chain | [Photomultiplier tubes](#photomultiplier-tubes) and [digitizer presets](#digitizer-presets) |
| A sample, source sandwich or shield | [Sample materials](#sample-materials), [encapsulation foils](#encapsulation-foils) and [shielding materials](#shielding-materials) |

**Reading the values.** Scintillator decay constants refer to light emission. Sample and foil lifetimes refer to positron annihilation. PMT transit-time spread is reported in the convention of each record (FWHM or σ). The optical tables include measured curves, nominal constants and documented model assumptions. The provenance in the application identifies which applies.

<!-- factory-catalogue:start -->
## Scintillators

| Entry | Light yield (photons/MeV) | Decay constants (ns) | Optical curves |
| --- | --- | --- | --- |
| BaF₂ | 11500 | 0.6, 620 | emission fast, emission slow, refractive index, absorption length |
| BC-418 | 10200 | 1.4 | emission, refractive index |
| BC-422Q 0.5% | 2900 | 0.7 | emission, refractive index, absorption length |
| BC-422Q 1% | 1700 | 0.7 | emission, refractive index, absorption length |
| BC-422Q 2% | 770 | 0.7 | emission, refractive index, absorption length |
| BC-422Q 3% | 610 | 0.7 | emission, refractive index, absorption length |
| BC-422Q 5% | 460 | 0.7 | emission, refractive index, absorption length |
| CeBr₃ | 60000 | 19 | emission, refractive index |
| EJ-232 | 8400 | 1.6 | emission, refractive index, absorption length |
| EJ-232Q 0.5% | 2900 | 0.7 | emission, refractive index, absorption length |
| EJ-232Q 1% | 1700 | 0.7 | emission, refractive index, absorption length |
| EJ-232Q 2% | 770 | 0.7 | emission, refractive index, absorption length |
| EJ-232Q 3% | 610 | 0.7 | emission, refractive index, absorption length |
| EJ-232Q 5% | 460 | 0.7 | emission, refractive index, absorption length |
| LYSO:Ce | 33200 | 36 | emission, refractive index, absorption length |

## Optical coupling

| Entry | Density (g/cm³) | Refractive index | Optical curves |
| --- | --- | --- | --- |
| Air | 0.00120479 | 1.00027 | refractive index, absorption length |
| EJ-550 silicone grease | 1.06 | 1.46 | refractive index, absorption length |

## Photomultiplier tubes

| Entry | Rise (ns) | Transit (ns) | Transit-time spread (ns, convention) |
| --- | --- | --- | --- |
| ET Enterprises 9214B | 3 | 45 | 2.2 (FWHM) |
| Hamamatsu R11265U-100 | 1.3 | 5.8 | 0.27 (FWHM) |
| Hamamatsu R11265U-20 | 1.3 | 5.8 | 0.27 (FWHM) |
| Hamamatsu R11265U-200 | 1.3 | 5.8 | 0.27 (FWHM) |
| Hamamatsu R11265U-300 | 1.3 | 5.8 | 0.27 (FWHM) |
| Hamamatsu R1450 | 1.8 | 19 | 0.76 (FWHM) |
| Hamamatsu R1828-01 | 1.3 | 28 | 0.55 (FWHM) |
| Hamamatsu R2059 | 1.3 | 28 | 0.55 (FWHM) |
| Hamamatsu R2083 | 0.8 | 16 | 0.37 (FWHM) |
| Hamamatsu R329-02 | 2.6 | 48 | 1.1 (FWHM) |
| Hamamatsu R3377 | 0.8 | 16 | 0.37 (FWHM) |
| Hamamatsu R5320 | 0.7 | 10 | 0.16 (FWHM) |
| Hamamatsu R7400U-06 | 0.78 | 5.4 | 0.28 (FWHM) |
| Hamamatsu R9800 | 1 | 11 | 0.27 (FWHM) |
| Photonis XP2020 | 1.5 | 30 | 0.25 (σ) |
| Photonis XP2020Q | 1.5 | 30 | 0.25 (σ) |

## Digitizer presets

| Entry | Sampling (GS/s) | ADC (bits) | Range (mV) | Samples |
| --- | --- | --- | --- | --- |
| Acqiris DP240-002 · 0.5 GS/s · ±100 mV | 0.5 | 8 | -100 to 100 | 1024 |
| Acqiris DP240-002 · 0.5 GS/s · ±1000 mV | 0.5 | 8 | -1000 to 1000 | 1024 |
| Acqiris DP240-002 · 0.5 GS/s · ±25 mV | 0.5 | 8 | -25 to 25 | 1024 |
| Acqiris DP240-002 · 0.5 GS/s · ±250 mV | 0.5 | 8 | -250 to 250 | 1024 |
| Acqiris DP240-002 · 0.5 GS/s · ±2500 mV | 0.5 | 8 | -2500 to 2500 | 1024 |
| Acqiris DP240-002 · 0.5 GS/s · ±50 mV | 0.5 | 8 | -50 to 50 | 1024 |
| Acqiris DP240-002 · 0.5 GS/s · ±500 mV | 0.5 | 8 | -500 to 500 | 1024 |
| Acqiris DP240-003 · 1 GS/s · ±100 mV | 1 | 8 | -100 to 100 | 1024 |
| Acqiris DP240-003 · 1 GS/s · ±1000 mV | 1 | 8 | -1000 to 1000 | 1024 |
| Acqiris DP240-003 · 1 GS/s · ±25 mV | 1 | 8 | -25 to 25 | 1024 |
| Acqiris DP240-003 · 1 GS/s · ±250 mV | 1 | 8 | -250 to 250 | 1024 |
| Acqiris DP240-003 · 1 GS/s · ±2500 mV | 1 | 8 | -2500 to 2500 | 1024 |
| Acqiris DP240-003 · 1 GS/s · ±50 mV | 1 | 8 | -50 to 50 | 1024 |
| Acqiris DP240-003 · 1 GS/s · ±500 mV | 1 | 8 | -500 to 500 | 1024 |
| Acqiris SA220P · 1 GS/s · ±1250 mV | 1 | 14 | -1250 to 1250 | 1024 |
| Acqiris SA220P · 1 GS/s · ±250 mV | 1 | 14 | -250 to 250 | 1024 |
| Acqiris SA220P · 2 GS/s · ±1250 mV | 2 | 14 | -1250 to 1250 | 1024 |
| Acqiris SA220P · 2 GS/s · ±250 mV | 2 | 14 | -250 to 250 | 1024 |
| LeCroy WavePro 960 · 8 GS/s · ±500 mV | 8 | 8 | -500 to 500 | 1600 |
| PSI DRS4 V5 · 1.00721 GS/s | 1.00721 | 14 | -500 to 500 | 1024 |
| PSI DRS4 V5 · 1.98194 GS/s | 1.98194 | 14 | -500 to 500 | 1024 |
| PSI DRS4 V5 · 5.12 GS/s | 5.12 | 14 | -500 to 500 | 1024 |
| Teledyne LeCroy WavePro 254HD · 20 GS/s · ±200 mV | 20 | 12 | -200 to 200 | 4000 |
| Teledyne LeCroy WavePro 254HD · 20 GS/s · ±400 mV | 20 | 12 | -400 to 400 | 4000 |
| Teledyne LeCroy WavePro 404HD · 20 GS/s · ±200 mV | 20 | 12 | -200 to 200 | 4000 |
| Teledyne LeCroy WavePro 404HD · 20 GS/s · ±400 mV | 20 | 12 | -400 to 400 | 4000 |
| Teledyne LeCroy WavePro 604HD · 20 GS/s · ±200 mV | 20 | 12 | -200 to 200 | 4000 |
| Teledyne LeCroy WavePro 604HD · 20 GS/s · ±400 mV | 20 | 12 | -400 to 400 | 4000 |
| Teledyne LeCroy WavePro 804HD · 20 GS/s · ±200 mV | 20 | 12 | -200 to 200 | 4000 |
| Teledyne LeCroy WavePro 804HD · 20 GS/s · ±400 mV | 20 | 12 | -400 to 400 | 4000 |
| Teledyne LeCroy WaveRunner 9254 · 20 GS/s · ±200 mV | 20 | 8 | -200 to 200 | 4000 |
| Teledyne LeCroy WaveRunner 9254 · 20 GS/s · ±400 mV | 20 | 8 | -400 to 400 | 4000 |
| Teledyne LeCroy WaveRunner 9254M · 40 GS/s · ±200 mV | 40 | 8 | -200 to 200 | 8000 |
| Teledyne LeCroy WaveRunner 9254M · 40 GS/s · ±400 mV | 40 | 8 | -400 to 400 | 8000 |
| Teledyne LeCroy WaveRunner 9404 · 20 GS/s · ±200 mV | 20 | 8 | -200 to 200 | 4000 |
| Teledyne LeCroy WaveRunner 9404 · 20 GS/s · ±400 mV | 20 | 8 | -400 to 400 | 4000 |
| Teledyne LeCroy WaveRunner 9404M · 40 GS/s · ±200 mV | 40 | 8 | -200 to 200 | 8000 |
| Teledyne LeCroy WaveRunner 9404M · 40 GS/s · ±400 mV | 40 | 8 | -400 to 400 | 8000 |
| Teledyne SP Devices ADQ14DC-2A · 0.5 GS/s · ±250 mV | 0.5 | 14 | -250 to 250 | 1024 |
| Teledyne SP Devices ADQ14DC-2C · 1 GS/s · ±250 mV | 1 | 14 | -250 to 250 | 1024 |
| Teledyne SP Devices ADQ14DC-2X · 2 GS/s · ±500 mV | 2 | 14 | -500 to 500 | 1024 |

## Reflector wrappings

| Entry | Model | Geant4 finish | Reflectance input |
| --- | --- | --- | --- |
| PTFE powder — reflectance model | UNIFIED | ground | reflectivity |
| PTFE — measured LUT | LUT | polishedteflonair | Geant4 surface lookup table |

## Sample materials

87 of 309 entries include lifetime references. A dash marks a material with composition and density only. Multiple values may describe different methods or sample conditions. See the record before selecting a value.

| Entry | Elements | Density (g/cm³) | Lifetime references (ps) |
| --- | --- | --- | --- |
| 1,2-Dichlorobenzene | C, Cl, H | 1.3048 | — |
| 1,2-Dichloroethane | C, Cl, H | 1.2351 | — |
| A-150 Tissue | C, Ca, F, H, N, O | 1.127 | — |
| Ac | Ac | 10.07 | 195 (calculated), 192 (calculated) |
| Acetone | C, H, O | 0.7899 | — |
| Acetylene | C, H | 0.0010967 | — |
| Adenine | C, H, N | 1.35 | — |
| Adipose Tissue Icrp | C, Cl, H, N, Na, O, S | 0.95 | — |
| Air | Ar, C, N, O | 0.00120479 | — |
| Alanine | C, H, N, O | 1.42 | — |
| Aluminium | Al | 2.699 | 165 (calculated), 153 (calculated) |
| Aluminum Oxide | Al, O | 3.97 | — |
| Am | Am | 13.67 | 164 (calculated), 171 (calculated) |
| Amber | C, H, O | 1.1 | — |
| Ammonia | H, N | 0.000826019 | — |
| Aniline | C, H, N | 1.0235 | — |
| Anthracene | C, H | 1.283 | — |
| Ar | Ar | 0.00166201 | 268 (calculated), 435 (calculated) |
| As | As | 5.73 | 181 (calculated), 188 (calculated) |
| At | At | 9.32 | — |
| B | B | 2.37 | — |
| B-100 Bone | C, Ca, F, H, N, O | 1.45 | — |
| Ba | Ba | 3.5 | 307 (calculated), 304 (calculated) |
| Bakelite | C, H, O | 1.25 | — |
| Barium Fluoride | Ba, F | 4.89 | — |
| Barium Sulfate | Ba, O, S | 4.5 | — |
| Benzene | C, H | 0.87865 | — |
| Beryllium | Be | 1.848 | 137 (calculated), 128 (calculated) |
| Beryllium Oxide | Be, O | 3.01 | — |
| Bgo | Bi, Ge, O | 7.13 | — |
| Bismuth | Bi | 9.747 | 224 (calculated), 233 (calculated) |
| Bk | Bk | 14 | 181 (calculated), 193 (calculated) |
| Blood Icrp | C, Cl, Fe, H, K, N, Na, O, P, S | 1.06 | — |
| Bone Compact Icru | C, Ca, H, Mg, N, O, P, S | 1.85 | — |
| Bone Cortical Icrp | C, Ca, H, Mg, N, Na, O, P, S | 1.92 | — |
| Boron Carbide | B, C | 2.52 | — |
| Boron Oxide | B, O | 1.812 | — |
| Br | Br | 0.0070721 | 248 (calculated), 270 (calculated) |
| Brain Icrp | C, Cl, H, K, N, Na, O, P, S | 1.04 | — |
| Brass | Cu, Pb, Zn | 8.52 | — |
| Bronze | Cu, Pb, Zn | 8.82 | — |
| Butane | C, H | 0.00249343 | — |
| C | C | 2 | 99 (calculated), 97 (calculated) |
| C-552 | C, F, H, O, Si | 1.76 | — |
| Ca | Ca | 1.55 | 290 (calculated), 279 (calculated) |
| Cadmium | Cd | 8.65 | 154 (calculated), 167 (calculated) |
| Cadmium Telluride | Cd, Te | 6.2 | — |
| Cadmium Tungstate | Cd, O, W | 7.9 | — |
| Calcium Carbonate | C, Ca, O | 2.8 | — |
| Calcium Fluoride | Ca, F | 3.18 | — |
| Calcium Oxide | Ca, O | 3.3 | — |
| Calcium Sulfate | Ca, O, S | 2.96 | — |
| Calcium Tungstate | Ca, O, W | 6.062 | — |
| Carbon Dioxide | C, O | 0.00184212 | — |
| Carbon Tetrachloride | C, Cl | 1.594 | — |
| Ce | Ce | 6.657 | 197 (calculated), 196 (calculated) |
| Cellulose Butyrate | C, H, O | 1.2 | — |
| Cellulose Cellophane | C, H, O | 1.42 | — |
| Cellulose Nitrate | C, H, N, O | 1.49 | — |
| Ceric Sulfate | Ce, H, N, O, S | 1.03 | — |
| Cesium Fluoride | Cs, F | 4.115 | — |
| Cesium Iodide | Cs, I | 4.51 | — |
| Cf | Cf | 10 | — |
| Chlorobenzene | C, Cl, H | 1.1058 | — |
| Chloroform | C, Cl, H | 1.4832 | — |
| Chromium | Cr | 7.18 | 99 (calculated), 105 (calculated) |
| Cl | Cl | 0.00299473 | 250 (calculated), 275 (calculated) |
| Cm | Cm | 13.51 | 171 (calculated), 180 (calculated) |
| Cobalt | Co | 8.9 | 96 (calculated), 107 (calculated) |
| Concrete | Al, C, Ca, Fe, H, K, Mg, Na, O, Si | 2.3 | — |
| Copper | Cu | 8.96 | 105 (calculated), 118 (calculated) |
| Cr39 | C, H, O | 1.32 | — |
| Cs | Cs | 1.873 | 387 (calculated), 426 (calculated) |
| Cyclohexane | C, H | 0.779 | — |
| Cytosine | C, H, N, O | 1.3 | — |
| Dacron | C, H, O | 1.4 | — |
| Deoxyribose | C, H, O | 1.5 | — |
| Dichlorodiethyl Ether | C, Cl, H, O | 1.2199 | — |
| Diethyl Ether | C, H, O | 0.71378 | — |
| Dimethyl Sulfoxide | C, H, O, S | 1.1014 | — |
| Dna Adenine | C, H, N | 1 | — |
| Dna Cytosine | C, H, N, O | 1 | — |
| Dna Deoxyribose | C, H, O | 1 | — |
| Dna Guanine | C, H, N, O | 1 | — |
| Dna Phosphate | O, P | 1 | — |
| Dna Thymine | C, H, N, O | 1 | — |
| Dna Uracil | C, H, N, O | 1 | — |
| Dy | Dy | 8.55 | 200 (calculated), 205 (calculated) |
| Er | Er | 9.066 | 199 (calculated), 205 (calculated) |
| Ethane | C, H | 0.00125324 | — |
| Ethyl Alcohol | C, H, O | 0.7893 | — |
| Ethyl Cellulose | C, H, O | 1.13 | — |
| Ethylene | C, H | 0.00117497 | — |
| Eu | Eu | 5.243 | 271 (calculated), 266 (calculated) |
| Eye Lens Icrp | C, Cl, H, N, Na, O, P, S | 1.07 | — |
| F | F | 0.00158029 | — |
| Ferric Oxide | Fe, O | 5.2 | — |
| Ferroboride | B, Fe | 7.15 | — |
| Ferrous Oxide | Fe, O | 5.7 | — |
| Ferrous Sulfate | Cl, Fe, H, N, Na, O, S | 1.024 | — |
| Fr | Fr | 1 | — |
| Freon-12 | C, Cl, F | 1.12 | — |
| Freon-12B2 | Br, C, F | 1.8 | — |
| Freon-13 | C, Cl, F | 0.95 | — |
| Freon-13B1 | Br, C, F | 1.5 | — |
| Freon-13I1 | C, F, I | 1.8 | — |
| Gadolinium Oxysulfide | Gd, O, S | 7.44 | — |
| Galactic | H | 1e-25 | — |
| Gallium | Ga | 5.904 | 165 (calculated), 167 (calculated) |
| Gallium Arsenide | As, Ga | 5.31 | — |
| Gd | Gd | 7.9004 | 205 (calculated), 209 (calculated) |
| Ge | Ge | 5.323 | 223 (calculated), 228 (calculated) |
| Gel Photo Emulsion | C, H, N, O, S | 1.2914 | — |
| Glass Lead | As, O, Pb, Si, Ti | 6.22 | — |
| Glass Plate | Ca, Na, O, Si | 2.4 | — |
| Glutamine | C, H, N, O | 1.46 | — |
| Glycerol | C, H, O | 1.2613 | — |
| Gold | Au | 19.32 | 108 (calculated), 119 (calculated) |
| Graphite | C | 2.21 | — |
| Graphite Porous | C | 1.7 | — |
| Guanine | C, H, N, O | 1.58 | — |
| Gypsum | Ca, H, O, S | 2.32 | — |
| H | H | 8.3748e-05 | — |
| Hafnium | Hf | 13.31 | 146 (calculated), 146 (calculated) |
| He | He | 0.000166322 | — |
| Hg | Hg | 13.546 | 146 (calculated), 161 (calculated) |
| Ho | Ho | 8.795 | 200 (calculated), 206 (calculated) |
| I | I | 4.93 | 260 (calculated), 268 (calculated) |
| Indium | In | 7.31 | 181 (calculated), 190 (calculated) |
| Ir | Ir | 22.42 | 86 (calculated), 92 (calculated) |
| Iron | Fe | 7.874 | 101 (calculated), 110 (calculated) |
| K | K | 0.862 | 368 (calculated), 391 (calculated) |
| Kapton | C, H, N, O | 1.42 | — |
| Kevlar | C, H, N, O | 1.44 | — |
| Kr | Kr | 0.00347832 | 289 (calculated), 448 (calculated) |
| La | La | 6.154 | 208 (calculated), 207 (calculated) |
| Lanthanum Oxybromide | Br, La, O | 6.28 | — |
| Lanthanum Oxysulfide | La, O, S | 5.86 | — |
| Lar | Ar | 1.396 | — |
| Lbr | Br | 3.1028 | — |
| Lead | Pb | 11.35 | 188 (calculated), 197 (calculated) |
| Lead Oxide | O, Pb | 9.53 | — |
| Lh2 | H | 0.0708 | — |
| Li | Li | 0.534 | 301 (calculated), 281 (calculated) |
| Lithium Amide | H, Li, N | 1.178 | — |
| Lithium Carbonate | C, Li, O | 2.11 | — |
| Lithium Fluoride | F, Li | 2.635 | — |
| Lithium Hydride | H, Li | 0.82 | — |
| Lithium Iodide | I, Li | 3.494 | — |
| Lithium Oxide | Li, O | 2.013 | — |
| Lithium Tetraborate | B, Li, O | 2.44 | — |
| Lkr | Kr | 2.418 | — |
| Ln2 | N | 0.807 | — |
| Lo2 | O | 1.141 | — |
| Lpropane | C, H | 0.43 | — |
| Lu | Lu | 9.84 | 193 (calculated), 192 (calculated) |
| Lucite | C, H, O | 1.19 | — |
| Lung Icrp | C, Cl, H, K, N, Na, O, P, S | 1.04 | — |
| Lxe | Xe | 2.953 | — |
| M3 Wax | C, Ca, H, Mg, O | 1.05 | — |
| Magnesium | Mg | 1.74 | 232 (calculated), 216 (calculated) |
| Magnesium Carbonate | C, Mg, O | 2.958 | — |
| Magnesium Fluoride | F, Mg | 3 | — |
| Magnesium Oxide | Mg, O | 3.58 | — |
| Magnesium Tetraborate | B, Mg, O | 2.53 | — |
| Manganese | Mn | 7.44 | 102 (calculated), 109 (calculated) |
| Mercuric Iodide | Hg, I | 6.36 | — |
| Methane | C, H | 0.000667151 | — |
| Methanol | C, H, O | 0.7914 | — |
| Mix D Wax | C, H, Mg, O, Ti | 0.99 | — |
| Molybdenum | Mo | 10.22 | 103 (calculated), 106 (calculated) |
| Ms20 Tissue | C, Cl, H, Mg, N, O | 1 | — |
| Muscle Skeletal Icrp | C, Cl, H, K, N, Na, O, P, S | 1.05 | — |
| Muscle Striated Icru | C, H, K, N, Na, O, P, S | 1.04 | — |
| Muscle With Sucrose | C, H, N, O | 1.11 | — |
| Muscle Without Sucrose | C, H, N, O | 1.07 | — |
| Mylar | C, H, O | 1.4 | — |
| N | N | 0.0011652 | — |
| N,N-Dimethyl Formamide | C, H, N, O | 0.9487 | — |
| N-Butyl Alcohol | C, H, O | 0.8098 | — |
| N-Heptane | C, H | 0.68376 | — |
| N-Hexane | C, H | 0.6603 | — |
| N-Pentane | C, H | 0.6262 | — |
| N-Propyl Alcohol | C, H, O | 0.8035 | — |
| Na | Na | 0.971 | 324 (calculated), 334 (calculated) |
| Naphthalene | C, H | 1.145 | — |
| Nd | Nd | 6.9 | 202 (calculated), 202 (calculated) |
| Ne | Ne | 0.000838505 | 206 (calculated), 534 (calculated) |
| Neoprene | C, Cl, H | 1.23 | — |
| Nickel | Ni | 8.902 | 96 (calculated), 108 (calculated) |
| Niobium | Nb | 8.57 | 120 (calculated), 122 (calculated) |
| Nitrobenzene | C, H, N, O | 1.19867 | — |
| Nitrous Oxide | N, O | 0.00183094 | — |
| Np | Np | 20.25 | 116 (calculated), 117 (calculated) |
| Nylon-11 Rilsan | C, H, N, O | 1.425 | — |
| Nylon-6-10 | C, H, N, O | 1.14 | — |
| Nylon-6-6 | C, H, N, O | 1.14 | — |
| Nylon-8062 | C, H, N, O | 1.08 | — |
| O | O | 0.00133151 | — |
| Octadecanol | C, H, O | 0.812 | — |
| Octane | C, H | 0.7026 | — |
| Os | Os | 22.57 | 85 (calculated), 89 (calculated) |
| P | P | 2.2 | 237 (calculated), 223 (calculated) |
| Pa | Pa | 15.37 | 125 (calculated), 125 (calculated) |
| Palladium | Pd | 12.02 | 102 (calculated), 113 (calculated) |
| Paraffin | C, H | 0.93 | — |
| Pbwo4 | O, Pb, W | 8.28 | — |
| Phosphoric Acid | H, O, P | 1.87 | — |
| Photo Emulsion | Ag, Br, C, H, I, N, O, S | 3.815 | — |
| Plastic Sc Vinyltoluene | C, H | 1.032 | — |
| Platinum | Pt | 21.45 | 93 (calculated), 101 (calculated) |
| Plexiglass | C, H, O | 1.19 | — |
| Plutonium Dioxide | O, Pu | 11.46 | — |
| Pm | Pm | 7.22 | 201 (calculated), 202 (calculated) |
| Po | Po | 9.32 | 214 (calculated), 216 (calculated) |
| Polyacrylonitrile | C, H, N | 1.17 | — |
| Polycarbonate | C, H, O | 1.2 | — |
| Polychlorostyrene | C, Cl, H | 1.3 | — |
| Polyethylene | C, H | 0.94 | — |
| Polyoxymethylene | C, H, O | 1.425 | — |
| Polypropylene | C, H | 0.9 | — |
| Polystyrene | C, H | 1.06 | — |
| Polytrifluorochloroethylene | C, Cl, F | 2.1 | — |
| Polyvinyl Acetate | C, H, O | 1.19 | — |
| Polyvinyl Alcohol | C, H, O | 1.3 | — |
| Polyvinyl Butyral | C, H, O | 1.12 | — |
| Polyvinyl Chloride | C, Cl, H | 1.3 | — |
| Polyvinyl Pyrrolidone | C, H, N, O | 1.25 | — |
| Polyvinylidene Chloride | C, Cl, H | 1.7 | — |
| Polyvinylidene Fluoride | C, F, H | 1.76 | — |
| Potassium Iodide | I, K | 3.13 | — |
| Potassium Oxide | K, O | 2.32 | — |
| Pr | Pr | 6.71 | 200 (calculated), 200 (calculated) |
| Propane | C, H | 0.00187939 | — |
| Pu | Pu | 19.84 | 137 (calculated), 141 (calculated) |
| Pyrex Glass | Al, B, K, Na, O, Si | 2.23 | — |
| Pyridine | C, H, N | 0.9819 | — |
| Ra | Ra | 5 | 308 (calculated), 309 (calculated) |
| Rb | Rb | 1.532 | 377 (calculated), 408 (calculated) |
| Re | Re | 21.02 | 90 (calculated), 93 (calculated) |
| Rh | Rh | 12.41 | 92 (calculated), 100 (calculated) |
| Rn | Rn | 0.00900662 | — |
| Ru | Ru | 12.41 | 89 (calculated), 95 (calculated) |
| Rubber Butyl | C, H | 0.92 | — |
| Rubber Natural | C, H | 0.92 | — |
| Rubber Neoprene | C, Cl, H | 1.23 | — |
| S | S | 2 | — |
| Sb | Sb | 6.691 | 208 (calculated), 211 (calculated) |
| Sc | Sc | 2.989 | 196 (calculated), 193 (calculated) |
| Se | Se | 4.5 | 281 (calculated), 313 (calculated) |
| Si | Si | 2.33 | 222 (calculated), 211 (calculated) |
| Silicon Dioxide | O, Si | 2.32 | — |
| Silver | Ag | 10.5 | 122 (calculated), 137 (calculated) |
| Silver Bromide | Ag, Br | 6.473 | — |
| Silver Chloride | Ag, Cl | 5.56 | — |
| Silver Halides | Ag, Br, I | 6.47 | — |
| Silver Iodide | Ag, I | 6.01 | — |
| Skin Icrp | C, Cl, H, K, N, Na, O, P, S | 1.09 | — |
| Sm | Sm | 7.46 | 200 (calculated), 203 (calculated) |
| Sodium Carbonate | C, Na, O | 2.532 | — |
| Sodium Iodide | I, Na | 3.667 | — |
| Sodium Monoxide | Na, O | 2.27 | — |
| Sodium Nitrate | N, Na, O | 2.261 | — |
| Sr | Sr | 2.54 | 311 (calculated), 300 (calculated) |
| Stainless-Steel | Cr, Fe, Ni | 8 | — |
| Stilbene | C, H | 0.9707 | — |
| Sucrose | C, H, O | 1.5805 | — |
| Tantalum | Ta | 16.654 | 115 (calculated), 117 (calculated) |
| Tb | Tb | 8.229 | 201 (calculated), 205 (calculated) |
| Tc | Tc | 11.5 | 94 (calculated), 99 (calculated) |
| Te | Te | 6.24 | 286 (calculated), 307 (calculated) |
| Teflon | C, F | 2.2 | — |
| Terphenyl | C, H | 1.24 | — |
| Testis Icrp | C, Cl, H, K, N, Na, O, P, S | 1.04 | — |
| Tetrachloroethylene | C, Cl | 1.625 | — |
| Th | Th | 11.72 | 170 (calculated), 167 (calculated) |
| Thallium Chloride | Cl, Tl | 7.004 | — |
| Thymine | C, H, N, O | 1.48 | — |
| Tin | Sn | 7.31 | 182 (calculated), 211 (calculated) |
| Tissue Soft Icrp | C, Cl, H, K, N, Na, O, P, S | 1.03 | — |
| Tissue Soft Icru-4 | C, H, N, O | 1 | — |
| Tissue-Methane | C, H, N, O | 0.00106409 | — |
| Tissue-Propane | C, H, N, O | 0.00182628 | — |
| Titanium | Ti | 4.54 | 144 (calculated), 146 (calculated) |
| Titanium Dioxide | O, Ti | 4.26 | — |
| Tl | Tl | 11.72 | 183 (calculated), 203 (calculated) |
| Tm | Tm | 9.321 | 198 (calculated), 203 (calculated) |
| Toluene | C, H | 0.8669 | — |
| Trichloroethylene | C, Cl, H | 1.46 | — |
| Triethyl Phosphate | C, H, O, P | 1.07 | — |
| Tungsten | W | 19.3 | 98 (calculated), 100 (calculated) |
| Tungsten Hexafluoride | F, W | 2.4 | — |
| U | U | 18.95 | 107 (calculated), 108 (calculated) |
| Uracil | C, H, N, O | 1.32 | — |
| Uranium Dicarbide | C, U | 11.28 | — |
| Uranium Monocarbide | C, U | 13.63 | — |
| Uranium Oxide | O, U | 10.96 | — |
| Urea | C, H, N, O | 1.323 | — |
| Valine | C, H, N, O | 1.23 | — |
| Vanadium | V | 6.11 | 114 (calculated), 119 (calculated) |
| Viton | C, F, H | 1.8 | — |
| Water | H, O | 1 | — |
| Water Vapor | H, O | 0.000756182 | — |
| Xe | Xe | 0.00548536 | 299 (calculated), 416 (calculated) |
| Xylene | C, H | 0.87 | — |
| Y | Y | 4.469 | 215 (calculated), 208 (calculated) |
| Yb | Yb | 6.73 | 254 (calculated), 253 (calculated) |
| Zinc | Zn | 7.133 | 134 (calculated), 146 (calculated) |
| Zirconium | Zr | 6.506 | 156 (calculated), 154 (calculated) |

## Encapsulation foils

6 of 6 entries include lifetime references. A dash marks a material with composition and density only. Multiple values may describe different methods or sample conditions. See the record before selecting a value.

| Entry | Elements | Density (g/cm³) | Lifetime references (ps) |
| --- | --- | --- | --- |
| Aluminium | Al | 2.699 | 165 (calculated), 153 (calculated) |
| Gold | Au | 19.32 | 108 (calculated), 119 (calculated) |
| Kapton | C, H, N, O | 1.42 | 385 (measured), 381.3 (measured) |
| Lead | Pb | 11.35 | 188 (calculated), 197 (calculated) |
| Nickel | Ni | 8.902 | 96 (calculated), 108 (calculated) |
| Silver | Ag | 10.5 | 122 (calculated), 137 (calculated) |

## Shielding materials

| Entry | Geant4 material | Elements | Density (g/cm³) |
| --- | --- | --- | --- |
| Aluminium | G4_Al | Al | 2.699 |
| Gold | G4_Au | Au | 19.32 |
| Lead | G4_Pb | Pb | 11.35 |
| Nickel | G4_Ni | Ni | 8.902 |
| Silver | G4_Ag | Ag | 10.5 |
<!-- factory-catalogue:end -->
