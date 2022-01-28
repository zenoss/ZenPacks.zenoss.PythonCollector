#!/usr/bin/env python
##############################################################################
#
# Copyright (C) Zenoss, Inc. 2012-2018, all rights reserved.
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

import collections
import functools
import inspect
import re

import Globals


if __name__ == "__main__":
    # Install the best reactor available if run as a script. This must
    # be done early before other imports have a chance to install a
    # different reactor.
    try:
        from Products.ZenHub import installReactor
    except ImportError:
        # Zenoss 4.1 doesn't have ZenHub.installReactor.
        pass
    else:
        installReactor()


from twisted.internet import defer, reactor, task
from twisted.internet.defer import inlineCallbacks, returnValue, maybeDeferred
from twisted.python.failure import Failure
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
    IStatisticsService,
    )

from Products.ZenCollector.tasks import (
    BaseTask,
    SimpleTaskFactory,
    SubConfigurationTaskSplitter,
    TaskStates,
    )

from Products.ZenEvents import ZenEventClasses
from Products.ZenUtils.Utils import unused

from ZenPacks.zenoss.PythonCollector import twisted_utils
from ZenPacks.zenoss.PythonCollector import watchdog
from ZenPacks.zenoss.PythonCollector.utils import get_dp_values
from ZenPacks.zenoss.PythonCollector.services.PythonConfig import PythonDataSourceConfig
from ZenPacks.zenoss.PythonCollector.web.semaphores import DEFAULT_TWISTEDCONCURRENTHTTP
from ZenPacks.zenoss.PythonCollector.lib.monotonic import monotonic

try:
    from Products.ZenUtils.Utils import varPath
except ImportError:
    # Zenoss 4 doesn't have varPath. Implement it here.
    from Products.ZenUtils.Utils import zenPath

    def varPath(*args):
        all_args = ['var'] + list(args)
        return zenPath(*all_args)


# patch twisted.web.client.getPage
import ZenPacks.zenoss.PythonCollector.patches.getPage as gp

unused(Globals, gp)

pb.setUnjellyableForClass(PythonDataSourceConfig, PythonDataSourceConfig)


# allowStaleDatapoint isn't available in Zenoss 4.1.
if 'allowStaleDatapoint' in inspect.getargspec(CollectorDaemon.writeRRD).args:
    WRITERRD_ARGS = {'allowStaleDatapoint': False}
else:
    WRITERRD_ARGS = {}


# eventClassKey for RUNNING timeout events.
EVENTCLASSKEY_TIMEOUT = "zenpython-timeout"


