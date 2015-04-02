##############################################################################
#
# Copyright (C) Zenoss, Inc. 2012, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""zenpython

Event and statistic collection daemon for python modules.

"""

import logging
log = logging.getLogger('zen.python')

import inspect
import re

import Globals

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks, returnValue
from twisted.spread import pb

import zope.interface

from Products.ZenCollector.daemon import CollectorDaemon
from Products.ZenHub.PBDaemon import HubDown

from Products.ZenCollector.interfaces import (
    ICollector,
    ICollectorPreferences,
    IDataService,
    IEventService,
    IScheduledTask,
    )

from Products.ZenCollector.tasks import (
    BaseTask,
    SimpleTaskFactory,
    SubConfigurationTaskSplitter,
    TaskStates,
    )

from Products.ZenEvents import ZenEventClasses
from Products.ZenUtils.Utils import unused

from ZenPacks.zenoss.PythonCollector.utils import get_dp_values
from ZenPacks.zenoss.PythonCollector.services.PythonConfig import PythonDataSourceConfig

unused(Globals)

pb.setUnjellyableForClass(PythonDataSourceConfig, PythonDataSourceConfig)


# allowStaleDatapoint isn't available in Zenoss 4.1.
if 'allowStaleDatapoint' in inspect.getargspec(CollectorDaemon.writeRRD).args:
    WRITERRD_ARGS = {'allowStaleDatapoint': False}
else:
    WRITERRD_ARGS = {}


class Preferences(object):
    zope.interface.implements(ICollectorPreferences)

    collectorName = 'zenpython'
    configurationService = 'ZenPacks.zenoss.PythonCollector.services.PythonConfig'
    cycleInterval = 5 * 60  # 5 minutes
    configCycleInterval = 60 * 60 * 12  # 12 hours
    maxTasks = None  # use system default

    def buildOptions(self, parser):
        parser.add_option(
            '--ignore',
            dest='ignorePlugins', default="",
            help="Python plugins to ignore. Takes a regular expression")
        parser.add_option(
            '--collect',
            dest='collectPlugins', default="",
            help="Python plugins to use. Takes a regular expression")
        parser.add_option(
            '--twistedthreadpoolsize',
            dest='threadPoolSize',
            type='int',
            default=10,
            help="Suggested size for twisted reactor threads pool. Takes an integer")

    def postStartup(self):
        if self.options.ignorePlugins and self.options.collectPlugins:
            raise SystemExit("Only one of --ignore or --collect"
                             " can be used at a time")


class PerDataSourceInstanceTaskSplitter(SubConfigurationTaskSplitter):
    """A task splitter that splits each datasource into its own task."""

    subconfigName = 'datasources'

    def makeConfigKey(self, config, subconfig):
        """
        Return a list of keys used to split configurations.

        Datasources with matching config key lists will be run in the same
        task.
        """
        return subconfig.config_key

    def splitConfiguration(self, configs):
        tasks = super(PerDataSourceInstanceTaskSplitter, self).splitConfiguration(configs)
        preferences = zope.component.queryUtility(
            ICollectorPreferences, 'zenpython')

        def class_name(task):
            plugin = task.plugin
            return "%s.%s" % (plugin.__class__.__module__,
                              plugin.__class__.__name__)

        if preferences.options.collectPlugins:
            collect = re.compile(preferences.options.collectPlugins).search
            return {n: t for n, t in tasks.iteritems() if collect(class_name(t))}
        elif preferences.options.ignorePlugins:
            ignore = re.compile(preferences.options.ignorePlugins).search
            return {n: t for n, t in tasks.iteritems() if not ignore(class_name(t))}
        else:
            return tasks


class PythonCollectionTask(BaseTask):
    """A task that performs periodic PythonDataSource collection."""

    zope.interface.implements(IScheduledTask)

    STATE_FETCH_DATA = 'FETCH_DATA'
    STATE_STORE_PERF = 'STORE_PERF_DATA'
    STATE_SEND_EVENTS = 'STATE_SEND_EVENTS'
    STATE_APPLY_MAPS = 'STATE_APPLY_MAPS'

    def __init__(self, taskName, configId, scheduleIntervalSeconds, taskConfig):
        super(PythonCollectionTask, self).__init__(
            taskName, configId, scheduleIntervalSeconds, taskConfig)

        # Needed for interface.
        self.name = taskName
        self.configId = configId
        self.state = TaskStates.STATE_IDLE
        self.interval = scheduleIntervalSeconds
        self.config = taskConfig

        self._collector = zope.component.queryUtility(ICollector)
        self._dataService = zope.component.queryUtility(IDataService)
        self._eventService = zope.component.queryUtility(IEventService)
        self._preferences = zope.component.queryUtility(
            ICollectorPreferences, 'zenpython')

        self.cycling = self._preferences.options.cycle

        from ZenPacks.zenoss.PythonCollector.services.PythonConfig import load_plugin_class
        plugin_class = load_plugin_class(
            self.config.datasources[0].plugin_classname)

        # New in 1.3: Added passing of config to plugin constructor.
        if 'config' in inspect.getargspec(plugin_class.__init__).args:
            self.plugin = plugin_class(config=self.config)
        else:
            self.plugin = plugin_class()

        # Provide access to getService, without providing access
        # to other parts of self, or encouraging the use of
        # self._collector, which you totally did not see.   Nothing
        # to see here.  Move along.
        @inlineCallbacks
        def _getServiceFromCollector(service_name):
            service = yield self._collector.getService(service_name)
            returnValue(service)

        self.plugin.getService = _getServiceFromCollector

        # New in 1.6: Support writeMetricWithMetadata().
        self.writeMetricWithMetadata = hasattr(
            self._dataService, 'writeMetricWithMetadata')

    def doTask(self):
        """Collect a single PythonDataSource."""
        d = self.plugin.collect(self.config)
        d.addBoth(self.plugin.onResult, self.config)
        d.addCallback(self.plugin.onSuccess, self.config)
        d.addErrback(self.plugin.onError, self.config)
        d.addBoth(self.plugin.onComplete, self.config)
        d.addCallback(self.processResults)
        d.addErrback(self.handleError)
        return d

    def cleanup(self):
        return self.plugin.cleanup(self.config)

    def processResults(self, result):
        if not result:
            # New in 1.3. Now safe to return no results.
            return

        # New in 1.3. It's OK to not set results events key.
        if 'events' in result:
            self.sendEvents(result['events'])

        # New in 1.3. It's OK to not set results values key.
        if 'values' in result:
            self.storeValues(result['values'])

        # New in 1.3. It's OK to not set results maps key.
        if 'maps' in result:
            d = self.applyMaps(result['maps'])

            # We should only block the task on applying datamaps when
            # not cycling.
            if d and not self.cycling:
                return d

    def sendEvents(self, events):
        if not events:
            return

        self.state = PythonCollectionTask.STATE_SEND_EVENTS

        if len(events) < 1:
            return

        # Default event fields.
        for event in events:
            event.setdefault('device', self.configId)
            event.setdefault('severity', ZenEventClasses.Info)

        # On CTRL-C or exit the reactor might stop before we get to this
        # call and generate a traceback.
        if reactor.running:
            self._eventService.sendEvents(events)

    def storeValues(self, values):
        if not values:
            return

        self.state = PythonCollectionTask.STATE_STORE_PERF

        for datasource in self.config.datasources:
            component_values = values.get(datasource.component)
            if not component_values:
                continue

            for dp_id, dp_value in component_values.items():
                for dp in datasource.points:
                    dpname = '_'.join((datasource.datasource, dp.id))

                    # New in 1.3: Values can now use either the
                    # datapoint id, or datasource_datapoint syntax in
                    # the component values dictionary.
                    if dp_id not in (dpname, dp.id):
                        continue

                    threshData = {
                        'eventKey': datasource.getEventKey(dp),
                        'component': datasource.component,
                        }

                    for value, timestamp in get_dp_values(dp_value):
                        if self.writeMetricWithMetadata:
                            self._dataService.writeMetricWithMetadata(
                                dp.dpName,
                                value,
                                dp.rrdType,
                                timestamp=timestamp,
                                min=dp.rrdMin,
                                max=dp.rrdMax,
                                threshEventData=threshData,
                                metadata=dp.metadata)
                        else:
                            self._dataService.writeRRD(
                                dp.rrdPath,
                                value,
                                dp.rrdType,
                                rrdCommand=dp.rrdCreateCommand,
                                cycleTime=datasource.cycletime,
                                min=dp.rrdMin,
                                max=dp.rrdMax,
                                threshEventData=threshData,
                                timestamp=timestamp,
                                **WRITERRD_ARGS)

    @inlineCallbacks
    def applyMaps(self, maps):
        if not maps:
            returnValue(None)

        self.state = PythonCollectionTask.STATE_APPLY_MAPS

        remoteProxy = self._collector.getRemoteConfigServiceProxy()

        log.debug("%s sending %s datamaps", self.name, len(maps))

        try:
            changed = yield remoteProxy.callRemote(
                'applyDataMaps', self.configId, maps)
        except (pb.PBConnectionLost, HubDown), e:
            log.error("Connection was closed by remote, "
                "please check zenhub health. "
                "%s lost %s datamaps", self.name, len(maps))
        except Exception, e:
            log.exception("%s lost %s datamaps", self.name, len(maps))
        else:
            if changed:
                log.debug("%s changes applied", self.name)
            else:
                log.debug("%s no changes applied", self.name)

    def handleError(self, result):
        log.error('%s unhandled plugin error: %s', self.name, result)


def main():
    preferences = Preferences()
    task_factory = SimpleTaskFactory(PythonCollectionTask)
    task_splitter = PerDataSourceInstanceTaskSplitter(task_factory)
    daemon = CollectorDaemon(preferences, task_splitter)
    pool_size = preferences.options.threadPoolSize
    reactor.suggestThreadPoolSize(pool_size)
    daemon.run()


if __name__ == '__main__':
    main()
