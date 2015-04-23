##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################


__doc__ = '''DataMapService

Service to apply datamaps
'''

import logging
log = logging.getLogger('zen.PythonCollectorDataMapService')

import Globals
import time

from twisted.spread import pb
from Products.ZenHub.HubService import HubService
from Products.ZenHub.PBDaemon import translateError
from ZODB.transact import transact
from Products.ZenCollector.services.config import CollectorConfigService
from Products.ZenModel.Device import manage_createDevice
from Products.DataCollector.ApplyDataMap import ApplyDataMap
from Products.ZenRRD.zencommand import DataPointConfig
from Products.ZenUtils.ZenTales import talesEvalStr

class DataMapService(HubService):

    def __init__(self, dmd, instance):
        HubService.__init__(self, dmd, instance)
        self.config = self.dmd.Monitors.Performance._getOb(self.instance)

    @translateError
    def remote_applyDataMaps(self, map_data, setLastCollection=False):
        from Products.DataCollector.ApplyDataMap import ApplyDataMap
        adm = ApplyDataMap(self)

        def inner(map):
            def action():
                start_time = time.time()
                completed= bool(adm._applyDataMap(device, map))
                end_time=time.time()-start_time
                if hasattr(map, "relname"):
                    log.debug("Time in _applyDataMap for Device %s with relmap %s objects: %.2f", device.getId(),map.relname,end_time)
                elif hasattr(map,"modname"):
                    log.debug("Time in _applyDataMap for Device %s with objectmap, size of %d attrs: %.2f",device.getId(),len(map.items()),end_time)
                else:
                    log.debug("Time in _applyDataMap for Device %s: %.2f . Could not find if relmap or objmap",device.getId(),end_time)
                return completed
            return self._do_with_retries(action)
        for d in map_data:
            device = d[0]
            devclass = d[1]
            maps = d[2]
            device = self.getPerformanceMonitor().findDevice(device)
            if device:
                adm.setDeviceClass(device, devclass)
                changed = False
                for map in maps:
                    result = inner(map)
                    changed = changed or result

                if changed:
                    log.debug("Device %s changed by map %r", device.getId(),map)

                # Technically we arent a modelling daemon and we dont know if this
                # was a full modelling run.  Commenting this out because
                # leaving it on could cause a huge storm of invalidations as the
                # device object would be touched almost everytime a call was made.

                #if setLastCollection:
                #    self._setSnmpLastCollection(device)

    def _setSnmpLastCollection(self, device):
        transactional = transact(device.setSnmpLastCollection)
        return self._do_with_retries(transactional)

    @translateError
    def remote_setSnmpLastCollection(self, device):
        device = self.getPerformanceMonitor().findDevice(device)
        self._setSnmpLastCollection(device)

    def _do_with_retries(self, action):
        from ZODB.POSException import StorageError
        max_attempts = 3
        for attempt_num in range(max_attempts):
            try:
                return action()
            except StorageError as e:
                if attempt_num == max_attempts-1:
                    msg = "{0}, maximum retries reached".format(e)
                else:
                    msg = "{0}, retrying".format(e)
                log.info(msg)
