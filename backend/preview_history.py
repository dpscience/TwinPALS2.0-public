# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

"""Incremental retention of the existing per-detector preview buckets."""
from collections import OrderedDict,deque


class PreviewHistory:
    def __init__(self,limit):
        self.limit=limit
        self.buckets={}
        self.references={}
        self.ordered=OrderedDict()

    def append(self,message):
        identity=id(message);self.ordered[identity]=message
        # Preserve the legacy [-0:] retention contract. A separate UI/format
        # change is required before zero can acquire different semantics.
        if self.limit==0:return list(self.ordered.values()),[]
        self.references[identity]=0
        expired=[]
        for detector,category in {'all':message.get('category','miss'),**message.get('detectors',{})}.items():
            origins=message.get('pulse_origins',[0,0])
            origin=tuple(origins) if detector=='all' else origins['AB'.index(detector)]
            key=(message['role'],detector,category,origin)
            bucket=self.buckets.setdefault(key,deque());bucket.append(identity)
            self.references[identity]+=1
            if len(bucket)>self.limit:
                old=bucket.popleft();self.references[old]-=1
                if not self.references[old]:
                    del self.references[old];expired.append(self.ordered.pop(old))
        return list(self.ordered.values()),expired
