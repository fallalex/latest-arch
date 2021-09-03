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
from loguru import logger

class MissingField(Exception):
    def __init__(self, expression):
        self.expression = expression

class BittorrentUnreachable(Exception):
    def __init__(self, expression):
        self.expression = expression

class DownloadStalled(Exception):
    def __init__(self):
        pass

class NoTorrentHash(Exception):
    def __init__(self):
        pass

class ISOFailedHash(Exception):
    def __init__(self):
        pass

class ISONotFound(Exception):
    def __init__(self):
        pass

class latestISO:
    def __init__(self):
        self.log_level = 'DEBUG'
        logger.remove()
        self.log_handler = logger.add(sys.stderr, level=self.log_level)

        # TODO - load from configuration or commandline
        self.cwd = pathlib.Path(os.getcwd())
        self.script_dir = pathlib.Path(os.path.realpath(__file__)).parent
        logger.debug("CWD = '{}'".format(self.cwd))
        logger.debug("Script DIR = '{}'".format(self.script_dir))

        self.poll_interval = 2 # seconds
        self.bitclient = Client('http://127.0.0.1:8080/')
        self.expected_torrent_fields = ('completion_date', 'eta', 'pieces_have', 'pieces_num')
        self.hashes = {'md5': hashlib.md5(), 'sha1': hashlib.sha1()}

    def get_latest(self):
            self.bitclient_status()
            self.load_last_iso_info()
            self.get_iso_info()
            self.iso_path = self.cwd / self.iso_info['file_name']
            logger.info('\n' + tabulate(self.iso_info.items()))
            if not self.is_new_release():
                logger.debug("Current is latest, no action needed.")
                sys.exit()
            self.get_torrent()
            sleep(self.poll_interval * 2) # give time for trackers and peers to establish
            self.torrent_present()
            self.poll_download()
            self.verify_file_hash()
            self.save_iso_info()

    def get(self, url):
        try:
            return requests.get(url)
        except requests.exceptions.HTTPError as e:
            raise SystemExit(e)

    def is_new_release(self):
        logger.debug('check for new release')
        if not self.last_iso_info:
            return True
        assert(set(self.iso_info.keys()) == set(self.last_iso_info.keys()))
        if self.iso_info[self.hash] != self.last_iso_info[self.hash]:
            return True
        if not self.iso_path.exists():
            return True
        if self.torrent_present() and self.torrent_done():
            self.verify_file_hash()
        else:
            return True
        return False

    def get_torrent(self):
        logger.debug('download and start torrent')
        if not self.torrent_present():
            with self.get(self.iso_info['torrent_link']) as r:
                with open(self.torrent_path, 'wb') as f:
                    f.write(r.content)
            with open(self.torrent_path, 'rb') as f:
                self.bitclient.download_from_file(f, savepath=self.cwd)
        else:
            if self.torrent_done():
                self.verify_file_hash()

    def bitclient_status(self):
        try:
            assert(self.bitclient.qbittorrent_version)
            assert(self.bitclient.api_version)
        except:
            raise BittclientUnreachable

    def torrent_present(self):
        self.bitclient_status()
        try:
            self.torrent_info = self.bitclient.get_torrent(self.iso_info['info_hash'])
        except:
            # assume 404 error
            return False
        for k in self.expected_torrent_fields:
            if not k in self.torrent_info:
                raise MissingField(k)
        return True

    def torrent_done(self):
        if not self.torrent_present():
            raise NoTorrentHash
        # '-1' if not complete, otherwise epoch time
        if int(self.torrent_info['completion_date']) >= 0:
            return True
        return False

    def poll_download(self):
        with tqdm(total=self.torrent_info['pieces_num']) as pbar:
            while True:
                try:
                    if self.torrent_done():
                        pbar.n = self.torrent_info['pieces_have']
                        pbar.refresh()
                        pbar.close()
                        return
                    # 8640000 == infinite eta
                    if self.torrent_info['eta'] == 8640000:
                        pbar.close()
                        raise DownloadStalled
                    pbar.n = self.torrent_info['pieces_have']
                    pbar.refresh()
                except Exception as e:
                    logger.exception(e)
                    sys.exit()
                sleep(self.poll_interval)

    def verify_file_hash(self):
        if not self.iso_path.exists():
            raise ISONotFound
        logger.debug('Checking hash')
        chunk = 65536  # 64kB
        hash_method = self.hashes[self.hash]
        with open(self.iso_path, 'rb') as f:
            while True:
                data = f.read(chunk)
                if not data: break
                hash_method.update(data)
        if not hash_method.hexdigest() == self.iso_info[self.hash]:
            raise ISOFailedHash

    def save_iso_info(self):
        logger.debug('save iso info')
        with open(self.iso_info_path, 'w') as f:
            # datetime object will default to string
            f.write(json.dumps(self.iso_info, default=str))

    def load_last_iso_info(self):
        logger.debug('load iso info')
        self.last_iso_info = dict()
        if self.iso_info_path.exists():
            with open(self.iso_info_path, 'r') as f:
                self.last_iso_info = json.loads(f.read())
                self.last_iso_info['release_date'] = datetime.strptime(self.last_iso_info['release_date'], '%Y-%m-%d %H:%M:%S')


class latestArch(latestISO):
    def __init__(self):
        super().__init__()
        self.arch_url = 'https://www.archlinux.org'
        self.releases_endpoint = '/releng/releases'
        self.releases_url = self.arch_url + self.releases_endpoint
        self.iso_info_path = self.cwd / '.arch-iso'
        self.torrent_path = self.cwd / 'arch.torrent'
        self.hash = 'sha1'
        self.expected_iso_fields = ('release_date', 'kernel_version', self.hash,
                                    'file_name', 'info_hash', 'torrent_link')

    def get_release_url(self):
        logger.debug('find page for latest release')
        r = self.get(self.releases_url)
        page = html.fromstring(r.text)
        latest_release_endpoint = page.xpath('//*[@id="release-table"]/tbody/tr[1]/td[3]/a/@href')[0]
        self.latest_release_url = self.arch_url + latest_release_endpoint

    def get_iso_info(self):
        self.get_release_url()
        logger.debug('scraping iso info')
        r = self.get(self.latest_release_url)
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
        self.map_iso_links()
        self.sanitize_iso_info()

    def map_iso_links(self):
        logger.debug('translate links to keyed values')
        for link in self.iso_links:
            if 'magnet' in link.lower():
                self.iso_info['magnet_link'] = link
            elif 'torrent' in link.lower():
                self.iso_info['torrent_link'] = self.arch_url + link

    def sanitize_iso_info(self):
        logger.debug('sanitize iso info')
        for k in self.expected_iso_fields:
            if not k in self.iso_info:
                raise MissingField(k)
        self.iso_info = {k: v for k, v in self.iso_info.items() if k in self.expected_iso_fields}

        # Convert value
        self.iso_info['release_date'] = datetime.strptime(self.iso_info['release_date'], '%Y-%m-%d')
        # self.iso_info['available'] = bool(util.strtobool(self.iso_info['available']))

latestArch().get_latest()

# TODO:
# log to file
# log rotation
# redo debug out
# redo info out
# redo/add warn out?
# account for checking/init time at start beyond sleep, use bitclient
# check exit codes
# document methods
# unit tests
# load from config
# cli
# see if there is a better way to do exceptions
# get_torrent should also try to force start
# only print progress bar if using stdout to ttyl / add progress flag
# parse torrent files for as much info as possible
# expand for Fedora ISO
# expand for Alpine ISO
# break into files
# switch/add aria2 for bitclient/downloader

