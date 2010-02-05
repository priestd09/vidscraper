# Miro - an RSS based video player application
# Copyright 2009 - Participatory Culture Foundation
# 
# This file is part of vidscraper.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
# 
# 1. Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright
#    notice, this list of conditions and the following disclaimer in the
#    documentation and/or other materials provided with the distribution.
# 
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES
# OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
# NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
# THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import re

from vidscraper.decorators import provide_shortmem, parse_url, returns_unicode
from vidscraper import errors
from vidscraper import util


@provide_shortmem
@parse_url
@returns_unicode
def scrape_title(url, shortmem=None):
    try:
        return shortmem['base_etree'].xpath(
            "//div[@id='video-title']/text()")[0]
    except IndexError:
        raise errors.FieldNotFound('Could not find the title field')


@provide_shortmem
@parse_url
@returns_unicode
def scrape_description(url, shortmem=None):
    try:
        details = shortmem['base_etree'].xpath(
            "//span[@id='video-description']")[0]
        return util.clean_description_html(util.lxml_inner_html(details))
    except IndexError:
        raise errors.FieldNotFound('Could not find the description field')


# This isn't returning a working url any more :\
@provide_shortmem
@parse_url
@returns_unicode
def scrape_file_url(url, shortmem=None):
    return shortmem['base_etree'].xpath(
        "//div[@id='download-instructions-detail']/a/@href")[0]

@provide_shortmem
def file_url_is_flaky(url, shortmem=None):
    return True

@provide_shortmem
@parse_url
@returns_unicode
def scrape_embed_code(url, shortmem=None):
    return shortmem['base_etree'].xpath(
        "//textarea[@id='embed-video-code']/text()")[0]

GOOGLE_VIDEO_REGEX = re.compile(
    r'^https?://video.google.com/videoplay')
SUITE = {
    'regex': GOOGLE_VIDEO_REGEX,
    'funcs': {
        'title': scrape_title,
        'description': scrape_description,
        'file_url_is_flaky': file_url_is_flaky,
        'file_url': scrape_file_url,
        'embed': scrape_embed_code}}
