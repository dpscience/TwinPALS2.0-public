# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Optional cited bulk/material lifetimes; never transport completeness criteria."""
from typing import Literal
from urllib.parse import urlsplit
from pydantic import BaseModel,ConfigDict,Field,field_validator

class MaterialLifetime(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
    tau_ps:float=Field(gt=0,le=1e9)
    kind:Literal['calculated','measured','assumed']='calculated'
    method:str=Field(min_length=1,max_length=250)
    state:str=Field(min_length=1,max_length=500)
    reference_title:str=Field(min_length=1,max_length=500)
    reference_url:str=Field(min_length=1,max_length=1000)
    comment:str=Field('',max_length=3000)
    @field_validator('reference_url')
    @classmethod
    def source(cls,value):
        p=urlsplit(value)
        if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
            raise ValueError('Lifetime source: enter a full http or https URL.')
        return value

def validate_lifetimes(properties):
    values=properties.get('positron_lifetimes',[])
    if not isinstance(values,list) or len(values)>50:raise ValueError('Lifetime: use at most 50 referenced values.')
    if 'positron_lifetimes' in properties:
        properties['positron_lifetimes']=[MaterialLifetime.model_validate(v).model_dump(mode='json') for v in values]

def input_materials(info,entries):
    """Frozen stream identity, optional suggestions from the current database."""
    header=info['streams'][0]['header'];sample=header['profile']['sample']
    by_id={e['id']:e for e in entries};names=header.get('material_names',{})
    ids=[]
    if sample['enabled']:
        ids.extend((side,sample[side]['material_id'],'sample') for side in ('left','right'))
    if sample['foil_enabled'] and sample['foil_thickness_mm']>0:
        ids.append(('foil',sample['foil_material_id'],'foil'))
    return [dict(position=pos,id=id,category=category,name=names.get(id,id),
        present=id in by_id,lifetimes=by_id.get(id,{}).get('properties',{}).get('positron_lifetimes',[])) for pos,id,category in ids]
