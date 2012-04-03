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

import time
from datetime import datetime
import json
import re
import urllib
import urllib2
import urlparse
import warnings
from xml.dom import minidom

try:
    import oauth2
except ImportError:
    oauth2 = None
import requests

from vidscraper.exceptions import VideoDeleted
from vidscraper.suites import BaseSuite, registry, SuiteMethod, OEmbedMethod
from vidscraper.utils.feedparser import struct_time_to_datetime
from vidscraper.utils.http import open_url_while_lying_about_agent
from vidscraper.videos import VideoFeed


class VimeoApiMethod(SuiteMethod):
    fields = set(['link', 'title', 'description', 'tags', 'guid',
                  'publish_datetime', 'thumbnail_url', 'user', 'user_url',
                  'flash_enclosure_url', 'embed_code'])

    def get_url(self, video):
        video_id = video.suite.video_regex.match(video.url).group('video_id')
        return u"http://vimeo.com/api/v2/video/%s.json" % video_id

    def process(self, response):
        parsed = json.loads(response.text)[0]
        return VimeoSuite.api_video_to_data(parsed)


class VimeoScrapeMethod(SuiteMethod):
    fields = set(['link', 'title', 'user', 'user_url', 'thumbnail_url',
                  'embed_code', 'file_url', 'file_url_mimetype',
                  'file_url_expires'])

    def get_url(self, video):
        video_id = video.suite.video_regex.match(video.url).group('video_id')
        return u"http://www.vimeo.com/moogaloop/load/clip:%s" % video_id

    def process(self, response):
        doc = minidom.parseString(response.text)
        error_id = doc.getElementsByTagName('error_id').item(0)
        if (error_id is not None and
            error_id.firstChild.data == 'embed_blocked'):
            return {
                'is_embeddable': False
                }
        xml_data = {}
        for key in ('url', 'caption', 'thumbnail', 'uploader_url',
                    'uploader_display_name', 'isHD', 'embed_code',
                    'request_signature', 'request_signature_expires',
                    'nodeId'):
            item = doc.getElementsByTagName(key).item(0)
            str_data = item.firstChild.data
            if isinstance(str_data, unicode):
                xml_data[key] = str_data # actually Unicode
            else:
                xml_data[key] = str_data.decode('utf8')

        data = {
            'link': xml_data['url'],
            'user': xml_data['uploader_display_name'],
            'user_url': xml_data['uploader_url'],
            'title': xml_data['caption'],
            'thumbnail_url': xml_data['thumbnail'],
            'embed_code': xml_data['embed_code'],
            'file_url_expires': struct_time_to_datetime(time.gmtime(
                    int(xml_data['request_signature_expires']))),
            'file_url_mimetype': u'video/x-flv',
            }
        base_file_url = (
            'http://www.vimeo.com/moogaloop/play/clip:%(nodeId)s/'
            '%(request_signature)s/%(request_signature_expires)s'
            '/?q=' % xml_data)
        if xml_data['isHD'] == '1':
            data['file_url'] = base_file_url + 'hd'
        else:
            data['file_url'] = base_file_url + 'sd'

        return data


