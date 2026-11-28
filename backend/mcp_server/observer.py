# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Read-only charts derived from the scientific engines' bin counts and edges."""
import math
from functools import lru_cache
import json

from backend.m3_models import SpectrumDisplay

COLORS = ('#137f80', '#466bb2', '#985e9f', '#b36c20')
DIRECTIONS = {'merged': 'Merged', 'AB': 'A → B', 'BA': 'B → A', 'SS': 'Stop–Stop'}


def series(name, bins, color, dashed=False):
    # Step segments use measured bin edges. Gaps in sparse spectra return to zero.
    points = []
    for low, high, count in bins:
        if points and low > points[-1][0]:
            points.extend([[points[-1][0], 0], [low, 0]])
        points.extend([[low, count], [high, count]])
    if points:
        points.insert(0, [points[0][0], 0])
        points.append([points[-1][0], 0])
    return dict(name=name, color=color, dashed=dashed, points=points,
                bins=[dict(low=a, high=b, count=n) for a,b,n in bins])


def distribution(title, unit, items, y_label, note):
    traces = []
    for i, item in enumerate(items):
        edges = item['edges']
        counts = item['counts']
        bins = list(zip(edges, edges[1:], counts)) if any(counts) else []
        traces.append(series(item.get('label') or item.get('name',''), bins, COLORS[i % len(COLORS)]))
    return dict(title=title, xLabel=f'{title} ({unit})' if unit else title, yLabel=y_label,
                series=traces, note=note, emptyText='No observations in this distribution')


def lifetime(direction, comparison, view):
    stages = comparison['stages'][:2 if comparison['filter_active'] else 1]
    occupied = {i for stage in stages for i,n in stage['lifetime']['bins'] if n}
    # Keep native timing resolution for sparse data, even for very distant tails.
    group = math.ceil((max(occupied)-min(occupied)+1)/1200) if len(occupied)>1200 else 1
    width = view.bin_ps / 1000
    traces, notes = [], []
    for index, stage in enumerate(stages):
        hist = stage['lifetime']
        grouped = {}
        for i,n in hist['bins']:
            k = i // group
            grouped[k] = grouped.get(k,0) + n
        bins = [(view.low_ns+k*group*width, min(view.high_ns, view.low_ns+(k+1)*group*width), n)
                for k,n in sorted(grouped.items()) if n]
        name = ('Before filters','After filters')[index] if len(stages)==2 else 'Window-selected pairs'
        traces.append(series(name, bins, COLORS[index], bool(index)))
        total = stage['phs'][0]['counts']
        notes.append(f"{name}: {hist['counts']:,} in range, {total-hist['counts']:,} outside")
    if len(stages)==1:
        notes.append('Area and shape filters off')
    notes.append(f'{view.low_ns:g} to {view.high_ns:g} ns · {view.bin_ps*group:g} ps per displayed bin')
    return dict(title=DIRECTIONS[direction]+' lifetime', xLabel='Time difference (ns)', yLabel='Pairs / bin',
                series=traces, note=' · '.join(notes), emptyText='No pairs in this time range',
                timingGrid=[view.low_ns,view.high_ns,view.bin_ps*group,view.zero_ps,'direction total'])


def charts(module, data, *, displays=None, positive=False):
    if module==1:
        return [distribution('Deposited energy', data['unit'], data['series'], 'Events / bin',
                             'Positive energy deposits per detector and primary.' if positive else
                             'All recorded events, including zero deposited energy, per detector and primary.')]
    if module==2:
        return [distribution(p['title'], p['unit'], p['series'], 'Waveform pairs / bin',
                             f"{data['selected']:,} selected of {data['total']:,} recorded pairs.")
                for p in data['plots']]
    displays = displays or {}
    return [lifetime(d, data['comparisons'][d], displays.get(d) or SpectrumDisplay())
            for d in DIRECTIONS if d in data['comparisons']]


@lru_cache(maxsize=12)
def archived_charts(folder, module):
    # Only called for committed, immutable attempts. Earlier previews used
    # incorrect lifetime coordinates. Reconstruct them from the scientific archive.
    analysis = folder/'analysis.json'
    if not analysis.is_file():
        return []
    return charts(module, json.loads(analysis.read_bytes()))


@lru_cache(maxsize=8)
def query_charts(folder, run_id, name):
    # The caller has already checked the committed receipt and exact file name.
    manifest=json.loads((folder.parent.parent/'manifest.json').read_bytes())
    item=next(s for s in manifest['steps'] if s['id']==run_id)
    q=next(q for q in item['queries'] if q['name']==name)
    path, body=q['path'], q['body']
    if path not in ('/api/m1/analysis','/api/m1/analysis/batch','/api/m2/analysis','/api/m3/analysis','/api/m3/query'):
        return []
    data=json.loads((folder/('query-'+name+'.json')).read_bytes())
    if item['module']==1:
        result=[]
        for histogram in data if isinstance(data,list) else [data]:
            if 'series' in histogram:
                title=histogram['metric'].replace('_',' ').capitalize()
                note=' · '.join(k.replace('_',' ').capitalize()+': '+str(body.get(k,'all'))
                                for k in ('primary','detector','category'))
                result.append(distribution(title,histogram['unit'],histogram['series'],'Events / bin',note))
        return result
    if item['module']==2 and 'plots' in data and 'selected' in data:
        return charts(2,data)
    if path=='/api/m3/analysis':
        return charts(3,data,displays={k:SpectrumDisplay.model_validate(v) for k,v in body.items()})
    if path=='/api/m3/query' and 'spectra' in data:
        result=[]
        view=data['view']
        width=view['bin_ps']/1000
        selection=', '.join(view['categories']) if view.get('categories') is not None else view['category']
        for spectrum in data['spectra']:
            label=DIRECTIONS[spectrum['direction']]
            occupied=[(x,n) for x,n in spectrum['points'] if n]
            group=max(1,math.ceil((occupied[-1][0]-occupied[0][0]+width)/width/1200)) if len(occupied)>1200 else 1
            grouped={}
            for x,n in occupied:
                index=round((x-view['low_ns'])/width-.5)//group
                grouped[index]=grouped.get(index,0)+n
            bins=[(view['low_ns']+k*width*group,min(view['high_ns'],view['low_ns']+(k+1)*width*group),n)
                  for k,n in grouped.items()]
            result.append(dict(title=label+' lifetime',xLabel='Time difference (ns)',yLabel='Pairs / bin',
                               series=[series(label,bins,COLORS[0])],emptyText='No pairs for this selection',
                               timingGrid=[view['low_ns'],view['high_ns'],view['bin_ps']*group,view['zero_ps'],selection,view['origin']],
                               note=f"{spectrum['counts']:,} pairs · Classes: {selection} · Light: {view['origin']} · {view['bin_ps']*group:g} ps per displayed bin"))
        return result
    return []
