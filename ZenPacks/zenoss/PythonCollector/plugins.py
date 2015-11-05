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
LOG = logging.getLogger('zen.PythonCollect')

import time

from twisted.internet import defer, reactor, threads

from .datasources.PythonDataSource import PythonDataSourcePlugin


class BaseTestPlugin(PythonDataSourcePlugin):

    """Abstract base class for test plugins."""

    # Must be overridden in subclasses. Identifies tasks in logs.
    task_label = None

    @classmethod
    def config_key(cls, datasource, context):
        return (
            context.device().id,
            datasource.getCycleTime(context),
            cls.task_label,
            )


class TestSleepMainPlugin(BaseTestPlugin):

    """Plugin that sleeps on the main thread.

    You would never want to do this. This plugin exists to help test
    zenpython's ability to handle misbehaving plugins.

    """

    task_label = 'sleepMain'

    def collect(self, config):
        time.sleep(10)
        return defer.succeed(self.new_data())


class TestSleepThreadPlugin(BaseTestPlugin):

    """Plugin that sleeps in a thread.

    This is OK because collect immediately returns a deferred.

    """

    task_label = 'sleepThread'

    @defer.inlineCallbacks
    def collect(self, config):
        def inner():
            time.sleep(10)
            return self.new_data()

        r = yield threads.deferToThread(inner)
        defer.returnValue(r)


class TestSleepAsyncPlugin(BaseTestPlugin):

    """Plugin that sleeps asynchronously.

    This is OK because collect immediately returns a deferred.

    """

    task_label = 'sleepAsync'

    @defer.inlineCallbacks
    def collect(self, config):
        def async_sleep(seconds):
            d = defer.Deferred()
            reactor.callLater(seconds, d.callback, None)
            return d

        yield async_sleep(10)
        defer.returnValue(self.new_data())


class TestNonBlockingPlugin(BaseTestPlugin):

    """Plugin that returns a Deferred and doesn't block.

    This plugin's collect method should be run in the zenpython process.

    """

    task_label = 'non-blocking'
    is_blocking = False

    def collect(self, config):
        LOG.info("collecting TestNonBlockingPlugin")
        data = self.new_data()
        data['values'][None]['value1'] = 1.0
        data['values'][None]['value2'] = 2.0
        return defer.succeed(data)


class TestBlockingPlugin(BaseTestPlugin):

    """Plugin that blocks and returns data instead of a Deferred.

    This plugin's collect method should be run in a subprocess.

    """

    task_label = 'blocking'
    is_blocking = True

    def collect(self, config):
        LOG.info("collecting TestBlockingPlugin")
        data = self.new_data()
        data['values'][None]['value1'] = 1.0
        data['values'][None]['value2'] = 2.0
        return data