class VimeoFeed(VideoFeed):
    """
    Vimeo supports the following feeds for videos through its "Simple API":

    * http://vimeo.com/api/v2/album/<album_id>/videos.json
    * http://vimeo.com/api/v2/channel/<channelname>/videos.json
    * http://vimeo.com/api/v2/group/<groupname>/videos.json

    as well as the following "user video" feeds:

    http://vimeo.com/api/v2/<username>/videos.json
        Videos created by the user

    http://vimeo.com/api/v2/<username>/likes.json
        Videos the user likes

    http://vimeo.com/api/v2/<username>/appears_in.json
        Videos that the user appears in

    http://vimeo.com/api/v2/<username>/all_videos.json
        Videos that the user appears in and created

    http://vimeo.com/api/v2/<username>/subscriptions.json
        Videos the user is subscribed to

    Vimeo also provides an advanced API which provides the above feeds through
    the following methods:

    * albums.getVideos
    * channels.getVideos
    * groups.getVideos
    * videos.getUploaded
    * videos.getLiked
    * videos.getAppearsIn
    * videos.getAll
    * videos.getSubscriptions

    The simple API only provides up to 60 videos in each feed; the advanced
    API provides all the videos, but requires a key and a secret for OAuth. So
    we prefer the advanced, but fall back to the simple if the key and secret
    are missing.

    """
    path_re = re.compile(r'(?:^/album/(?P<album_id>\d+)(?:/format:\w+)?/?)$|'
                         r'(?:^/channels/(?P<channel_id>\w+)(?:/videos/rss)?/?)$|'
                         r'(?:^/groups/(?P<group_id>\w+)(?:/videos(?:/sort:\w+(?:/format:\w+)?)?)?/?)$|'
                         r'(?:^/(?P<user_id>\w+)(?:/(?P<request_type>videos|likes)(?:/sort:\w+(?:/format:\w+)?|/rss)?)?/?)$')

    api_re = re.compile(r'(?:^/api/v2/(?:album/(?P<album_id>\d+)|channel/(?P<channel_id>\w+)|group/(?P<group_id>\w+)|(?P<user_id>\w+))/(?P<request_type>\w+).(?P<output_type>json|php|xml)))')

    simple_url_format = "http://vimeo.com/api/v2/{api_path}/{request_type}.json?page={page}"
    advanced_url_format = ("http://vimeo.com/api/rest/v2?format=json&full_response=1&sort=newest&"
                           "method=vimeo.{method}&per_page=50&page={page}&{method_params}")

    @property
    def page_url_format(self):
        if self.is_simple():
            return self.simple_url_format
        return self.advanced_url_format

    @property
    def per_page(self):
        if self.is_simple():
            return 20
        return 50

    def __init__(self, *args, **kwargs):
        super(VimeoFeed, self).__init__(*args, **kwargs)
        if self.is_simple():
            warnings.warn("Without an API key and secret, only the first 60 "
                          "results can be retrieved for this feed.")

    def is_simple(self):
        return ('vimeo_key' in self.api_keys and
                'vimeo_secret' in self.api_keys)

    def get_url_data(self, url):
        parsed_url = urlparse.urlsplit(url)
        if parsed_url.scheme not in ('http', 'https'):
            raise UnhandledURL

        if parsed_url.netloc not in ('vimeo.com', 'www.vimeo.com'):
            raise UnhandledURL

        match = self.path_re.match(parsed_url.path)
        if not match:
            # Only use the api regex as a fallback - less likely to see it.
            match = self.api_re.match(parsed_url.path)
            if not match:
                raise UnhandledURL

        return match.groupdict()

    def get_simple_api_path(self, data):
        if data['user_id']:
            request_type = (data['request_type'] if data['request_type']
                            in ('videos', 'likes', 'appears_in',
                                'all_videos', 'subscriptions')
                            else 'videos')
            api_path = data['user_id']
        else:
            request_type = 'videos'
            if data['album_id']:
                api_path = "album/{0}".format(data['album_id'])
            elif data['channel_id']:
                api_path = "channel/{0}".format(data['channel_id'])
            elif data['group_id']:
                api_path = "group/{0}".format(data['group_id'])
            else:
                raise ValueError

    def get_page_url_data(self, *args, **kwargs):
        data = super(VimeoFeed, self).get_page_url_data(*args, **kwargs)
        if self.is_simple():
            if data['user_id']:
                request_type = (data['request_type'] if data['request_type']
                                in ('videos', 'likes', 'appears_in',
                                    'all_videos', 'subscriptions')
                                else 'videos')
            else:
                request_type = 'videos'
            data.update({
                'api_path': self.get_simple_api_path(data),
                'request_type': request_type
            })
        else:
            if data['user_id']:
                method_params = "user_id={0}".format(data['user_id'])
                request_type = data['request_type']
                if request_type == 'likes':
                    method = 'getLiked'
                elif request_type == 'appears_in':
                    method = 'getAppearsIn'
                elif request_type == 'all_videos':
                    method = 'getAll'
                elif request_type == 'subscriptions':
                    method = 'getSubscriptions'
                else:
                    # This covers 'videos' and any invalid or unknown methods.
                    method = 'getUploaded'
                method = "videos.{0}".format(method)
            elif data['album_id']:
                method_params = "album_id={0}".format(data['album_id'])
                method = "albums.getVideos"
            elif data['channel_id']:
                method_params = "channel_id={0}".format(data['channel_id'])
                method = "channels.getVideos"
            elif data['group_id']:
                method_params = "group_id={0}".format(data['group_id'])
                method = "groups.getVideos"
            else:
                raise ValueError
            data.update({
                'method_params': method_params,
                'method': method
            })
        return data

    def get_page(self, start_index, max_results):
        url = self.get_page_url(start_index, max_results)
        if self.is_simple():
            # Do we still need to fake the agent?
            response = requests.get(url, timeout=5).text
        else:
            if oauth2 is None:
                raise ImportError("OAuth2 library must be installed.")
            consumer = oauth2.Consumer(self.api_keys['vimeo_key'],
                                       self.api_keys['vimeo_secret'])
            client = oauth2.Client(consumer)
            response = client.request(url)
        return response

    def load(self):
        """
        Vimeo returns data about feeds from a different part of the API, so we
        handle loading differently than for default feeds.

        """
        if not self._loaded:
            url_data = {
                'api_path': self.get_simple_api_path(self.url_data),
                'request_type': 'info',

                # Have a page so we can just use the same url_format string.
                # Vimeo will just ignore this.
                'page': 1
            }
            url = self.simple_url_format.format(**url_data)
            response = requests.get(url)
            data = self.data_from_response(response)
            if self._response is None:
                self._next_page()
            if self.is_simple():
                data['etag'] = self._response.headers['etag']
            else:
                # Advanced api doesn't have etags, but it does have explicit
                # video counts.
                response = json.loads(self._response[1])
                if 'videos' not in response:
                    video_count = 0
                else:
                    video_count = int(response['videos']['total'])
                data.update({
                    'video_count': video_count,
                })
            self._apply(data)
            self._loaded = True

    def data_from_response(self, response):
        """
        The response here is expected to be an *info* response for the feed,
        which always uses the simple api, since there is no api for album
        info.

        """
        response = json.loads(response.text)
        data = {}
        # User is very different
        if self.url_data['user_id']:
            display_name = response['display_name']
            request_type = (self.url_data['request_type'] if
                            self.url_data['request_type'] in
                            ('videos', 'likes', 'appears_in',
                             'all_videos', 'subscriptions')
                            else 'videos')
            count = None
            webpage = response['profile_url']
            if request_type == 'videos':
                title = "{0}'s videos".format(display_name)
                count = response['total_videos_uploaded']
                webpage = response['videos_url']
            elif request_type == 'likes':
                title = 'Videos {0} likes'.format(display_name)
                count = response['total_videos_liked']
                webpage = "{0}/likes".format(webpage)
            elif request_type == 'appears_in':
                title = "Videos {0} appears in".format(display_name)
                count = response['total_videos_appears_in']
            elif request_type == 'all_videos':
                title = "{0}'s videos and videos {0} appears in".format(
                            display_name)
            elif request_type == 'subscriptions':
                title = "Videos {0} is subscribed to".format(display_name)
            data.update({
                'title': title,
                'video_count': count,
                'description': response['bio'],
                'webpage': webpage,
                'thumbnail_url': response['portrait_huge']
            })
        else:
            # It's a channel, album, or group feed.

            # Title
            if self.url_data['album_id']:
                title = response['title']
            else:
                title = response['name']

            # Albums and groups have a small thumbnail (~100x75). Groups and
            # channels have a large logo, as well, but it seems like a paid
            # feature - some groups/channels have a blank value there.
            thumbnail_url = response.get('logo')
            if not thumbnail_url and 'thumbnail' in response:
                thumbnail_url = response['thumbnail']

            data.update({
                'title': title,
                'video_count': response['total_videos'],
                'description': response['description'],
                'webpage': response['url'],
                'thumbnail_url': thumbnail_url
            })

        return data

    def get_response_items(self, response):
        if self.is_simple():
            if response.status_code == 403:
                return []
            return json.loads(response.text)
        response = json.loads(response[1])
        if 'videos' not in response:
            return []
        return response['videos']['video']

    def get_item_data(self, item):
        return VimeoSuite.api_video_to_data(entry)


