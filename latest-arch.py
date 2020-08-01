#!/usr/bin/env python3
import requests
from tqdm import tqdm
import json
from os.path import realpath
import pathlib
from lxml import html
from lxml import etree
from qbittorrent import Client
from tabulate import tabulate
from slugify import slugify
from datetime import datetime
from distutils import util
import sys
import hashlib

URL = 'https://www.archlinux.org'
ENDPOINT = '/releng/releases'
WORKING_DIR = pathlib.Path(realpath(__file__)).parent
LAST_VERSION_INFO = WORKING_DIR / '.arch-iso'

# dont need this to download a small torrent file should remove
# it is overly complex but id like to use it in some other code
def download_file(url, filename=None, path=None):
    if not filename:
        filename = url.split('/')[-1]
    if not path:
        path = WORKING_DIR
    else:
        path = pathlib.Path(path)

    filepath = path / filename
    chunk_size = 1024  # 1 MB
    with requests.get(url, stream=True) as r:
        file_size = int(r.headers.get('content-length'))
        num_bars = file_size // chunk_size
        with open(filepath, 'wb') as f:
            for chunk in tqdm(r.iter_content(chunk_size=chunk_size),
                              total=num_bars,
                              unit='KB',
                              desc=str(filepath),
                              leave=True,
                              file=sys.stdout):
                f.write(chunk)
    return filepath

def torrent_status(hash):
    """
    0 = complete
    1 = not complete
    2 = bad connection/no hash
    """
    qb = Client('http://127.0.0.1:8080/')
    # monitor download
    # check if reachable
    qb.api_version
    qb.qbittorrent_version
    try:
        torrent_info = qb.get_torrent(hash)
    except Exception as e:
        # likely the torrent is not loaded
        # could also be no connection
        print(e)
        return 2
    # '-1' if not complete, otherwise epoch time
    if int(torrent_info['completion_date']) >= 0:
        return 0
    return 1

def file_hash(file_path):
    chunk = 65536  # 64kb
    md5 = hashlib.md5()
    sha1 = hashlib.sha1()
    with open(file_path, 'rb') as f:
        while True:
            data = f.read(chunk)
            if not data: break
            md5.update(data)
            sha1.update(data)
    return {'md5': md5.hexdigest(), 'sha1': sha1.hexdigest()}

def arch_check():
    # Get link to latest release page
    r = requests.get(URL + ENDPOINT)
    page = html.fromstring(r.text)
    latest_release_url = page.xpath('//*[@id="release-table"]/tbody/tr[1]/td[3]/a/@href')[0]

    # Pull data from latest release page
    r = requests.get(URL + latest_release_url)
    page = html.fromstring(r.text)
    ul = page.xpath('//*[@class="release box"]/ul/li')
    links = []
    iso_info = dict()
    for li in ul:
        hrefs = li.xpath('./a/@href')
        if not hrefs:
            row = li.text_content().split(':')
            row = [i.strip() for i in row]
            if len(row) == 2:
                k, v = row
                iso_info[slugify(k, separator='_')] = v
        links.extend(hrefs)

    # Ensure we have the expected fields
    expected_keys = ('release_date', 'kernel_version', 'available', 'md5', 'sha1', 'file_name', 'info_hash')
    for k in expected_keys:
        assert(k in iso_info)
    iso_info = {k: v for k, v in iso_info.items() if k in expected_keys}

    # Convert values
    iso_info['release_date'] = datetime.strptime(iso_info['release_date'], '%Y-%m-%d')
    iso_info['available'] = bool(util.strtobool(iso_info['available']))

    # Display release info
    print(tabulate(iso_info.items()))
    for link in links:
        print(link)
    print()

    qb = Client('http://127.0.0.1:8080/')

    # Download torrent file for release if iso does not exist
    if torrent_status(iso_info['info_hash']) == 2:
        filepath = download_file(URL + latest_release_url + '/torrent', 'archiso.torrent')
        # Start iso download on bittorrent client
        with open(filepath, 'rb') as f:
            qbreturn = qb.download_from_file(f)
    else:
        print("Not downloading")

    iso_path = pathlib.Path(qb.get_default_save_path()) / iso_info['file_name']
    print(file_hash(iso_path))


arch_check()


# TODO:
# check last version
# json for ".arch-iso"
# CWD paths for downloads rather than script file dir
# remove old torrent
# switch to OOP
