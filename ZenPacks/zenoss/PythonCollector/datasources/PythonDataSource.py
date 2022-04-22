##############################################################################
#
# Copyright (C) Zenoss, Inc. 2012-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import collections
import datetime
import time

from Acquisition import aq_base
from zope.component import adapts
from zope.interface import implements

from twisted.internet import defer

from Products.ZenModel.RRDDataSource import RRDDataSource
from Products.ZenModel.ZenPackPersistence import ZenPackPersistence
from Products.ZenUtils.ZenTales import talesEvalStr

from Products.Zuul.form import schema
from Products.Zuul.infos import ProxyProperty
from Products.Zuul.infos.template import RRDDataSourceInfo
from Products.Zuul.interfaces import IRRDDataSourceInfo
from Products.Zuul.utils import ZuulMessageFactory as _t


class PythonDataSource(ZenPackPersistence, RRDDataSource):
    """General-purpose Python data source."""

    ZENPACKID = 'ZenPacks.zenoss.PythonCollector'

    sourcetypes = ('Python',)
    sourcetype = sourcetypes[0]

    plugin_classname = None

    # Defined instead of inherited to change cycletime type to string.
    _properties = (
        {'id': 'sourcetype', 'type': 'selection', 'select_variable': 'sourcetypes', 'mode': 'w'},
        {'id': 'enabled', 'type': 'boolean', 'mode': 'w'},
        {'id': 'component', 'type': 'string', 'mode': 'w'},
        {'id': 'eventClass', 'type': 'string', 'mode': 'w'},
        {'id': 'eventKey', 'type': 'string', 'mode': 'w'},
        {'id': 'severity', 'type': 'int', 'mode': 'w'},
        {'id': 'commandTemplate', 'type': 'string', 'mode': 'w'},
        {'id': 'cycletime', 'type': 'string', 'mode': 'w'},
        {'id': 'plugin_classname', 'type': 'string', 'mode': 'w'},
        )

    def getDescription(self):
        return self.plugin_classname

    def talesEval(self, text, context):
        if text is None:
            return

        device = context.device()
        extra = {
            'device': device,
            'dev': device,
            'devname': device.id,
            'datasource': self,
            'ds': self,
            }

        return talesEvalStr(str(text), context, extra=extra)

    def getPluginClass(self):
        """Return plugin class referred to by self.plugin_classname."""
        plugin_class = getattr(aq_base(self), '_v_pluginClass', None)
        if not plugin_class:
            from ZenPacks.zenoss.PythonCollector.services.PythonConfig \
                import load_plugin_class

            self._v_pluginClass = load_plugin_class(self.plugin_classname)

        return self._v_pluginClass

    def getCycleTime(self, context):
        return int(self.talesEval(self.cycletime, context))

    def getConfigKey(self, context):
        """Returns a tuple to be used to split configs at the collector."""
        if not self.plugin_classname:
            return [context.id]

        return self.getPluginClass().config_key(self, context)

    def getParams(self, context):
        """Returns extra parameters needed for collecting this datasource."""
        if not self.plugin_classname:
            return {}

        try:
            params = self.getPluginClass().params(self, context)
        except Exception:
            params = {}
        return params


class IPythonDataSourceInfo(IRRDDataSourceInfo):
    plugin_classname = schema.TextLine(title=_t(u'Plugin Class Name'))
    cycletime = schema.TextLine(title=_t(u'Cycle Time (seconds)'))


class PythonDataSourceInfo(RRDDataSourceInfo):
    implements(IPythonDataSourceInfo)
    adapts(PythonDataSource)

    testable = False

    plugin_classname = ProxyProperty('plugin_classname')
    cycletime = ProxyProperty('cycletime')


