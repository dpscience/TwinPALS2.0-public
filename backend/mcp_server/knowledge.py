# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Versioned, offline methods shared by MCP resources and the lookup tools."""
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from backend import __version__
from backend.app import application_root

PREFIX = 'twinpals://methods/'
INDEX = 'overview'
TOPICS = {
    'overview': ('Study workflow and module map', 'overview übersicht einführung workflow settings profile', ('backend/mcp_server/tools.py','tests/test_mcp_studies.py')),
    'detector-response': ('Module 1 · Detector response', 'm1 szintillator scintillation cherenkov pmt quantum efficiency TTS optics geometry transport anode', ('native/transport.hpp','native/analog_pmt.hpp','docs/STREAM_FORMAT.md','tests/test_light_origin.py')),
    'acquisition': ('Module 2 · Acquisition and measurement time', 'm2 trigger digitizer cable source clock measurement time messzeit dead time lifetime co60 na22', ('native/acquisition_scan.hpp','native/adc_waveform.hpp','docs/MODULE2_STREAM.md','tests/test_module2_physics.py')),
    'pulse-measurement': ('Module 3 · Pulse measurement and filters', 'm3 CF baseline pile-up onset time rise fall area median interpolation akima filter puls flanke', ('backend/m3_signal.py','backend/m3_interpolation.py','tests/test_module3.py','tests/test_m3_filter_views.py')),
    'contributions': ('Module 3 · Pile-up and contribution classes', 'm3 pileup pile-up überlagerung decay zufallskoinzidenz photon 511 accidental provenance scatter streuung subtypes mixed', ('backend/m3_signal.py','backend/m3_subtypes.py','native/lifetime_truth.hpp','tests/test_m3_pileup.py')),
    'spectra': ('Module 3 · Reading lifetime and pulse-height spectra', 'm3 merged AB BA SS PHS percentages prozent counts bins lifetime ns ps zero delay superimposed', ('backend/m3_spectra.py','frontend/src/spectrumAnalysis.ts','tests/test_m3_spectrum_comparison.py')),
    'catalogue': ('Component catalogue and data provenance', 'database datenbank PMT photomultiplier scintillator source assumptions fenster thickness material curves revision references', ('backend/material_database.py','backend/m1_resolve.py','tests/test_unified_catalogue260.py')),
    'studies': ('Designing, recovering and reporting a study', 'study optimise optimize uncertainty seed simulation validation paper manuscript receipt replay parallel recovery', ('backend/mcp_server/studies.py','backend/mcp_server/engine.py','scripts/verify_mcp.py','tests/test_mcp_studies.py')),
}


def folder():
    return application_root()/'docs/mcp/knowledge'


def source_metadata(path=None, version=__version__, official=False):
    values=json.loads((path or folder()/'source.json').read_text(encoding='utf-8'))
    repo,release=values['repository'],values['release']
    if repo is not None and (not isinstance(repo,str) or not re.fullmatch(r'https://github\.com/[A-Za-z0-9-]+/[A-Za-z0-9_.-]+',repo)):
        raise ValueError('Expected the canonical public GitHub repository URL.')
    tag=None
    if release is not None:
        if not repo or release not in [repo+'/releases/tag/'+v for v in (version,'v'+version)]:
            raise ValueError('Official release URL must identify the configured repository and this exact version.')
        tag=urlsplit(release).path.rsplit('/',1)[-1]
    if official and not tag:
        raise ValueError('Set the public repository and official release URL for version '+version+' before publication.')
    return dict(repository=repo,release=release,tag=tag)


def resources():
    return [dict(uri=PREFIX+key,name=key,title=info[0],mimeType='text/markdown') for key,info in TOPICS.items()]


def read_topic(key):
    if key not in TOPICS:
        raise ValueError('Unknown methods topic. Use knowledge_search with an empty query to list topics.')
    title,_,paths=TOPICS[key]
    content=(folder()/(key+'.md')).read_text(encoding='utf-8')
    source=source_metadata()
    tag=source['tag']
    return dict(topic=key,uri=PREFIX+key,title=title,version=__version__,sha256=sha256(content.encode()).hexdigest(),
                text=content,source=source,references=[dict(path=p,url=(source['repository']+'/blob/'+tag+'/'+p) if tag else None) for p in paths])


def search(query='',limit=8):
    terms=set(re.findall(r'[\w]+',query.casefold()))
    matches=[]
    for key,(title,aliases,_) in TOPICS.items():
        heading=(key+' '+title+' '+aliases).casefold()
        paragraphs=(folder()/(key+'.md')).read_text(encoding='utf-8').strip().split('\n\n')
        body='\n'.join(paragraphs).casefold()
        score=sum(4*(word in heading)+(word in body) for word in terms)
        if terms and not score:
            continue
        excerpt=max(paragraphs[1:],key=lambda part: sum(w in part.casefold() for w in terms))
        matches.append((score,dict(topic=key,title=title,uri=PREFIX+key,excerpt=excerpt[:280])))
    matches.sort(key=lambda match:-match[0])
    return dict(version=__version__,source=source_metadata(),topics=[m for _,m in matches[:limit]])


def resource_text(uri):
    if not isinstance(uri,str) or not uri.startswith(PREFIX):
        raise ValueError('Unknown methods resource.')
    item=read_topic(uri[len(PREFIX):])
    references=[ref['url'] or ref['path'] for ref in item['references']]
    return item['text']+'\n\nTwinPALS '+item['version']+'\n'+'\n'.join(references+[item['source']['release'] or 'Development preview'])

