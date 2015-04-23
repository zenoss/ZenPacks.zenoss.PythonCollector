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
import time
import Globals

from twisted.internet import reactor, defer
import twisted.python.log
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
from ZenPacks.zenoss.PythonCollector.interfaces import IDataMapService
from ZenPacks.zenoss.PythonCollector.datamap import DataMapQueueManager
from Products.ZenCollector.daemon import DUMMY_LISTENER
from functools import partial

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
        parser.add_option('--datamapflushseconds',
                           dest='datamapflushseconds',
                           default=5.,
                           type='float',
                           help='Seconds between attempts to flush '
                           'datamaps to ZenHub.')

        parser.add_option('--datamapflushchunksize',
                           dest='datamapflushchunksize',
                           default=50,
                           type='int',
                           help='Number of datamaps to send to ZenHub'
                           'at one time')
        parser.add_option('--maxdatamapqueuelen',
                           dest='maxdatamapqueuelen',
                           default=5000,
                           type='int',
                           help='Maximum number of datamaps to queue')

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
        self._datamapService = zope.component.queryUtility(IDataMapService)
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

    def applyMaps(self, maps):
        if not maps:
            return None

        self.state = PythonCollectionTask.STATE_APPLY_MAPS

        log.debug("%s sending %s datamaps", self.name, len(maps))

        # On CTRL-C or exit the reactor might stop before we get to this
        # call and generate a traceback.
        if reactor.running:
            self._datamapService.applyDataMaps(self.configId, self.config.deviceClass, maps)

    def handleError(self, result):
        log.error('%s unhandled plugin error: %s', self.name, result)