class Preferences(object):
    zope.interface.implements(ICollectorPreferences)

    collectorName = 'zenpython'
    configurationService = 'ZenPacks.zenoss.PythonCollector.services.PythonConfig'
    cycleInterval = 5 * 60  # 5 minutes
    configCycleInterval = 60 * 60 * 12  # 12 hours
    maxTasks = None  # use system default

    def buildOptions(self, parser):
        parser.add_option(
            '--blockingwarning',
            dest='blockingWarning',
            type='float',
            default=3.0,
            help="Log warning when plugin code blocks for X seconds")

        parser.add_option(
            '--blockingtimeout',
            dest='blockingTimeout',
            type='float',
            default=30.0,
            help="Disable plugins that block for X seconds")

        parser.add_option(
            '--runningtimeout',
            dest='runningTimeout',
            type='float',
            default=3.0,
            help="Timeout plugins that run for cycletime * runningtimeout")

        parser.add_option(
            '--twistedthreadpoolsize',
            dest='threadPoolSize',
            type='int',
            default=10,
            help="Maximum threads in thread pool (default %default)")

        parser.add_option(
            '--collect',
            dest='collectPlugins', default="",
            help="Python plugins to use. Takes a regular expression")

        parser.add_option(
            '--ignore',
            dest='ignorePlugins', default="",
            help="Python plugins to ignore. Takes a regular expression")

        parser.add_option(
            '--twistedconcurrenthttp',
            dest='twistedconcurrenthttp',
            type='int',
            default=DEFAULT_TWISTEDCONCURRENTHTTP,
            help="Overall limit of concurrent HTTP connections by all plugins which utilize ZenPacks.zenoss.PythonCollector.web.client.getPage")

        parser.add_option(
            '--datasource',
            dest='datasource',
            type='string',
            default=None,
            help="Collect just for one datasource")

    def postStartup(self):
        if self.options.ignorePlugins and self.options.collectPlugins:
            raise SystemExit("Only one of --ignore or --collect"
                             " can be used at a time")

        self.setupWatchdog()

    def setupWatchdog(self):
        if self.options.blockingTimeout > 0:
            self.blockingPlugins = watchdog.get_timeout_entries(
                timeout_file=varPath('{}.blocked'.format(self.collectorName)))

            log.info(
                "plugins disabled by watchdog: %r",
                list(self.blockingPlugins))

            log.info(
                "starting watchdog with %.1fs timeout",
                self.options.blockingTimeout)

            watchdog.start()
        else:
            self.blockingPlugins = set()


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

        self.sendDisabledDatasourceEvents(configs)

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

    def sendDisabledDatasourceEvents(self, configs):
        preferences = zope.component.queryUtility(
            ICollectorPreferences, 'zenpython')

        disabled_map = collections.defaultdict(set)
        for config in configs:
            for datasource in config.datasources:
                if datasource.plugin_classname in preferences.blockingPlugins:
                    disabled_map[config.configId].add(
                        '{}/{}'.format(
                            datasource.template,
                            datasource.datasource))

        events = zope.component.queryUtility(IEventService)
        for device_id, disabled_datasources in disabled_map.iteritems():
            if len(disabled_datasources) > 1:
                summary = (
                    "multiple datasources have been disabled - see details")
            else:
                summary = "{} datasource has been disabled".format(
                    list(disabled_datasources)[0])

            events.sendEvent({
                'device': device_id,
                'severity': ZenEventClasses.Error,
                'eventClassKey': 'zenpython-datasources-disabled',
                'eventKey': 'zenpython-datasources-disabled',
                'summary': summary,
                'message': (
                    "Some monitoring for this device has been disabled due to "
                    "problems detected in the following datasources: {}"
                    .format(', '.join(sorted(disabled_datasources))))})


