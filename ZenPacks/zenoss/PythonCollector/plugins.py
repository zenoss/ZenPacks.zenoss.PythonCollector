##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""PythonDataSourcePlugin implementations used for testing."""

import logging
LOG = logging.getLogger('zen.PythonCollector')

import math
import time

from twisted.internet import defer, reactor, threads

from .datasources.PythonDataSource import PythonDataSourcePlugin

SINE_LENGTH = 7200


def radians_from_timestamp(timestamp):
    return (math.pi * 2) * ((timestamp % SINE_LENGTH) / SINE_LENGTH)


class BaseTestPlugin(PythonDataSourcePlugin):

    """Abstract base class for test plugins."""

    offset = (SINE_LENGTH / 6)

    @classmethod
    def config_key(cls, datasource, context):
        return (
            context.device().id,
            datasource.getCycleTime(context),
            datasource.id,
            )

    def __init__(self, config):
        self.datasource = config.datasources[0].datasource
        self.cycletime = config.datasources[0].cycletime

    def get_data(self):
        ds = self.datasource

        data = self.new_data()
        data['events'].append({
            'severity': 2,
            'summary': 'test {} 1'.format(ds)})

        now = time.time()
        radians = radians_from_timestamp(now + self.offset)
        data['values'][None]['{}_sin'.format(ds)] = math.sin(radians) * 50 + 50

        return data


class TestSleepMainPlugin(BaseTestPlugin):

    """Plugin that sleeps for just shy of cycletime on the main thread."""

    offset = (SINE_LENGTH / 6) * 1

    def collect(self, config):
        LOG.info("%s.collect()", self.datasource)
        time.sleep(self.cycletime - 1)
        return defer.succeed(self.get_data())


class TestOversleepMainPlugin(BaseTestPlugin):

    """Plugin that sleeps for double cycletime on the main thread."""

    offset = (SINE_LENGTH / 6) * 2

    def collect(self, config):
        LOG.info("%s.collect()", self.datasource)
        time.sleep(self.cycletime * 2)
        return defer.succeed(self.get_data())


class TestSleepThreadPlugin(BaseTestPlugin):

    """Plugin that sleeps for just shy of cycletime in a thread."""

    offset = (SINE_LENGTH / 6) * 3

    @defer.inlineCallbacks
    def collect(self, config):
        LOG.info("%s.collect()", self.datasource)

        def inner():
            time.sleep(self.cycletime - 1)
            return self.get_data()

        r = yield threads.deferToThread(inner)
        defer.returnValue(r)


class TestOversleepThreadPlugin(BaseTestPlugin):

    """Plugin that sleeps for double cycletime in a thread."""

    offset = (SINE_LENGTH / 6) * 4

    @defer.inlineCallbacks
    def collect(self, config):
        LOG.info("%s.collect()", self.datasource)

        def inner():
            time.sleep(self.cycletime * 2)
            return self.get_data()

        r = yield threads.deferToThread(inner)
        defer.returnValue(r)


class TestSleepAsyncPlugin(BaseTestPlugin):

    """Plugin that sleeps asynchronously for just shy of cycletime."""

    offset = (SINE_LENGTH / 6) * 5

    @defer.inlineCallbacks
    def collect(self, config):
        LOG.info("%s.collect()", self.datasource)

        def async_sleep(seconds):
            d = defer.Deferred()
            reactor.callLater(seconds, d.callback, None)
            return d

        yield async_sleep(self.cycletime - 1)
        defer.returnValue(self.get_data())


class TestOversleepAsyncPlugin(BaseTestPlugin):

    """Plugin that sleeps asynchronously double cycletime."""

    offset = (SINE_LENGTH / 6) * 6

    @defer.inlineCallbacks
    def collect(self, config):
        LOG.info("%s.collect()", self.datasource)

        def async_sleep(seconds):
            d = defer.Deferred()
            reactor.callLater(seconds, d.callback, None)
            return d

        yield async_sleep(self.cycletime * 2)
        defer.returnValue(self.get_data())
