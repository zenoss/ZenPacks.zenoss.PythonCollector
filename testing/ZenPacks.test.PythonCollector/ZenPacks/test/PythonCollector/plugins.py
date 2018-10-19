##############################################################################
#
# Copyright (C) Zenoss, Inc. 2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""PythonDataSourcePlugin implementations used for testing."""

import datetime
import logging
import math
import time

from twisted.internet import defer, threads
from twisted.internet.task import LoopingCall

from Products.DataCollector.plugins.DataMaps import ObjectMap

from ZenPacks.zenoss.PythonCollector import twisted_utils
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import PythonDataSourcePlugin

SINE_LENGTH = 7200.0

LOG = logging.getLogger('zen.PythonCollector')


def radians_from_timestamp(timestamp):
    return (math.pi * 2) * ((timestamp % SINE_LENGTH) / SINE_LENGTH)


class BaseTestPlugin(PythonDataSourcePlugin):

    """Abstract base class for test plugins."""

    offset = (SINE_LENGTH / 11)

    def __init__(self, config):
        super(BaseTestPlugin, self).__init__(config)
        self.config = config
        self.datasource = config.datasources[0].datasource
        self.cycletime = config.datasources[0].cycletime

    def get_data(self):
        data = self.new_data()
        for datasource in self.config.datasources:
            data["events"].append({
                "component": datasource.component,
                "severity": 2,
                "summary": "test {} 1".format(datasource.datasource)})

            metric_name = "{}_sin".format(datasource.datasource)
            radians = radians_from_timestamp(time.time() + self.offset)
            value = math.sin(radians) * 50 + 50
            data["values"][datasource.component][metric_name] = value

        return data


class PerDeviceTestPlugin(BaseTestPlugin):

    """Abstract base for plugins that collect once per device."""

    @classmethod
    def config_key(cls, datasource, context):
        return (
            context.device().id,
            datasource.getCycleTime(context),
            datasource.id)


class PerComponentTestPlugin(BaseTestPlugin):

    """Abstract base for plugins that collect once per component."""

    @classmethod
    def config_key(cls, datasource, context):
        return (
            context.device().id,
            datasource.getCycleTime(context),
            datasource.id,
            context.id)


class TestSleepMainPlugin(PerDeviceTestPlugin):

    """Plugin that sleeps for just shy of cycletime on the main thread."""

    offset = (SINE_LENGTH / 11) * 1

    def collect(self, config):
        time.sleep(self.cycletime - 1)
        return defer.succeed(self.get_data())


class TestOversleepMainPlugin(PerDeviceTestPlugin):

    """Plugin that sleeps for double cycletime on the main thread."""

    offset = (SINE_LENGTH / 11) * 2

    def collect(self, config):
        time.sleep(self.cycletime * 2)
        return defer.succeed(self.get_data())


class TestSleepThreadPlugin(PerDeviceTestPlugin):

    """Plugin that sleeps for just shy of cycletime in a thread."""

    offset = (SINE_LENGTH / 11) * 3

    @defer.inlineCallbacks
    def collect(self, config):
        def inner():
            time.sleep(self.cycletime - 1)
            return self.get_data()

        r = yield threads.deferToThread(inner)
        defer.returnValue(r)


class TestOversleepThreadPlugin(PerDeviceTestPlugin):

    """Plugin that sleeps for double cycletime in a thread."""

    offset = (SINE_LENGTH / 11) * 4

    @defer.inlineCallbacks
    def collect(self, config):
        def inner():
            time.sleep(self.cycletime * 2)
            return self.get_data()

        r = yield threads.deferToThread(inner)
        defer.returnValue(r)


class TestSleepAsyncPlugin(PerDeviceTestPlugin):

    """Plugin that sleeps asynchronously for just shy of cycletime."""

    offset = (SINE_LENGTH / 11) * 5

    @defer.inlineCallbacks
    def collect(self, config):
        yield twisted_utils.sleep(self.cycletime - 1)
        defer.returnValue(self.get_data())


class TestOversleepAsyncPlugin(PerDeviceTestPlugin):

    """Plugin that sleeps asynchronously double cycletime."""

    offset = (SINE_LENGTH / 11) * 6

    @defer.inlineCallbacks
    def collect(self, config):
        yield twisted_utils.sleep(self.cycletime * 2)
        defer.returnValue(self.get_data())


