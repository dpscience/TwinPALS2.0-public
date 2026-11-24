# SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
# SPDX-License-Identifier: MIT
# Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import hashlib
import json
from pathlib import Path

import pytest

from backend import __version__
from backend.mcp_server import knowledge
from backend.mcp_server.cli import rpc


def request(method,params=None):
    return rpc(dict(jsonrpc='2.0',id=1,method=method,params=params or {}),None)


def call(tool,arguments):
    response=request('tools/call',{'name':tool,'arguments':arguments})['result']
    assert not response.get('isError')
    return json.loads(response['content'][0]['text'])


def test_all_chapters_available_via_resources_and_tools_without_service():
    assert 'resources' in request('initialize')['result']['capabilities']
    resources=request('resources/list')['result']['resources']
    result=call('knowledge_search',{})['topics']
    assert {row['uri'] for row in result}=={r['uri'] for r in resources}
    for row in result:
        item=call('knowledge_read',{'topic':row['topic']})
        content=request('resources/read',{'uri':row['uri']})['result']['contents'][0]
        assert content['uri']==row['uri'] and content['mimeType']=='text/markdown' and item['text'] in content['text']
        assert item['version']==__version__ and item['sha256']==hashlib.sha256(item['text'].encode()).hexdigest()
        for ref in item['references']:
            assert (Path(__file__).resolve().parents[1]/ref['path']).is_file()
    assert request('resources/read',{'uri':'twinpals://methods/../../etc'})['error']['code']==-32002
    assert request('tools/call',{'name':'knowledge_read','arguments':{'topic':'../data'}})['result']['isError']


def test_search_and_exclusive_pileup_example():
    assert 'contributions' in {t['topic'] for t in call('knowledge_search',{'query':'pile-up','limit':3})['topics']}
    assert not call('knowledge_search',{'query':'xyzzy814'})['topics']
    from backend.m3_signal import provenance
    f=[{'valid':True,'support':[10,20]}]*2
    pulses=[dict(channel=c,role=r,decay=9,onset_ns=12,end_ns=18,light_origin='scintillation') for c,r in [(0,1),(0,0),(1,1)]]
    chapter=knowledge.read_topic('contributions')['text']
    assert '511 + 1275' in chapter and 'multiple-decay' in chapter
    assert provenance({'pulses':pulses},f,'na22')['category']=='pileup_same_decay'
    pulses[0]['decay']=10
    assert provenance({'pulses':pulses},f,'na22')['category']=='pileup_multiple_decays'
    pulses[0]['onset_ns']=23
    assert provenance({'pulses':pulses},f,'na22')['category']=='correlated'


def test_release_requires_version_link_in_same_repository(tmp_path):
    path=tmp_path/'source.json'
    repo='https://github.com/example/test'
    def set_links(url, release):
        path.write_text(json.dumps(dict(repository=url,release=release)))
    set_links(None,None)
    assert knowledge.source_metadata(path)['release'] is None
    with pytest.raises(ValueError):
        knowledge.source_metadata(path,official=True)
    for bad in [repo+'/releases/latest',repo+'/releases/tag/v1.0.0','https://github.com/other/test/releases/tag/v'+__version__]:
        set_links(repo,bad)
        with pytest.raises(ValueError):
            knowledge.source_metadata(path,official=True)
    tag='v'+__version__
    set_links(repo,repo+'/releases/tag/'+tag)
    assert knowledge.source_metadata(path,official=True)['tag']==tag