class ZenPythonDaemon(CollectorDaemon):
    zope.interface.implements(IDataMapService)

    def __init__(self, preferences, taskSplitter,
                 configurationListener=DUMMY_LISTENER,
                 initializationCallback=None,
                 stoppingCallback=None):
        self.initialServices += ['ZenPacks.zenoss.PythonCollector.services.DataMapService']
        super(ZenPythonDaemon, self).__init__(preferences, taskSplitter,
                                                   configurationListener,
                                                   initializationCallback,
                                                   stoppingCallback)
        self.DataMapServicestopped = False
        # Add a shutdown trigger to send a stop event and flush the datamap queue
        reactor.addSystemEventTrigger('before', 'shutdown', self._stopPbDaemonDataMapService)

        self.dataMapQueueManager = DataMapQueueManager(self.options, self.log)
        self.datamap_lastStats = 0

        self._pushDataMapsDeferred = None
        # register the various interfaces we provide the rest of the system so
        # that collector implementors can easily retrieve a reference back here
        # if needed
        zope.component.provideUtility(self, IDataMapService)

    '''
    def run(self):
        self.rrdStats.config(self.options.monitor, self.name, [])
        self.log.debug('Starting PBDaemon initialization')
        d = self.connect()
        def callback(result):
            self.sendEvent(self.startEvent)
            self.pushEventsLoop()
            self.log.debug('Calling connected.')
            self.connected()
            return result
        d.addCallback(callback)
        d.addErrback(twisted.python.log.err)
        reactor.run()
        if self._customexitcode:
            sys.exit(self._customexitcode)
    '''


    def run(self):
        def callback(result):
            self.sendEvent(self.startEvent)
            self.pushEventsLoop()
            self.pushDataMapLoop()
            self.log.debug('Calling connected.')
            self.connected()
            return result

        try:
            # Zenoss 5 support
            threshold_notifier = self._getThresholdNotifier()
            self.rrdStats.config(self.name,
                                 self.options.monitor,
                                 self.metricWriter(),
                                 threshold_notifier,
                                 self.derivativeTracker())
        except AttributeError:
            self.rrdStats.config(self.options.monitor, self.name, [])

        self.log.debug('Starting PBDaemon initialization')
        d = self.connect()
        d.addCallback(callback)
        d.addErrback(twisted.python.log.err)
        reactor.run()
        if self._customexitcode:
            sys.exit(self._customexitcode)

        reactor.run()
        if self._customexitcode:
            sys.exit(self._customexitcode)

    @defer.inlineCallbacks
    def pushDataMapLoop(self):
        """Periodically, wake up and flush datamaps to ZenHub."""
        reactor.callLater(self.options.datamapflushseconds, self.pushDataMapLoop)
        self.log.debug('Pushing DataMaps')
        yield self.pushDatamaps()

        # Record the number of datamaps in the queue up to every 2 seconds.
        now = time.time()
        if self.rrdStats.name and now >= (self.datamap_lastStats + 2):
            self.datamap_lastStats = now
            try:
                events = self.rrdStats.gauge(
                    'datamapQueueLength', self.dataMapQueueManager.datamap_queue_length)
            except TypeError:
                events = self.rrdStats.gauge(
                    'datamapQueueLength', 300, self.dataMapQueueManager.datamap_queue_length)

            for event in events:
                self.eventQueueManager.addPerformanceEvent(event)

    @defer.inlineCallbacks
    def pushDatamaps(self):
        """Flush datamaps to ZenHub.
        """
        # are we already shutting down?
        if not reactor.running:
            self.log.debug("Skipping datamap sending - reactor not running.")
            return
        if self._pushDataMapsDeferred:
            self.log.debug("Skipping datamap sending - previous call active.")
            return
        try:
            self._pushDataMapsDeferred = defer.Deferred()

            # are still connected to ZenHub?
            datamapSvc = self.services.get('ZenPacks.zenoss.PythonCollector.services.DataMapService', None)
            if not datamapSvc:
                self.log.error("No datamap service: %r", datamapSvc)
                return

            discarded_datamaps = self.dataMapQueueManager.discarded_datamaps
            if discarded_datamaps:
                self.log.error(
                    'Discarded olded %d datamaps because maxdatamapqueuelen was '
                    'exceeded: %d/%d',
                    discarded_datamaps,
                    discarded_datamaps + self.options.maxdatamapqueuelen,
                    self.options.maxdatamapqueuelen)
                self.counters['discardedDataMaps'] += discarded_datamaps
            self.dataMapQueueManager.discarded_datamaps = 0

            send_datamap_fn = partial(datamapSvc.callRemote, 'applyDataMaps')
            try:
                yield self.dataMapQueueManager.applyDataMaps(send_datamap_fn)
            except (PBConnectionLost, ConnectionLost) as ex:
                self.log.error('Error sending datamap: %s', ex)
        except Exception as ex:
            self.log.exception(ex)
        finally:
            d, self._pushDataMapsDeferred = self._pushDataMapsDeferred, None
            d.callback('datamaps sent')

    def applyDataMaps(self, device, deviceClass, datamaps, **kw):
        """ Add datamaps to queue of maps to be sent.  If we have an map
            service then process the queue.
        """
        generatedDataMaps = self.generateDataMaps(datamaps, **kw)
        self.dataMapQueueManager.addDataMaps(device, deviceClass, generatedDataMaps)
        self.counters['dataMapCount'] += len(generatedDataMaps)

    def generateDataMaps(self, datamaps, **kw):
        """ Add datamaps to queue of maps to be sent.  If we have an datamap
        service then process the queue.
        """
        if not reactor.running:
            return
        return datamaps

    def _stopPbDaemonDataMapService(self):
        if self.DataMapServicestopped:
            return
        self.DataMapServicestopped = True

        if 'ZenPacks.zenoss.PythonCollector.services.DataMapService' in self.services:
            self.log.debug("Shutting down DataMap Service")
            if self._pushDataMapsDeferred:
                self.log.debug("Currently sending datamaps. Queueing next call")
                d = self._pushDataMapsDeferred
                # Schedule another call to flush any additional datamaps
                d.addBoth(lambda unused: self.pushDataMaps())
            else:
                d = self.pushDatamaps()

def main():
    preferences = Preferences()
    task_factory = SimpleTaskFactory(PythonCollectionTask)
    task_splitter = PerDataSourceInstanceTaskSplitter(task_factory)
    daemon = ZenPythonDaemon(preferences, task_splitter)
    pool_size = preferences.options.threadPoolSize
    reactor.suggestThreadPoolSize(pool_size)
    daemon.run()

if __name__ == '__main__':
    main()