class VimeoSuite(BaseSuite):
    """
    Suite for vimeo.com. Currently supports their oembed api and simple api. No
    API key is required for this level of access.

    """
    video_regex = r'https?://([^/]+\.)?vimeo.com/(?P<video_id>\d+)'
    api_regex = re.compile((r'http://(?:www\.)?vimeo.com/api/v./'
                            r'(?:(?P<collection>channel|group)s/)?'
                            r'(?P<name>\w+)'
                            r'(?:/(?P<type>videos|likes))\.json'))
    _tag_re = re.compile(r'>([\w ]+)</a>')


    methods = (OEmbedMethod(u"http://vimeo.com/api/oembed.json"),
               VimeoApiMethod(), VimeoScrapeMethod())
    feed_class = VimeoFeed

    @classmethod
    def api_video_embed_code(cls, api_video):
        return u"""<iframe src="http://player.vimeo.com/video/%s" \
width="320" height="240" frameborder="0" webkitAllowFullScreen \
allowFullScreen></iframe>""" % api_video['id']

    @classmethod
    def api_video_flash_enclosure(cls, api_video):
        return u'http://vimeo.com/moogaloop.swf?clip_id=%s' % api_video['id']

    @classmethod
    def api_video_to_data(cls, api_video):
        """
        Takes a video dictionary from a vimeo API response and returns a
        dictionary mapping field names to values.

        """
        data = {
            'title': api_video['title'],
            'link': api_video['url'],
            'description': api_video['description'],
            'thumbnail_url': api_video['thumbnail_medium'],
            'user': api_video['user_name'],
            'user_url': api_video['user_url'],
            'publish_datetime': datetime.strptime(api_video['upload_date'],
                                             '%Y-%m-%d %H:%M:%S'),
            'tags': [tag for tag in api_video['tags'].split(', ') if tag],
            'flash_enclosure_url': cls.api_video_flash_enclosure(api_video),
            'embed_code': cls.api_video_embed_code(api_video),
            'guid': 'tag:vimeo,%s:clip%i' % (api_video['upload_date'][:10],
                                             api_video['id'])
        }
        return data


    def _get_user_api_url(self, user, type):
        return 'http://vimeo.com/api/v2/%s/%s.json' % (user, type)

    def get_search_url(self, search, extra_params=None):
        if search.api_keys is None or not search.api_keys.get('vimeo_key'):
            raise NotImplementedError("API Key is missing.")
        params = {
            'format': 'json',
            'full_response': '1',
            'method': 'vimeo.videos.search',
            'query': search.query,
        }
        params['api_key'] = search.api_keys['vimeo_key']
        if search.order_by == 'relevant':
            params['sort'] = 'relevant'
        elif search.order_by == 'latest':
            params['sort'] = 'newest'
        if extra_params is not None:
            params.update(extra_params)
        return "http://vimeo.com/api/rest/v2/?%s" % urllib.urlencode(params)

    def get_next_search_page_url(self, search, search_response):
        total = self.get_search_total_results(search, search_response)
        page = int(search_response['videos']['page'])
        per_page = int(search_response['videos']['perpage'])
        if page * per_page > total:
            return None
        extra_params = {'page': page + 1}
        return self.get_search_url(search,
                                   extra_params=extra_params)

    def get_search_response(self, search, search_url):
        if oauth2 is None:
            raise ImportError("OAuth2 library must be installed.")
        api_key = (search.api_keys.get('vimeo_key')
                   if search.api_keys else None)
        api_secret = (search.api_keys.get('vimeo_secret')
                      if search.api_keys else None)
        if api_key is None or api_secret is None:
            raise NotImplementedError("API Key and Secret missing.")
        consumer = oauth2.Consumer(api_key, api_secret)
        client = oauth2.Client(consumer)
        request = client.request(search_url)
        return json.loads(request[1])

    def get_search_total_results(self, search, search_response):
        if 'videos' not in search_response:
            return 0
        return int(search_response['videos']['total'])

    def get_search_results(self, search, search_response):
        if 'videos' not in search_response:
            return []
        # Vimeo only includes the 'video' key if there are actually videos on
        # the page.
        if int(search_response['videos']['on_this_page']) > 0:
            return search_response['videos']['video']
        return []

    def parse_search_result(self, search, result):
        # TODO: results have an embed_privacy key. What is this? Should
        # vidscraper return that information? Doesn't youtube have something
        # similar?
        video_id = result['id']
        if not result['upload_date']:
            # deleted video
            link = [u['_content'] for u in result['urls']['url']
                    if u['type'] == 'video'][0]
            raise VideoDeleted(link)
        data = {
            'title': result['title'],
            'link': [u['_content'] for u in result['urls']['url']
                    if u['type'] == 'video'][0],
            'description': result['description'],
            'thumbnail_url': result['thumbnails']['thumbnail'][1]['_content'],
            'user': result['owner']['realname'],
            'user_url': result['owner']['profileurl'],
            'publish_datetime': datetime.strptime(result['upload_date'],
                                             '%Y-%m-%d %H:%M:%S'),
            'tags': [t['_content']
                            for t in result.get('tags', {}).get('tag', [])],
            'flash_enclosure_url': VimeoSuite.api_video_flash_enclosure(result),
            'embed_code': VimeoSuite.api_video_embed_code(result)
        }
        return data
registry.register(VimeoSuite)
