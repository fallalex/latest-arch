#!/usr/bin/env python3
import requests
from tqdm import tqdm
import json
import os
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

class latestArch:
    def __init__(self):
        self.arch_url = 'https://www.archlinux.org'
        self.releases_endpoint = '/releng/releases'
        self.releases_url = self.arch_url + self.releases_endpoint
        self.torrent_url = self.releases_endpoint + '/torrent'
        self.cwd = pathlib.Path(os.getcwd())
        self.script_dir = pathlib.Path(os.path.realpath(__file__)).parent
        self.iso_info_path = self.cwd / '.arch-iso'
        self.torrent_path = self.cwd / 'arch.torrent'
        self.bitclient =Client('http://127.0.0.1:8080/')

        self.get_release_url()
        self.get_iso_info()
        self.str_iso_info()
        self.iso_path = self.cwd / self.iso_info['file_name']
        print(self.file_hash())

    def get_release_url(self):
        r = requests.get(self.releases_url)
        page = html.fromstring(r.text)
        self.latest_release_endpoint = page.xpath('//*[@id="release-table"]/tbody/tr[1]/td[3]/a/@href')[0]
        self.latest_release_url = self.arch_url + self.latest_release_endpoint

    def get_iso_info(self):
        r = requests.get(self.latest_release_url)
        page = html.fromstring(r.text)
        ul = page.xpath('//*[@class="release box"]/ul/li')
        self.iso_links = []
        iso_info = dict()
        for li in ul:
            hrefs = li.xpath('./a/@href')
            if not hrefs:
                row = li.text_content().split(':')
                row = [i.strip() for i in row]
                if len(row) == 2:
                    k, v = row
                    iso_info[slugify(k, separator='_')] = v
            self.iso_links.extend(hrefs)

        # Ensure we have the expected fields
        expected_keys = ('release_date', 'kernel_version', 'available', 'md5', 'sha1', 'file_name', 'info_hash')
        for k in expected_keys:
            assert(k in iso_info)
        self.iso_info = {k: v for k, v in iso_info.items() if k in expected_keys}

        # Convert values
        self.iso_info['release_date'] = datetime.strptime(iso_info['release_date'], '%Y-%m-%d')
        self.iso_info['available'] = bool(util.strtobool(iso_info['available']))

    def str_iso_info(self):
        print(tabulate(self.iso_info.items()))
        for link in self.iso_links:
            print(link)
        print()

    def get_torrent(self):
        if torrent_status(iso_info['info_hash']) == 2:
            with requests.get(self.torrent_url) as r:
                with open(self.torrent_path, 'wb') as f:
                    write(r.content)
            with open(self.torrent_path, 'rb') as f:
                qbreturn = self.bitclient.download_from_file(f)
        else:
            print("Not downloading")

        iso_path = pathlib.Path(qb.get_default_save_path()) / iso_info['file_name']


    def torrent_status(self):
        """
        0 = complete
        1 = not complete
        2 = bad connection/no hash
        """
        # monitor download
        # check if reachable
        self.bitclient.api_version
        self.bitclient.qbittorrent_version
        try:
            torrent_info = self.bitclient.get_torrent(self.iso_info['hash'])
        except Exception as e:
            # likely the torrent is not loaded
            # could also be no connection
            print(e)
            return 2
        # '-1' if not complete, otherwise epoch time
        if int(torrent_info['completion_date']) >= 0:
            return 0
        return 1

    def file_hash(self):
        chunk = 65536  # 64kb
        md5 = hashlib.md5()
        sha1 = hashlib.sha1()
        with open(self.iso_path, 'rb') as f:
            while True:
                data = f.read(chunk)
                if not data: break
                md5.update(data)
                sha1.update(data)
        return {'md5': md5.hexdigest(), 'sha1': sha1.hexdigest()}

latestArch()


# TODO:
# check last version
# json for ".arch-iso"
# CWD paths for downloads rather than script file dir
# remove old torrent