class PythonCollectionTask(BaseTask):
    """A task that performs periodic PythonDataSource collection."""

    zope.interface.implements(IScheduledTask)

    STATE_STORE_PERF = 'STORE_PERF_DATA'
    STATE_PUBLISH_METRICS = 'PUBLISH_METRICS'
    STATE_SEND_EVENTS = 'SEND_EVENTS'
    STATE_APPLY_MAPS = 'APPLY_MAPS'
    STATE_BLOCKING = 'BLOCKING'

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
        self._statsService = zope.component.queryUtility(IStatisticsService)
        self._preferences = zope.component.queryUtility(
            ICollectorPreferences, 'zenpython')

        self.cycling = self._preferences.options.cycle
        self.blockingWarning = self._preferences.options.blockingWarning
        self.blockingTimeout = self._preferences.options.blockingTimeout
        self.blockingPlugins = self._preferences.blockingPlugins
        self.chosenDatasource = self._preferences.options.datasource

        if self.chosenDatasource:
            self.config.datasources = self.getDatasources()

        self.plugin = self.initializePlugin()

        # New in 1.6: Support writeMetricWithMetadata().
        self.writeMetricWithMetadata = hasattr(
            self._dataService, 'writeMetricWithMetadata')

        # New in 1.7: Use startDelay from the plugin.
        self.startDelay = getattr(self.plugin, 'startDelay', None)

        # New in 1.7.2: Wrap all calls to plugin methods in synchronous
        # timeouts if "blockingtimeout" is non-zero. This is done to
        # guard zenpython against plugins that pause the event loop with
        # blocking code.
        self.pluginCalls = {
            x: self.wrapPluginCall(getattr(self.plugin, x))
            for x in [
                'collect',
                'onResult',
                'onSuccess',
                'onError',
                'onComplete',
                'cleanup',
            ]
        }

        # New in 1.7.2: Track the percent of time zenpython is blocked
        # by plugin code. Plugin code should be asynchronous and the
        # amount of time they block should be very small. However, code
        # is code and we can't guarantee that it's asynchronous. So we
        # measure it instead.
        self.percentBlocked = self.getStatistic('percentBlocked', 'COUNTER')

        # New in 1.10.0: Timeout plugin collect methods that stay RUNNING for
        # too long.
        self.runningTimeout = self._preferences.options.runningTimeout
        self.timeoutEvent = self.initializeTimeoutEvent()
        self.timeoutEventSeverity = self.getMaximumSeverity()

        # New in 1.10.0: Track the number of tasks timed out by runningtimeout.
        self.timedOutTasks = self.getStatistic('timedOutTasks', 'COUNTER')

        # New in 1.11.0: Support for datapoint extra tags.
        self.metricExtraTags = getattr(
            self._dataService, "metricExtraTags", False)

    def getDatasources(self):
        try:
            template, datasource = self.chosenDatasource.split('/')
        except ValueError:
            log.error('Invalid datasource format')
            return []
        filteredDatasources = [
            ds for ds in self.config.datasources
            if ds.template == template and ds.datasource == datasource]
        if len(filteredDatasources) == 0:
            log.error(
                'No configs for template %s, datasource %s',
                template, datasource)
        return filteredDatasources

    def getStatistic(self, name, type_):
        """Return statistic. It will be added first if necessary."""
        try:
            self._statsService.addStatistic(name, type_)
        except NameError:
            # NameError means the statistic already exists.
            pass

        return self._statsService.getStatistic(name)

    def getMaximumSeverity(self):
        """Return maximum severity of all datasources in our config."""
        return max(x.severity for x in self.config.datasources)

    def initializePlugin(self):
        """Return initialized PythonDataSourcePlugin for this task."""
        from ZenPacks.zenoss.PythonCollector.services.PythonConfig import load_plugin_class
        plugin_class = load_plugin_class(
            self.config.datasources[0].plugin_classname)

        # New in 1.3: Added passing of config to plugin constructor.
        if 'config' in inspect.getargspec(plugin_class.__init__).args:
            plugin = plugin_class(config=self.config)
        else:
            plugin = plugin_class()

        # Provide access to getService, without providing access
        # to other parts of self, or encouraging the use of
        # self._collector, which you totally did not see.   Nothing
        # to see here.  Move along.
        @inlineCallbacks
        def _getServiceFromCollector(service_name):
            service = yield self._collector.getService(service_name)
            returnValue(service)

        plugin.getService = _getServiceFromCollector

        # New in 1.11: Allow plugins to directly and immediately publish data.
        plugin.publishData = self.processResults
        plugin.publishEvents = self.sendEvents
        plugin.publishValues = self.storeValues
        plugin.publishMetrics = self.publishMetrics
        plugin.publishMaps = self.applyMaps
        plugin.changeInterval = self.changeInterval

        return plugin

    def wrapPluginCall(self, f):
        """Records detailed statistics for wrapped function."""
        @functools.wraps(f)
        def __wrapper(*args, **kwargs):
            # Save original state to restore after running function.
            original_state = self.state

            # Set state and set start time then execute function.
            self.state = PythonCollectionTask.STATE_BLOCKING
            start_time = monotonic.monotonic()

            try:
                return f(*args, **kwargs)
            finally:
                elapsed_time = (monotonic.monotonic() - start_time)

                # Track seconds spent in wrapped functions with as much
                # precision as the system allows. Convert the precise
                # seconds value to the closest centiseconds
                # approximation for our percentBlocked datapoint value.
                # Centiseconds are chosen because their rate equals
                # percent of total time spent.
                self.percentBlocked.value += elapsed_time * 100

                # Restore original state even if an exception occurs.
                self.state = original_state

                if self.blockingWarning is not None:
                    if elapsed_time >= self.blockingWarning:
                        log.warning(
                            "Task %s blocked for %.2f seconds in %s",
                            self.name,
                            elapsed_time,
                            f.__name__)

        return __wrapper

    def initializeTimeoutEvent(self):
        """Return base timeout event used for timeouts and clears."""
        components = set(x.component for x in self.config.datasources)
        components_c = ",".join(x for x in sorted(components) if x is not None)

        datasources = set(x.datasource for x in self.config.datasources)
        datasources_c = ",".join(sorted(datasources))

        # Friendly components portion of event's summary.
        if len(components) > 1:
            component = ""
            components_s = " for multiple components"
        else:
            component = next(iter(components))
            components_s = ""

        # Friendly datasources portion of event's summary.
        if len(datasources) > 1:
            datasources_s = "multiple datasources"
        else:
            datasources_s = "{} datasource".format(next(iter(datasources)))

        event = {
            'component': component,
            'components': components_c,
            'datasources': datasources_c,
            'eventClassKey': EVENTCLASSKEY_TIMEOUT,
            'eventKey': "{}|{}".format(EVENTCLASSKEY_TIMEOUT, self.name),
            'summary': "timeout collecting {}{}".format(
                datasources_s, components_s),
        }

        return event

    def doTask(self):
        """Collect a single PythonDataSource."""
        ds = self.config.datasources[0]
        template = ds.template
        datasource = ds.datasource
        plugin_classname = ds.plugin_classname

        # Prevent disabled plugins (due to BLOCKING) from running.
        if plugin_classname in self.blockingPlugins:
            log.warning(
                "Task %s is disabled (%s/%s)",
                self.name,
                template,
                datasource)

            return defer.fail(Exception('disabled'))

        # Guard against plugin's collect method BLOCKING for too long.
        with watchdog.timeout(self.blockingTimeout, plugin_classname):
            if (
                hasattr(self, "_scheduler")
                and getattr(self._scheduler, "cyberark", None)
            ):
                d = self._update_configs()
                d.addCallback(self._run_collect)
            else:
                d = self._run_collect()

        # Guard against plugin's collect method RUNNING for too long.
        if self.runningTimeout:
            d = twisted_utils.add_timeout(
                d,
                ds.cycletime * self.runningTimeout,
                exception_class=RunningTimeoutError)

        # Allow the plugin to handle results from it's collect method.
        d.addBoth(self.pluginCalls['onResult'], self.config)
        d.addCallback(self.pluginCalls['onSuccess'], self.config)
        d.addErrback(self.pluginCalls['onError'], self.config)
        d.addBoth(self.pluginCalls['onComplete'], self.config)

        # Have zenpython handle RunningTimeoutError if the plugin doesn't.
        if self.runningTimeout:
            d.addBoth(self.handleTimeout)

        # Have zenpython process the results: events, values, metrics, maps.
        d.addCallback(self.processResults)

        # Have zenpython handle any errors not handled by the plugin.
        d.addErrback(self.handleError)

        # Return Deferred to the collector framework.
        return d

    @inlineCallbacks
    def _update_configs(self):
        for ds in self.config.datasources:
            yield self._scheduler.cyberark.update_config(ds.device, ds)

    def _run_collect(self, result=None):
        return self.pluginCalls['collect'](self.config)

    def cleanup(self):
        try:
            return self.pluginCalls['cleanup'](self.config)
        except Exception as e:
            return self.handleError(e)

    def handleTimeout(self, result):
        if isinstance(result, Failure):
            if isinstance(result.value, RunningTimeoutError):
                self.timedOutTasks.value += 1

                # Return a timeout event.
                return {'events': [self.getTimeoutEvent(clear=False)]}
        else:
            # Add timeout clear event to plugin's events.
            if result is None:
                result = {}

            if 'events' not in result:
                result['events'] = []

            result['events'].append(self.getTimeoutEvent(clear=True))

        # Propagate any other failure or success.
        return result

    def getTimeoutEvent(self, clear=False):
        """Return a timeout or timeout clear event."""
        return dict(
            severity=0 if clear else self.timeoutEventSeverity,
            **self.timeoutEvent)

    @inlineCallbacks
    def processResults(self, result):
        if not result:
            # New in 1.3. Now safe to return no results.
            returnValue(None)

        # New in 1.3. It's OK to not set results events key.
        if 'events' in result:
            yield self.sendEvents(result['events'])

        # New in 1.3. It's OK to not set results values key.
        if 'values' in result:
            yield self.storeValues(result['values'])

        # New in 1.11. Publishing of ad hoc metrics.
        if 'metrics' in result:
            yield self.publishMetrics(result['metrics'])

        # New in 1.3. It's OK to not set results maps key.
        if 'maps' in result:
            d = self.applyMaps(result['maps'])

            # We should only block the task on applying datamaps when
            # not cycling.
            if d and not self.cycling:
                yield d

        # New in 1.9.0. Will change task's interval once set.
        if 'interval' in result:
            self.changeInterval(result['interval'])

    @inlineCallbacks
    def sendEvents(self, events):
        if not events:
            returnValue(None)

        self.state = PythonCollectionTask.STATE_SEND_EVENTS

        # Default event fields.
        for i, event in enumerate(events):
            event.setdefault('device', self.configId)
            event.setdefault('severity', ZenEventClasses.Info)
            # On CTRL-C or exit the reactor might stop before we get to this
            # call and generate a traceback.
            if reactor.running:
                #do in chunks of 100 to give time to reactor
                self._eventService.sendEvent(event)
                if i % 100:
                    yield task.deferLater(reactor, 0, lambda: None)

    @inlineCallbacks
    def storeValues(self, values):
        if not values:
            returnValue(None)

        self.state = PythonCollectionTask.STATE_STORE_PERF
        if self.chosenDatasource:
            log.info(
                "Values would be stored for datasource %s",
                self.chosenDatasource)

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

                    # New in 1.11: Support for extra datapoint tags.
                    tags = getattr(dp, "tags", None)
                    if tags and self.metricExtraTags:
                        write_kwargs = {"extraTags": tags}
                    else:
                        write_kwargs = {}

                    for value, timestamp in get_dp_values(dp_value):
                        if self.chosenDatasource:
                            log.info(
                                "Component: %s >> DataPoint: %s %s",
                                dp.metadata['contextKey'], dp.dpName, value)

                        if self.writeMetricWithMetadata:
                            yield maybeDeferred(
                                self._dataService.writeMetricWithMetadata,
                                dp.dpName,
                                value,
                                dp.rrdType,
                                timestamp=timestamp,
                                min=dp.rrdMin,
                                max=dp.rrdMax,
                                threshEventData=threshData,
                                metadata=dp.metadata,
                                **write_kwargs)

                        else:
                            yield maybeDeferred(
                                self._dataService.writeRRD,
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
    def publishMetrics(self, metrics):
        if not (metrics and self.writeMetricWithMetadata):
            returnValue(None)

        self.state = PythonCollectionTask.STATE_PUBLISH_METRICS

        writer = self._dataService.metricWriter()

        for metric in metrics:
            try:
                yield defer.maybeDeferred(
                    writer.write_metric,
                    metric.name,
                    metric.value,
                    metric.timestamp,
                    metric.tags)
            except Exception as e:
                log.debug("error writing metric: %s", e)

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

    def changeInterval(self, interval):
        interval = int(interval)
        if interval != self.interval:
            self.interval = interval

    def handleError(self, result):
        if isinstance(result, Failure):
            error = result.value
        else:
            error = result

        log.error('%s unhandled plugin error: %s', self.name, error)


class RunningTimeoutError(Exception):
    """Plugin stayed in RUNNING state for too long."""

    def __str__(self):
        return "running timeout"


def main():
    preferences = Preferences()
    task_factory = SimpleTaskFactory(PythonCollectionTask)
    task_splitter = PerDataSourceInstanceTaskSplitter(task_factory)
    daemon = CollectorDaemon(preferences, task_splitter)
    pool_size = preferences.options.threadPoolSize

    # The Twisted version shipped with Zenoss 4.1 doesn't have this.
    if hasattr(reactor, 'suggestThreadPoolSize'):
        reactor.suggestThreadPoolSize(pool_size)

    daemon.run()


if __name__ == '__main__':
    main()
