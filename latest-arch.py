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
        self.hash = 'sha1'
        self.torrent_path = self.cwd / 'arch.torrent'
        self.bitclient = Client('http://127.0.0.1:8080/')
        self.expected_torrent_fields = ('completion_date', 'eta', 'pieces_have', 'pieces_num')
        self.expected_iso_fields = ('release_date', 'kernel_version', self.hash,
                                    'file_name', 'info_hash', 'torrent_link')

        if not self.bitclient_status():
            print('Bittorrent client not reachable.')
            sys.exit()
        self.load_last_iso_info()
        self.get_release_url()
        self.get_iso_info()
        self.map_iso_links()
        self.sanitize_iso_info()
        self.iso_path = self.cwd / self.iso_info['file_name']
        print(tabulate(self.iso_info.items()))
        if not self.is_new_release():
            print("Current is latest, no action needed.")
            sys.exit()
        self.get_torrent()
        self.poll_download()
        if not self.good_file_hash():
            print("Does not match checksum, download corupt.")
        self.save_iso_info()

    def get_release_url(self):
        print('find page for latest release')
        r = requests.get(self.releases_url)
        page = html.fromstring(r.text)
        latest_release_endpoint = page.xpath('//*[@id="release-table"]/tbody/tr[1]/td[3]/a/@href')[0]
        self.latest_release_url = self.arch_url + latest_release_endpoint

    def map_iso_links(self):
        print('translate links to keyed values')
        for link in self.iso_links:
            if 'magnet' in link.lower():
                self.iso_info['magnet_link'] = link
            elif 'torrent' in link.lower():
                self.iso_info['torrent_link'] = self.arch_url + link

    def get_iso_info(self):
        print('scraping iso info')
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
        print('sanitize iso info')
        for k in self.expected_iso_fields:
            if not k in self.iso_info:
                raise MissingField(k)
        self.iso_info = {k: v for k, v in self.iso_info.items() if k in self.expected_iso_fields}

        # Convert value
        self.iso_info['release_date'] = datetime.strptime(self.iso_info['release_date'], '%Y-%m-%d')
        # self.iso_info['available'] = bool(util.strtobool(self.iso_info['available']))

    def is_new_release(self):
        print('check for new release')
        assert(set(self.iso_info.keys()) == set(self.last_iso_info.keys()))
        if self.iso_info[self.hash] != self.last_iso_info[self.hash]:
            return True
        if not self.iso_path.exists():
            return True
        if not self.good_file_hash():
            print('Cache claims latest, checksums dont match')
            return True
        return False

    def get_torrent(self):
        print('download and start torrent')
        #TODO check path
        if self.torrent_status() == 2:
            with requests.get(self.iso_info['torrent_link']) as r:
                with open(self.torrent_path, 'wb') as f:
                    f.write(r.content)
            with open(self.torrent_path, 'rb') as f:
                self.bitclient.download_from_file(f, savepath=self.cwd)
        else:
            print("Not downloading")

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
        for k in self.expected_torrent_fields:
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

    def good_file_hash(self):
        print('Checking hash')
        chunk = 65536  # 64kB
        md5 = hashlib.md5()
        sha1 = hashlib.sha1()
        with open(self.iso_path, 'rb') as f:
            while True:
                data = f.read(chunk)
                if not data: break
                if self.hash == 'md5': md5.update(data)
                elif self.hash == 'sha1': sha1.update(data)
                else: raise Exception
        if self.hash == 'md5':
            return md5.hexdigest() == self.iso_info['md5']
        return sha1.hexdigest() == self.iso_info['sha1']

    def save_iso_info(self):
        print('save iso info')
        #TODO check path
        with open(self.iso_info_path, 'w') as f:
            # datetime object will default to string
            f.write(json.dumps(self.iso_info, default=str))

    def load_last_iso_info(self):
        print('load iso info')
        #TODO check path
        self.last_iso_info = dict()
        if self.iso_info_path.exists():
            with open(self.iso_info_path, 'r') as f:
                self.last_iso_info = json.loads(f.read())
                self.last_iso_info['release_date'] = datetime.strptime(self.last_iso_info['release_date'], '%Y-%m-%d %H:%M:%S')

latestArch()


# TODO:
# remove old torrent
# requests checks
# cli
# print to logging
