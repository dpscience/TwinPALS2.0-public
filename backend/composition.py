# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Chemical formula input for atomic proportions; no mass/optical inference."""
import math
import re

ELEMENTS = 'H He Li Be B C N O F Ne Na Mg Al Si P S Cl Ar K Ca Sc Ti V Cr Mn Fe Co Ni Cu Zn Ga Ge As Se Br Kr Rb Sr Y Zr Nb Mo Tc Ru Rh Pd Ag Cd In Sn Sb Te I Xe Cs Ba La Ce Pr Nd Pm Sm Eu Gd Tb Dy Ho Er Tm Yb Lu Hf Ta W Re Os Ir Pt Au Hg Tl Pb Bi Po At Rn Fr Ra Ac Th Pa U Np Pu Am Cm Bk Cf Es Fm Md No Lr Rf Db Sg Bh Hs Mt Ds Rg Cn Nh Fl Mc Lv Ts Og'.split()
SUBSCRIPTS = str.maketrans('₀₁₂₃₄₅₆₇₈₉','0123456789')


def parse_formula(text):
    text=str(text).translate(SUBSCRIPTS).replace(' ','').strip()
    if not text or len(text)>240:
        raise ValueError('Enter a chemical formula, for example SiO2, BaF2 or Lu1.8Y0.2SiO5.')
    result={}
    for part in text.split('·'):
        tokens=re.findall(r'[A-Z][a-z]?|\d+(?:\.\d+)?|[()\[\]]',part)
        if ''.join(tokens)!=part: raise ValueError('Use element symbols, positive proportions and parentheses. Separate hydrate groups with ·, for example CuSO4·5H2O.')
        pos=0
        def amount():
            nonlocal pos
            if pos<len(tokens) and tokens[pos][0].isdigit():
                value=float(tokens[pos]);pos+=1
                if not math.isfinite(value) or value<=0 or value>1e6: raise ValueError('Every element or group proportion must be greater than zero and at most 1,000,000.')
                return value
            return 1.
        multiplier=amount()
        def group(closing=None):
            nonlocal pos
            values={}
            while pos<len(tokens):
                token=tokens[pos];pos+=1
                if token in (')',']'):
                    if token!=closing: raise ValueError('The formula has unmatched parentheses or brackets.')
                    if not values: raise ValueError('A formula group cannot be empty.')
                    return values
                if token in ('(','['):
                    inner=group(')' if token=='(' else ']');factor=amount()
                    for key,value in inner.items(): values[key]=values.get(key,0)+factor*value
                elif token in ELEMENTS:
                    values[token]=values.get(token,0)+amount()
                else: raise ValueError(f'“{token}” is not a chemical element. Check capitalization, for example Co for cobalt.')
            if closing: raise ValueError('Close the parentheses or brackets in the formula.')
            if not values: raise ValueError('Enter at least one chemical element.')
            return values
        for key,value in group().items(): result[key]=result.get(key,0)+multiplier*value
    return result


def validate_composition(properties):
    composition=properties.get('composition',{})
    if not isinstance(composition,dict): raise ValueError('Composition: use an element table or apply a chemical formula.')
    if properties.get('composition_basis','atoms') not in ('atoms','mass_fraction'):
        raise ValueError('Composition: choose atomic proportions or mass fractions.')
    if 'nist_material' in properties and not isinstance(properties['nist_material'],str):
        raise ValueError('Composition: choose a Geant4 material name from the list.')
    if properties.get('formula'):
        if properties.get('composition_basis')!='atoms': raise ValueError('A chemical formula uses atomic proportions. Choose Atomic proportions or clear the formula.')
        parsed=parse_formula(properties['formula'])
        if parsed!=composition: raise ValueError('The formula and element table differ. Apply the formula again or clear it to edit the element table.')
    if properties.get('nist_material'):
        from .standard_materials import standard_catalogue
        if properties['nist_material'] not in standard_catalogue():
            raise ValueError(f'Composition → Standard material: “{properties["nist_material"]}” is not available in Geant4 11.4. Choose a name from the standard-material list.')
        return
    if not composition: raise ValueError('Composition: enter a chemical formula or add elements with positive proportions.')
    for element,value in composition.items():
        if element not in ELEMENTS: raise ValueError(f'Composition: “{element}” is not a chemical element. Use a symbol such as C, Si or Ba.')
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
            raise ValueError(f'Composition → {element}: enter a proportion greater than zero.')
    if properties.get('composition_basis')=='mass_fraction' and not math.isclose(sum(composition.values()),1.,abs_tol=1e-6):
        raise ValueError('Composition: mass fractions must add up to 1 (100%). Adjust the element proportions.')
