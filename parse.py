#!/usr/bin/env python
import os
import gzip
import urllib.request
from tqdm import tqdm
from lxml import etree
from lxml import html
import pandas as pd
import datetime

##########################
# CONSTANTS
#
DBLP_XML_URL = 'http://dblp.org/xml/dblp.xml.gz'
DBLP_XML_FILENAME = 'dblp.xml.gz'
DBLP_DTD_URL = 'http://dblp.org/xml/dblp.dtd'
DBLP_DTD_FILENAME = 'dblp.dtd'
OUTPUT_CSV_FILENAME='dblp-orcids.csv'


def progress_bar_hook(t):
    """Wraps tqdm instance."""
    last_b = [0]
    def update_to(b=1, bsize=1, tsize=None):
        """
        b  : int, optional
            Number of blocks transferred so far [default: 1].
        bsize  : int, optional
            Size of each block (in tqdm units) [default: 1].
        tsize  : int, optional
            Total size (in tqdm units). If [default: None] remains unchanged.
        """
        if tsize is not None:
            t.total = tsize
        t.update((b - last_b[0]) * bsize)
        last_b[0] = b

    return update_to

# download files
print("Downloading DBLP XML files...")
with tqdm(unit='B', unit_scale=True, unit_divisor=1024, miniters=1, desc=DBLP_XML_FILENAME) as t:
    urllib.request.urlretrieve(DBLP_XML_URL, filename=DBLP_XML_FILENAME,reporthook=progress_bar_hook(t), data=None)
with tqdm(unit='B', unit_scale=True, unit_divisor=1024, miniters=1, desc=DBLP_DTD_FILENAME) as t:
    urllib.request.urlretrieve(DBLP_DTD_URL, filename=DBLP_DTD_FILENAME,reporthook=progress_bar_hook(t), data=None)


##########################
# PARSING DATA STRUCTURES
#
# ALIAS -> dict(all_alias, dblp_key, affiliation, orcid, google_scholar_id, scopus_id, acm_id)
alias_info = {}
# ORCID -> set(ALIAS)
orcid_alias = {}
# ALIAS -> set(ORCID)
alias_orcid = {}
# adds pair of entries to bimap
def add_bimap(alias, orcid):
    if alias not in alias_orcid:
        alias_orcid[alias] = set()
    if orcid not in orcid_alias:
        orcid_alias[orcid] = set()

    alias_orcid[alias].add(orcid)
    orcid_alias[orcid].add(alias)


##########################
# PARSING METHODS
#
# processes author tags
def process_author(element):
    if 'orcid' in element.attrib:
        alias = element.text
        orcid = element.attrib['orcid']

        # inits bi-directional entries
        add_bimap(alias, orcid)


# processes www tags
def process_www(element):
    if 'key' in element.attrib and element.attrib['key'].startswith("homepages"):
        all_alias = set(element.xpath('author/text()'))

        info = {
            'dblp_key': element.attrib['key'],
            'affiliation': element.findtext("note[@type='affiliation']"),
            'orcid': None,
            'researcher_id': None,
            'google_scholar_id': None,
            'scopus_id': None,
            'acm_id': None,
            'homepage': None,
        }

        # finds info based on author urls
        for url in element.xpath("url/text()"):
            # some cleanup
            url = url.strip("/")
            # tries to find several standard information
            if 'orcid.org/' in url: info['orcid'] = url.rpartition('/')[-1]
            elif 'researcherid' in url: info['researcher_id'] = url.rpartition('/')[-1]
            elif 'scholar.google' in url: info['google_scholar_id'] = url.rpartition("user=")[-1]
            elif 'scopus' in url: info['scopus_id'] = url.rpartition("authorId=")[-1]
            elif 'dl.acm.org/author_page' in url: info['acm_id'] = url.rpartition("id=")[-1]
            # other not very relevant urls that we skip
            elif 'wikidata' in url: continue
            elif 'genealogy.ams.org' in url: continue
            elif 'researchgate' in url: continue
            elif 'mendeley' in url: continue
            elif 'github' in url: continue
            elif 'twitter' in url: continue
            elif 'wikipedia' in url: continue
            elif 'isni' in url: continue
            elif 'linkedin' in url: continue
            # everything else we consider homepage, but we just consider 1
            else: info['homepage'] = url

        # save info on all alias
        for alias in all_alias:
            alias_info[alias] = info
            # if exists saves on bimap and searches for more aliases
            if info['orcid'] is not None:
                add_bimap(alias, info['orcid'])


# merges info by orcid
def info_by_orcid():
    final = {}
    for orcid, aliases in orcid_alias.items():
        # merges all alias_info
        info = {}
        for alias in aliases:
            if info:
                info = alias_info[alias]
            else:
                # from running we found out that we might have
                # different alias info for the same orcid hence
                # we merging dict infos
                info.update({k:v for k,v in alias_info[alias].items() if v})

        # adds info to all alias
        for alias in aliases:
            alias_info[alias] = info

        # but we add all aliases to the final result
        info['alias'] = aliases
        info['orcid'] = orcid
        final[orcid] = info

    return final


def fast_iter(context, func, *args, **kwargs):
    """
    http://lxml.de/parsing.html#modifying-the-tree
    Based on Liza Daly's fast_iter
    http://www.ibm.com/developerworks/xml/library/x-hiperfparse/
    See also http://effbot.org/zone/element-iterparse.htm
    """
    for event, elem in context:
        func(elem, *args, **kwargs)
        # It's safe to call clear() here because no descendants will be accessed
        # filter for end-ns event due to DTD replacements
        if event == 'end-ns':
            elem.clear()
            # Also eliminate now-empty references from the root node to elem
            for ancestor in elem.xpath('ancestor-or-self::*'):
                while ancestor.getprevious() is not None:
                    del ancestor.getparent()[0]
    del context

counter = 0
def process_element(element):
    global counter
    globals()['process_'+element.tag](element)
    counter += 1
    if counter % 100000 == 0:
        print(str(counter)+ " xml nodes processed.")
    # if counter == 100000 * 20:
    #     exit()

# first parses all the authors with orcids
print("Started parsing...")
context = etree.iterparse(gzip.GzipFile(DBLP_XML_FILENAME), events=('end','end-ns'), tag=('author','www'), load_dtd=True, dtd_validation=True)
fast_iter(context,process_element)

# merges info by orcid
final = info_by_orcid()
print("Finished parsing!")

# remove files
os.remove(DBLP_DTD_FILENAME)
os.remove(DBLP_XML_FILENAME)
print("Removed DBLP xml files.")

# export to csv
df = pd.DataFrame(list(final.values()))
order = ['orcid','alias','dblp_key','affiliation','researcher_id','google_scholar_id','scopus_id','acm_id','homepage']
df = df.reindex(columns=order).sort_values('orcid')
with open(OUTPUT_CSV_FILENAME, 'w') as f:
    f.write('# PARSED ON ' + datetime.datetime.today().strftime('%Y-%m-%d') + '\n')
    df.to_csv(f, index=False, encoding='utf-8')
print("Parsed info saved to: " + OUTPUT_CSV_FILENAME)