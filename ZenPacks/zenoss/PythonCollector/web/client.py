##############################################################################
#
# Copyright (C) Zenoss, Inc. 2016, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging
import os
import random
from twisted.internet import defer, reactor
from twisted.internet.error import DNSLookupError
from twisted.web import http, client as txwebclient
from urlparse import urlunparse
from .semaphores import getOverallDeferredSemaphore, getKeyedDeferredSemaphore

log = logging.getLogger('zen.python.web.client')


# Supports getPage functionality, but honors proxy environment variables
class ProxyWebClient(object):
    """web methods with proxy support."""

    def __init__(self, url, username=None, password=None, return_headers=False):
        # get scheme used by url
        scheme, host, port, path = self.url_parse(url)
        envname = '%s_proxy' % scheme
        self.use_proxy = False
        self.proxy_host = None
        self.proxy_port = None
        if envname in os.environ.keys():
            proxy = os.environ.get('%s_proxy' % scheme)
            if proxy:
                # using proxy server
                # host:port identifies a proxy server
                # url is the actual target
                self.use_proxy = True
                scheme, host, port, path = self.url_parse(proxy)
                self.proxy_host = host
                self.proxy_port = port
                self.username = username
                self.password = password
        else:
            self.host = host
            self.port = port
        self.path = url
        self.url = url
        self.return_headers = return_headers

    def url_parse(self, url, defaultPort=None):
        """
        Split the given URL into the scheme, host, port, and path.

        @type url: C{str}
        @param url: An URL to parse.

        @type defaultPort: C{int} or C{None}
        @param defaultPort: An alternate value to use as the port if the URL does
        not include one.

        @return: A four-tuple of the scheme, host, port, and path of the URL.  All
        of these are C{str} instances except for port, which is an C{int}.
        """
        url = url.strip()
        parsed = http.urlparse(url)
        scheme = parsed[0]
        path = urlunparse(('', '') + parsed[2:])

        if defaultPort is None:
            if scheme == 'https':
                defaultPort = 443
            else:
                defaultPort = 80

        host, port = parsed[1], defaultPort
        if ':' in host:
            host, port = host.split(':')
            try:
                port = int(port)
            except ValueError:
                port = defaultPort

        if path == '':
            path = '/'

        return scheme, host, port, path

    def get_page(self, contextFactory=None, description=None, *args, **kwargs):
        if description is None:
            description = self.url

        scheme, _, _, _ = self.url_parse(self.url)
        factory = txwebclient.HTTPClientFactory(self.url, *args, **kwargs)
        if scheme == 'https':
            from twisted.internet import ssl
            if contextFactory is None:
                contextFactory = ssl.ClientContextFactory()
            if self.use_proxy:
                reactor.connectSSL(self.proxy_host, self.proxy_port,
                                   factory, contextFactory)
            else:
                reactor.connectSSL(self.host, self.port,
                                   factory, contextFactory)
        else:
            if self.use_proxy:
                reactor.connectTCP(self.proxy_host, self.proxy_port, factory)
            else:
                reactor.connectTCP(self.host, self.port, factory)

        if self.return_headers:
            return factory.deferred.addCallback(
                lambda page: (page, factory.response_headers))
        else:
            return factory.deferred


@defer.inlineCallbacks
def getPage(url, return_headers=False, concurrent_key=None, concurrent_limit=None, max_retries=1, retry_status_codes=None, description=None, *args, **kwargs):
    '''
    Retrieve a URL, in a manner that is backwards compatible with
    twisted.web.client.getPage.   Unlike the default getPage, the http proxy
    environment variables are supported.

    - retry_status_codes (default: 400, 408, 500, 502, 503, 504)  - list of
           status codes that trigger a retry, if max_retries > 1.
    - max_retries (default: 1)  if one of the retry_status_codes is returned,
           retry the request up to this many times, with exponential backoff.
    - concurrent_limit (default: None): number of concurrent connections to allow
           for the specified concurrent_key.
    - concurrent_key (default: None): an identifier to use for managing
           concurrency.  For instance, this could be a hostname, or a tuple of
           identifiers.
    - return_headers (default: False)  If true, returns a tuple of
           (body, http response headers) rather than just the body content.
    '''

    if retry_status_codes is None:
        retry_status_codes = (
            400,  # Bad Request  (retry is unlikely to help, but it should be harmless to try)
            408,  # Request Timeout
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504)  # Gateway Timeout

    if description is None:
        description = url
    kwargs['description'] = description

    # Overall limit on concurrent queries
    overall_semaphore = getOverallDeferredSemaphore()

    # Limit concurrent queries based on concurrent_key and concurrent_limit as
    # well, if specified.
    keyed_semaphore = None
    if concurrent_key is not None and concurrent_limit is not None:
        keyed_semaphore = getKeyedDeferredSemaphore(concurrent_key, concurrent_limit)

    factory = ProxyWebClient(url, return_headers=return_headers)

    def sleep(secs):
        d = defer.Deferred()
        reactor.callLater(secs, d.callback, None)
        return d

    # Incremental backoff
    for retry in xrange(max_retries + 1):
        if retry > 0:
            delay = (random.random() * pow(4, retry)) / 10.0
            log.debug(
                '%s retry %s backoff is %s seconds',
                description, retry, delay)

            yield sleep(delay)

        try:
            def get_page():
                if keyed_semaphore:
                    return keyed_semaphore.run(factory.get_page, *args, **kwargs)
                else:
                    return factory.get_page(*args, **kwargs)

            result = yield overall_semaphore.run(get_page)

        except DNSLookupError, e:
            # These could be transient, so go ahead and retry.
            log.warning("DNS Error: %s" % str(e))
            continue

        except Exception, ex:
            code = getattr(ex, 'status', None)

            if code in retry_status_codes:
                if int(code) < 500:
                    # A 4xx error is pretty unusual, so log them, just in case.
                    log.warning("HTTP Error (%s): %s - retrying." % (url, str(ex)))

                continue

            # any other exception, we can't recover, so give up.
            raise

        else:
            defer.returnValue(result)
            break
