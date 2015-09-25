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

import functools
import inspect
import re
import signal
import time

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


from twisted.internet import reactor, task
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

from ZenPacks.zenoss.PythonCollector.utils import get_dp_values
from ZenPacks.zenoss.PythonCollector.services.PythonConfig \
    import PythonDataSourceConfig
from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import SynchronousTimeoutError

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
            '--blockingwarning',
            dest='blockingWarning',
            type='float',
            default=30.0,
            help="Log warning when plugin code blocks for X seconds")

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

    STATE_STORE_PERF = 'STORE_PERF_DATA'
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

        self.plugin = self.initializePlugin()

        # New in 1.6: Support writeMetricWithMetadata().
        self.writeMetricWithMetadata = hasattr(
            self._dataService, 'writeMetricWithMetadata')

        # New in 1.7: Use startDelay from the plugin.
        self.startDelay = getattr(self.plugin, 'startDelay', None)

        # New in 1.8.0: Use timeout from the plugin.
        self.timeout = getattr(self.plugin, 'timeout', 0)

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
        try:
            self._statsService.addStatistic('percentBlocked', 'COUNTER')
        except NameError:
            # NameError means the statistic already exists.
            pass

        self.percentBlocked = self._statsService.getStatistic('percentBlocked')

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

        return plugin

    def wrapPluginCall(self, f):
        """Records detailed statistics for wrapped function."""
        @functools.wraps(f)
        def __wrapper(*args, **kwargs):
            # Save original state to restore after running function.
            original_state = self.state

            # Set state and set start time then execute function.
            self.state = PythonCollectionTask.STATE_BLOCKING
            start_time = time.time()

            try:
                if self.timeout:
                    # Add a timeout configured to do so.
                    return synchronous_timeout(
                        timeout=self.timeout,
                        message="timeout ({})".format(f.__name__)
                        )(f)(*args, **kwargs)
                else:
                    # Otherwise just run the function.
                    return f(*args, **kwargs)
            finally:
                elapsed_time = (time.time() - start_time)

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

    def doTask(self):
        """Collect a single PythonDataSource."""
        d = self.pluginCalls['collect'](self.config)
        d.addBoth(self.pluginCalls['onResult'], self.config)
        d.addCallback(self.pluginCalls['onSuccess'], self.config)
        d.addErrback(self.pluginCalls['onError'], self.config)
        d.addBoth(self.pluginCalls['onComplete'], self.config)
        d.addCallback(self.processResults)
        d.addErrback(self.handleError)
        return d

    def cleanup(self):
        try:
            return self.pluginCalls['cleanup'](self.config)
        except Exception as e:
            return self.handleError(e)

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

        # New in 1.3. It's OK to not set results maps key.
        if 'maps' in result:
            d = self.applyMaps(result['maps'])

            # We should only block the task on applying datamaps when
            # not cycling.
            if d and not self.cycling:
                yield d

    @inlineCallbacks
    def sendEvents(self, events):
        if not events:
            return

        self.state = PythonCollectionTask.STATE_SEND_EVENTS

        if len(events) < 1:
            return

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
                            yield maybeDeferred(self._dataService.writeMetricWithMetadata,
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
        if isinstance(result, Failure):
            error = result.value
        else:
            error = result

        log.error('%s unhandled plugin error: %s', self.name, error)


def synchronous_timeout(timeout=0.0, message="timeout"):
    """Function decorator that raises SynchronousTimeoutError.

    Timeout is specified in seconds and accepts an int or float. Raises
    SynchronousTimeoutError if the decorated function's execution takes
    longer than timeout seconds.

    Only functional for functions running on the main thread due to the
    use of SIGALRM.

    """
    def wrap_function(f):
        @functools.wraps(f)
        def __wrapper(*args, **kwargs):
            def alarm_handler(signum, frame):
                raise SynchronousTimeoutError(message=message, timeout=timeout)

            old_handler = signal.signal(signal.SIGALRM, alarm_handler)
            signal.setitimer(signal.ITIMER_REAL, float(timeout))
            try:
                return f(*args, **kwargs)
            finally:
                signal.setitimer(signal.ITIMER_REAL, 0.0)
                signal.signal(signal.SIGALRM, old_handler)

        return __wrapper

    return wrap_function


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