class TestDirtnapAsyncPerDevicePlugin(PerDeviceTestPlugin):

    """Plugin that stays in the RUNNING state effectively forever.

    Split into a single task per device.

    """

    offset = (SINE_LENGTH / 11) * 7

    @defer.inlineCallbacks
    def collect(self, config):
        yield twisted_utils.sleep(self.cycletime * 4)
        defer.returnValue(self.get_data())


class TestDirtnapAsyncPerComponentPlugin(PerComponentTestPlugin):
    """Plugin that stays in the RUNNING state effectively forever.

    Split into a single task per component.

    """

    offset = (SINE_LENGTH / 11) * 8

    @defer.inlineCallbacks
    def collect(self, config):
        yield twisted_utils.sleep(self.cycletime * 4)
        defer.returnValue(self.get_data())


class TestPeriodicTimeoutPerDevicePlugin(PerDeviceTestPlugin):
    """Plugin that times out if (minutes / 10 % 2).

    Useful for simulating a plugin that only times out sometimes.

    """

    offset = (SINE_LENGTH / 11) * 9

    @defer.inlineCallbacks
    def collect(self, config):
        now = datetime.datetime.now()
        should_timeout = bool((now.minute / 10) % 2)
        yield twisted_utils.sleep(
            self.cycletime * 4 if should_timeout else self.cycletime / 2)

        defer.returnValue(self.get_data())


class TestPeriodicTimeoutPerComponentPlugin(PerComponentTestPlugin):
    """Plugin that times out if (minutes / 10 % 2).

    Useful for simulating a plugin that only times out sometimes.

    """

    offset = (SINE_LENGTH / 11) * 11

    @defer.inlineCallbacks
    def collect(self, config):
        now = datetime.datetime.now()
        should_timeout = bool((now.minute / 10) % 2)
        yield twisted_utils.sleep(
            self.cycletime * 4 if should_timeout else self.cycletime / 2)

        defer.returnValue(self.get_data())


class TestReturnedDataPlugin(PerDeviceTestPlugin):
    """Plugin that returns all supported data types from collect()."""

    def collect(self, config):
        data = self.new_data()
        for datasource in self.config.datasources:
            data["events"].append({
                "component": datasource.component,
                "severity": 2,
                "summary": "TestReturnedDataPlugin {}".format(
                    datasource.datasource)})

            for point in datasource.points:
                data["values"][datasource.component][point.dpName] = 88.0

            data["metrics"].append(
                self.new_metric(
                    name="adhoc.{}".format(datasource.datasource),
                    value=77.0,
                    tags={
                        "type": "adhoc",
                        "plugin": "TestReturnedDataPlugin",
                        "device": datasource.device,
                        "component": datasource.component}))

            data["maps"].append(
                ObjectMap(
                    data={
                        datasource.datasource: 88.0}))

            data["interval"] = datasource.cycletime

        return defer.succeed(data)


class TestPublishedDataPlugin(PerDeviceTestPlugin):
    """Plugin that publishes all supported data types."""

    def __init__(self, config):
        super(TestPublishedDataPlugin, self).__init__(config)
        self.loop = LoopingCall(self.onLoop, config)
        self.loop.start(10, now=False)

    def cleanup(self, config):
        self.loop.stop()

    @defer.inlineCallbacks
    def onLoop(self, config):
        for datasource in config.datasources:
            yield self.publishEvents([{
                "component": datasource.component,
                "severity": 2,
                "summary": "TestReturnedDataPlugin {}".format(
                    datasource.datasource)}])

            for point in datasource.points:
                yield self.publishValues({
                    datasource.component: {
                        point.dpName: 88.0}})

            yield self.publishMetrics([
                self.new_metric(
                    name="adhoc.{}".format(datasource.datasource),
                    value=77.0,
                    tags={
                        "type": "adhoc",
                        "plugin": "TestReturnedDataPlugin",
                        "device": datasource.device,
                        "component": datasource.component})])

            yield self.publishMaps([
                ObjectMap(data={datasource.datasource: 88.0})])

            self.changeInterval(datasource.cycletime)