class PythonDataSourcePlugin(object):
    """Abstract base class for a PythonDataSourcePlugin."""

    createdAt = None
    proxy_attributes = ()

    def __init__(self):
        self.createdAt = datetime.datetime.utcnow()

    @classmethod
    def config_key(cls, datasource, context):
        """
        Return list that is used to split configurations at the collector.

        This is a classmethod that is executed in zenhub. The datasource and
        context parameters are the full objects.
        """
        return (
            context.device().id,
            datasource.getCycleTime(context),
            datasource.rrdTemplate().id,
            datasource.id,
            datasource.plugin_classname,
            )

    @classmethod
    def params(cls, datasource, context):
        """
        Return params dictionary needed for this plugin.

        This is a classmethod that is executed in zenhub. The datasource and
        context parameters are the full objects.
        """
        return {}

    def __init__(self, config=None):
        """Initialize the plugin with a configuration.

        New in version 1.3.

        """
        pass

    @staticmethod
    def new_data():
        """
        Return an empty data structure.

        Suitable for returning from on* methods.

        This data structure should emulate the source format defined in
        Products.ZenRRD.parsers.JSON.
        """
        return {
            'values': collections.defaultdict(dict),
            'metrics': [],
            'events': [],
            'maps': [],
            }

    @staticmethod
    def new_metric(name, value, timestamp=None, tags=None):
        return Metric(
            name=name,
            value=value,
            timestamp=timestamp or time.time(),
            tags=tags or {})

    def getService(self, service_name):
        """
        Provides access to zenhub services.  It may be used from within a
        collect method as follows:

            service = yield self.getService('ZenPacks.zenoss.MyZenPack.services.MyService')
            value = yield service.callRemote('myMethod', someParameter)

        This will invoke the method named remote_myMethod in the
        ZenPacks.zenoss.MyZenPack.services.MyService.MyService class:

            from Products.ZenHub.HubService import HubService
            from Products.ZenHub.PBDaemon import translateError

            class MyService(HubService):

                @translateError
                def remote_myMethod(self, someParameter):
                    return "My Result for " + someParameter

        Such services will run within zenhub, which gives them access to ZODB.

        Note: this method is provided by zenpython.  Do not override it in
              subclasses.
        """

    def publishData(self, data):
        """Return Deferred that fires when data is published.

        data must be a dict as is returned new_data().

        This is an alternative to returning data from the collect() method. It
        should only be used when there is data to be published at a time that
        is inconvenient to waiting for collect to be called.

        This is a wrapper that calls the following methods. The other methods
        can be used instead if there's a specific type of data to be published.

        - publishEvents
        - publishValues
        - publishMetrics
        - publishMaps
        - changeInterval

        Note: This method cannot be overridden. It is injected by zenpython.

        """

    def publishEvents(self, events):
        """Return Deferred that fires when events are published.

        events must be an iterable of event dictionaries.

        This is an alternative to returning data["events"] from the collect()
        method. It should only be used when there are events to be published at
        a time that is inconvenient to waiting for collect to be called.

        This method is called by publishData() which can be used if there's
        more than just events to publish.

        Note: This method cannot be overridden. It is injected by zenpython.

        """

    def publishValues(self, values):
        """Return Deferred that fires when values are published.

        values must be a dict (or defaultdict) with the same requirements as
        the data["values"] returned from new_data().

        This is an alternative to returning data["values"] from the collect()
        method. It should only be used when there are events to be published at
        a time that is inconvenient to waiting for collect to be called.

        This method is called by publishData() which can be used if there's
        more than just values to publish.

        Note: This method cannot be overridden. It is injected by zenpython.

        """

    def publishMetrics(self, metrics):
        """Return Deferred that fires when metrics are published.

        metrics must be a List[Metric] with the same requirements as the
        data["metrics"] returned from new_data().

        This is an alternative to returning data["metrics"] from the collect()
        method. It should only be used when there are metrics to be published at
        a time that is inconvenient to waiting for collect to be called.

        This method is called by publishData() which can be used if there's
        more than just metrics to publish.

        Note: This method cannot be overridden. It is injected by zenpython.

        """

    def publishMaps(self, maps):
        """Return Deferred that fires when maps are published.

        maps must be a List[DataMaps] with the same requirements as the
        data["maps"] returned from new_data().

        This is an alternative to returning data["maps"] from the collect()
        method. It should only be used when there are maps to be published at
        a time that is inconvenient to waiting for collect to be called.

        This method is called by publishData() which can be used if there's
        more than just maps to publish.

        Note: This method cannot be overridden. It is injected by zenpython.

        """

    def changeInterval(self, interval):
        """Change collection interval for this plugin. Returns None.

        This is the same as returning a new interval from collect in
        data["interval"]. The only difference is that this method can be
        called by the plugin at a time other than when the collect method
        returns.

        This method is called by publishData() which can be used if there's
        data to publish in addition to changing the plugin's collection
        interval.

        Note: This method cannot be overridden. It is injected by zenpython.

        """

    def collect(self, config):
        """No default collect behavior. Must be implemented in subclass."""
        return defer.succeed(None)

    def onResult(self, result, config):
        """Called first for success and error."""
        return result

    def onSuccess(self, result, config):
        """Called only on success. After onResult, before onComplete."""
        return result

    def onError(self, result, config):
        """Called only on error. After onResult, before onComplete."""
        return result

    def onComplete(self, result, config):
        """Called last for success and error."""
        return result

    def cleanup(self, config):
        """Called when collector exits, or task is deleted or recreated."""
        return


Metric = collections.namedtuple(
    "Metric", (
        "name",
        "value",
        "timestamp",
        "tags"))
