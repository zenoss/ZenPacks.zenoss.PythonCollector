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

import Globals

from twisted.internet.defer import Deferred, DeferredList
from twisted.spread import pb

import zope.interface

from Products.ZenCollector.daemon import CollectorDaemon

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

from ZenPacks.zenoss.PythonCollector.services.PythonConfig import PythonDataSourceConfig

unused(Globals)

pb.setUnjellyableForClass(PythonDataSourceConfig, PythonDataSourceConfig)


class Preferences(object):
    zope.interface.implements(ICollectorPreferences)

    collectorName = 'zenpython'
    configurationService = 'ZenPacks.zenoss.PythonCollector.services.PythonConfig'
    cycleInterval = 5 * 60  # 5 minutes
    configCycleInterval = 60 * 60 * 12  # 12 hours
    maxTasks = None  # use system default

    def buildOptions(self, parser):
        pass

    def postStartup(self):
        pass


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

    def doTask(self):
        """Collect a single PythonDataSource."""
        d = self.plugin.collect(self.config)
        d.addBoth(self.plugin.onResult, self.config)
        d.addCallback(self.plugin.onSuccess, self.config)
        d.addErrback(self.plugin.onError, self.config)
        d.addErrback(self.handleError)
        d.addBoth(self.plugin.onComplete, self.config)
        d.addCallback(self.processResults)
        return d

    def cleanup(self):
        return self.plugin.cleanup(self.config)

    def processResults(self, result):
        if not result:
            # New in 1.3. Now safe to return no results.
            return

        deferreds = []

        # New in 1.3. It's OK to not set results events key.
        if 'events' in result:
            deferreds.append(self.sendEvents(result['events']))

        # New in 1.3. It's OK to not set results values key.
        if 'values' in result:
            deferreds.append(self.storeValues(result['values']))

        # New in 1.3. It's OK to not set results maps key.
        if 'maps' in result:
            deferreds.append(self.applyMaps(result['maps']))

        # When not cycling we have to wait for these deferreds to fire.
        if not self.cycling and deferreds:
            return DeferredList(
                [x for x in deferreds if isinstance(x, Deferred)],
                consumeErrors=True)

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

                    self._dataService.writeRRD(
                        dp.rrdPath,
                        dp_value[0],
                        dp.rrdType,
                        rrdCommand=dp.rrdCreateCommand,
                        cycleTime=datasource.cycletime,
                        min=dp.rrdMin,
                        max=dp.rrdMax,
                        threshEventData=threshData,
                        timestamp=dp_value[1])

    def applyMaps(self, maps):
        if not maps:
            return

        self.state = PythonCollectionTask.STATE_APPLY_MAPS

        remoteProxy = self._collector.getRemoteConfigServiceProxy()

        log.warn("%s sending %s datamaps", self.name, len(maps))
        d = remoteProxy.callRemote('applyDataMaps', self.configId, maps)

        def applyMapsCallback(changed):
            if changed:
                log.warn("%s changes applied", self.name)
            else:
                log.warn("%s no changes applied", self.name)

        def applyMapsErrback(failure):
            log.warn("%s lost %s datamaps", self.name, len(maps))

        d.addCallbacks(applyMapsCallback, applyMapsErrback)
        return d

    def handleError(self, result):
        log.error('%s unhandled plugin error: %s', self.name, result)


def main():
    preferences = Preferences()
    task_factory = SimpleTaskFactory(PythonCollectionTask)
    task_splitter = PerDataSourceInstanceTaskSplitter(task_factory)
    daemon = CollectorDaemon(preferences, task_splitter)
    daemon.run()


if __name__ == '__main__':
    main()
