##############################################################################
#
# Copyright (C) Zenoss, Inc. 2012, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging
log = logging.getLogger('zen.PythonDataSource')

import importlib

from twisted.spread import pb

from Products.DataCollector.ApplyDataMap import ApplyDataMap
from Products.ZenCollector.services.config import CollectorConfigService
from Products.ZenRRD.zencommand import DataPointConfig
from Products.ZenUtils.ZenTales import talesEvalStr

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSource


known_point_properties = (
    'isrow', 'rrdmax', 'description', 'rrdmin', 'rrdtype', 'createCmd')


class PythonDataSourceConfig(pb.Copyable, pb.RemoteCopy):
    device = None
    manageIp = None
    component = None
    template = None
    datasource = None
    config_key = None
    params = None
    cycletime = None
    eventClass = None
    eventKey = None
    severity = 3
    plugin_classname = None
    result = None

    def __init__(self):
        self.points = []

    def getEventKey(self, point):
        # fetch datapoint name from filename path and add it to the event key
        return self.eventKey + '|' + point.rrdPath.split('/')[-1]


def load_plugin_class(classname):
    class_parts = classname.split('.')

    module_ = importlib.import_module('.'.join(class_parts[:-1]))
    return getattr(module_, class_parts[-1])


class PythonConfig(CollectorConfigService):

    def _createDeviceProxy(self, device):
        collector = device.getPerformanceServer()

        proxy = CollectorConfigService._createDeviceProxy(self, device)
        proxy.datasources = list(self.device_datasources(device, collector))

        # getTresholdInstances needs the datasource sourcetype string.
        proxy.thresholds = self._thresholds(device)

        for component in device.getMonitoredComponents():
            proxy.datasources += list(
                self.component_datasources(component, collector))

            proxy.thresholds += self._thresholds(component)

        if len(proxy.datasources) > 0:
            return proxy

        return None

    def device_datasources(self, device, collector):
        return self._datasources(device, device.id, None, collector)

    def component_datasources(self, component, collector):
        return self._datasources(
            component, component.device().id, component.id, collector)

    def _datasources(self, deviceOrComponent, deviceId, componentId, collector):
        for template in deviceOrComponent.getRRDTemplates():

            # Get all enabled datasources that are PythonDataSource or
            # subclasses thereof.
            datasources = [
                ds for ds in template.getRRDDataSources() \
                    if ds.enabled and isinstance(ds, PythonDataSource)]

            device = deviceOrComponent.device()

            for ds in datasources:
                datapoints = []

                try:
                    ds_plugin_class = ds.getPluginClass()
                except Exception as e:
                    log.error(
                        "Failed to load plugin %r for %s/%s: %s",
                        ds.plugin_classname,
                        template.id,
                        ds.titleOrId(),
                        e)

                    continue

                for dp in ds.datapoints():
                    dp_config = DataPointConfig()
                    dp_config.id = dp.id
                    dp_config.dpName = dp.name()
                    dp_config.component = componentId
                    dp_config.rrdPath = '/'.join((deviceOrComponent.rrdPath(), dp.name()))
                    dp_config.rrdType = dp.rrdtype
                    dp_config.rrdCreateCommand = dp.getRRDCreateCommand(collector)
                    dp_config.rrdMin = dp.rrdmin
                    dp_config.rrdMax = dp.rrdmax

                    # MetricMixin.getMetricMetadata() added in Zenoss 5.
                    if hasattr(deviceOrComponent, 'getMetricMetadata'):
                        dp_config.metadata = deviceOrComponent.getMetricMetadata()

                    # Attach unknown properties to the dp_config
                    for key in dp.propdict().keys():
                        if key in known_point_properties:
                            continue
                        try:
                            value = getattr(dp, key)
                            if isinstance(value, basestring) and '$' in value:
                                extra = {
                                    'device': device,
                                    'dev': device,
                                    'devname': device.id,
                                    'datasource': ds,
                                    'ds': ds,
                                    'datapoint': dp,
                                    'dp': dp,
                                    }

                                value = talesEvalStr(
                                    value,
                                    deviceOrComponent,
                                    extra=extra)

                            setattr(dp_config, key, value)
                        except Exception:
                            pass

                    datapoints.append(dp_config)

                ds_config = PythonDataSourceConfig()
                ds_config.device = deviceId
                ds_config.manageIp = deviceOrComponent.getManageIp()
                ds_config.component = componentId
                ds_config.plugin_classname = ds.plugin_classname
                ds_config.template = template.id
                ds_config.datasource = ds.titleOrId()
                ds_config.config_key = ds.getConfigKey(deviceOrComponent)
                ds_config.params = ds.getParams(deviceOrComponent)
                ds_config.cycletime = ds.getCycleTime(deviceOrComponent)
                ds_config.eventClass = ds.eventClass
                ds_config.eventKey = ds.eventKey
                ds_config.severity = ds.severity
                ds_config.points = datapoints

                # Populate attributes requested by plugin.
                for attr in ds_plugin_class.proxy_attributes:
                    value = getattr(deviceOrComponent, attr, None)
                    if callable(value):
                        value = value()

                    setattr(ds_config, attr, value)

                yield ds_config

    def _thresholds(self, deviceOrComponent):
        # Copied from RRDView.getThresholdInstances. The dsType check in the
        # original version is string-based and doesn't allow for datasource
        # subclasses. We'll use instanceof instead.

        from Products.ZenEvents.Exceptions import pythonThresholdException
        result = []
        for template in deviceOrComponent.getRRDTemplates():
            # if the template refers to a data source name of the right type
            # include it
            datasources = [
                ds for ds in template.datasources()
                    if isinstance(ds, PythonDataSource)
                ]

            names = set(dp.name() for ds in datasources for dp in ds.datapoints())
            for threshold in template.thresholds():
                if not threshold.enabled:
                    continue

                for ds in threshold.dsnames:
                    if ds in names:
                        try:
                            thresh = threshold.createThresholdInstance(deviceOrComponent)
                            result.append(thresh)
                        except pythonThresholdException, ex:
                            log.warn(ex)
                            zem = deviceOrComponent.primaryAq().getEventManager()
                            import socket
                            device = socket.gethostname()
                            path = template.absolute_url_path()
                            msg = "The threshold %s in template %s has caused an exception." % (threshold.id, path)
                            evt = dict(summary=str(ex), severity=3,
                                    component='zenhub', message=msg,
                                    dedupid='zenhub|' + str(ex),
                                    template=path,
                                    threshold=threshold.id,
                                    device=device, eventClass="/Status/Update",)

                            zem.sendEvent(evt)

                        break
        return result

    def remote_applyDataMaps(self, device, datamaps):
        device = self.getPerformanceMonitor().findDevice(device)
        applicator = ApplyDataMap(self)

        changed = False
        for datamap in datamaps:
            if applicator._applyDataMap(device, datamap):
                changed = True

        return changed
