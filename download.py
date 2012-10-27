#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import (unicode_literals, division, absolute_import,
                        print_function)

__license__   = 'GPL v3'
__copyright__ = '2011, Grant Drake <grant.drake@gmail.com>'
__docformat__ = 'restructuredtext en'

import socket

from lxml.html import fromstring, tostring
from calibre import browser
from calibre.utils.cleantext import clean_ascii_chars

class GoodreadsPagesWorker():
    '''
    Get page count from Goodreads book page
    '''
    def __init__(self, goodreads_id, timeout=20):
        self.goodreads_id = goodreads_id
        self.timeout = timeout
        self.page_count = None
        self.run()

    def run(self):
        try:
            self.url = 'http://www.goodreads.com/book/show/%s'%self.goodreads_id
            self._get_details()
        except:
            print('get_details failed for url: %r'%self.url)

    def _get_details(self):
        try:
            print('Goodreads book url: %r'%self.url)
            br = browser()
            raw = br.open_novisit(self.url, timeout=self.timeout).read().strip()
        except Exception as e:
            if callable(getattr(e, 'getcode', None)) and \
                    e.getcode() == 404:
                print('URL malformed: %r'%self.url)
                return
            attr = getattr(e, 'args', [None])
            attr = attr if attr else [None]
            if isinstance(attr[0], socket.timeout):
                msg = 'Goodreads timed out. Try again later.'
                print(msg)
            else:
                msg = 'Failed to make details query: %r'%self.url
                print(msg)
            return

        raw = raw.decode('utf-8', errors='replace')
        #open('E:\\t.html', 'wb').write(raw)

        if '<title>404 - ' in raw:
            print('URL malformed: %r'%self.url)
            return

        try:
            root = fromstring(clean_ascii_chars(raw))
        except:
            msg = 'Failed to parse goodreads details page: %r'%self.url
            print(msg)
            return

        errmsg = root.xpath('//*[@id="errorMessage"]')
        if errmsg:
            msg = 'Failed to parse goodreads details page: %r'%self.url
            msg += tostring(errmsg, method='text', encoding=unicode).strip()
            print(msg)
            return

        self._parse_page_count(root)

    def _parse_page_count(self, root):
        try:
            # <div class="row"><span itemprop="numberOfPages">412 pages</span></div>
            pages = root.xpath('//div[@id="details"]/div[@class="row"]/span[@itemprop="numberOfPages"]/text()')
            if pages:
                pages_text = ''.join(pages).strip().partition(' ')
                self.page_count = int(pages_text[0])
        except:
            print('Error parsing page count for url: %r'%self.url)
