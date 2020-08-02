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
from time import sleep

class MissingField(Exception):
    def __init__(self, expression):
        self.expression = expression

class latestArch:
    def __init__(self):
        # TODO - load from configuration or commandline
        self.cwd = pathlib.Path(os.getcwd())
        self.script_dir = pathlib.Path(os.path.realpath(__file__)).parent
        self.arch_url = 'https://www.archlinux.org'
        self.releases_endpoint = '/releng/releases'
        self.releases_url = self.arch_url + self.releases_endpoint
        self.iso_info_path = self.cwd / '.arch-iso'
        self.torrent_path = self.cwd / 'arch.torrent'
        self.bitclient = Client('http://127.0.0.1:8080/')

        self.get_release_url()
        self.get_iso_info()
        self.map_iso_links()
        self.sanitize_iso_info()
        print(tabulate(self.iso_info.items()))
        self.iso_path = self.cwd / self.iso_info['file_name']
        self.get_torrent()
        self.poll_download()
        print(self.file_hash())

    def get_release_url(self):
        r = requests.get(self.releases_url)
        page = html.fromstring(r.text)
        latest_release_endpoint = page.xpath('//*[@id="release-table"]/tbody/tr[1]/td[3]/a/@href')[0]
        self.latest_release_url = self.arch_url + latest_release_endpoint

    def map_iso_links(self):
        for link in self.iso_links:
            if 'magnet' in link.lower():
                self.iso_info['magnet_link'] = link
            elif 'torrent' in link.lower():
                self.iso_info['torrent_link'] = self.arch_url + link

    def get_iso_info(self):
        r = requests.get(self.latest_release_url)
        page = html.fromstring(r.text)
        ul = page.xpath('//*[@class="release box"]/ul/li')
        self.iso_links = []
        self.iso_info = dict()
        for li in ul:
            hrefs = li.xpath('./a/@href')
            if not hrefs:
                row = li.text_content().split(':')
                row = [i.strip() for i in row]
                if len(row) == 2:
                    k, v = row
                    self.iso_info[slugify(k, separator='_')] = v
            self.iso_links.extend(hrefs)

    def sanitize_iso_info(self):
        expected_keys = ('release_date', 'kernel_version', 'available', 'md5',
                         'sha1', 'file_name', 'info_hash', 'magnet_link', 'torrent_link')
        for k in expected_keys:
            if not k in self.iso_info:
                raise MissingField(k)
        self.iso_info = {k: v for k, v in self.iso_info.items() if k in expected_keys}

        # Convert values
        self.iso_info['release_date'] = datetime.strptime(self.iso_info['release_date'], '%Y-%m-%d')
        self.iso_info['available'] = bool(util.strtobool(self.iso_info['available']))

    def get_torrent(self):
        if self.torrent_status() == 2:
            with requests.get(self.iso_info['torrent_link']) as r:
                with open(self.torrent_path, 'wb') as f:
                    f.write(r.content)
            with open(self.torrent_path, 'rb') as f:
                self.bitclient.download_from_file(f)
        else:
            print("Not downloading")

        self.iso_path = pathlib.Path(self.bitclient.get_default_save_path()) / self.iso_info['file_name']
        assert(self.torrent_status() in (0,1))


    def bitclient_status(self):
        try:
            return (self.bitclient.qbittorrent_version, self.bitclient.api_version)
        except:
            return None

    def torrent_status(self):
        """
        0 = complete
        1 = not complete
        2 = no hash
        3 = client not responding
        """
        try:
            self.torrent_info = self.bitclient.get_torrent(self.iso_info['info_hash'])
        except Exception as e:
            if not self.bitclient_status():
                return 3
            return 2
        # '-1' if not complete, otherwise epoch time
        if int(self.torrent_info['completion_date']) >= 0:
            return 0
        # expected fields exist
        for k in ('completion_date', 'dl_speed', 'eta', 'pieces_have', 'pieces_num', 'time_elapsed'):
            if not k in self.torrent_info:
                raise MissingField(k)
        return 1

    def poll_download(self):
        # check that downloaded is increasing between polls
        # set retry limits for client and torrent
        # set polling rate
        # attempt to reload torrent if in bad state
        #  - if not found and client up re-add
        #  - if not downloading force start
        #  - try bumping priority up
        #  - delete and re-add
        with tqdm(total=self.torrent_info['pieces_num']) as pbar:
            pbar.n = self.torrent_info['pieces_have']
            pbar.refresh()
            while True:
                status = self.torrent_status()
                if not status:
                    pbar.close()
                    return
                elif status == 1:
                    pbar.n = self.torrent_info['pieces_have']
                    pbar.refresh()
                elif status == 2:
                    pass
                    # print('no hash')
                elif status == 3:
                    pass
                    # print('no client')
                sleep(3)

    def file_hash(self):
        chunk = 65536  # 64kB
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
# requests checks
