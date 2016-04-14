##############################################################################
#
# Copyright (C) Zenoss, Inc. 2016, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging
import time
import zope.interface
from twisted.internet import defer
from Products.ZenCollector.interfaces import ICollectorPreferences
from Products.ZenUtils import Map

log = logging.getLogger('zen.python.web.semaphores')


DEFAULT_TWISTEDCONCURRENTHTTP = 512


class ExpiringSemaphoreMap(Map.Timed):
    def clean(self, now=None):
        "remove old values"

        if now is None:
            now = time.time()
        if self.lastClean + self.timeout > now:
            return
        for k, (v, t) in self.map.items():
            # only allow them to expire if they are not being used
            try:
                tokens = v.tokens
            except:
                log.warning('Invalid token count in map item: '+v)
                tokens = 0
            if t + self.timeout < now and tokens == 0:
                del self.map[k]
        self.lastClean = now


# Global semaphore tracking
OVERALL_SEMAPHORE = None
KEYED_SEMAPHORES = ExpiringSemaphoreMap({}, 15 * 60)


def getOverallDeferredSemaphore():
    global OVERALL_SEMAPHORE

    if OVERALL_SEMAPHORE is None:
        preferences = zope.component.queryUtility(
            ICollectorPreferences, 'zenpython')

        if preferences:
            OVERALL_SEMAPHORE = defer.DeferredSemaphore(preferences.options.twistedconcurrenthttp)
        else:
            # When we are running in a daemon other than zenpython, the preferences
            # value will not be available
            OVERALL_SEMAPHORE = defer.DeferredSemaphore(DEFAULT_TWISTEDCONCURRENTHTTP)

    return OVERALL_SEMAPHORE


def getKeyedDeferredSemaphore(key, limit):
    global KEYED_SEMAPHORES

    if key not in KEYED_SEMAPHORES:
        KEYED_SEMAPHORES[key] = defer.DeferredSemaphore(limit)
    semaphore = KEYED_SEMAPHORES[key]

    if semaphore.limit != limit:
        if limit >= semaphore.tokens:
            semaphore.limit = limit
            log.info("Unable to lower maximum parallel query limit for %s to %d ", key, limit)
        else:
            log.warning("Unable to lower maximum parallel query limit for %s to %d at this time (%d connections currently active)", key, limit, semaphore.tokens)

    return semaphore
