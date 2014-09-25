##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging
ADM_LOG = logging.getLogger("zen.ApplyDataMap")

import copy

from Products.DataCollector.plugins.DataMaps import ObjectMap
from Products.ZenEvents import Event
from Products.ZenEvents.ZenEventClasses import Change_Remove, Change_Remove_Blocked
from Products.ZenModel.Lockable import Lockable
from Products.ZenUtils.Utils import monkeypatch


@monkeypatch('Products.DataCollector.ApplyDataMap.ApplyDataMap')
def _updateRelationship(self, device, relmap):
    '''
    Add/Update/Remove objects to the target relationship.

    Overridden to catch naked ObjectMaps with relname set. This
    indicates an incremental model that should be specially handled.

    Return True if a change was made or false if no change was made.
    '''
    if not isinstance(relmap, ObjectMap):
        for objmap in relmap.maps:
            if isinstance(objmap, ObjectMap) and hasattr(objmap, 'relname'):
                del(objmap.relname)

        # original is injected by monkeypatch decorator.
        return original(self, device, relmap)

    # Getting here means relmap is a component ObjectMap. We must make a
    # copy of relmap because this method runs inside a retrying
    # @transact decorator so side-effects must be avoided.
    objmap = copy.deepcopy(relmap)

    remove = getattr(objmap, 'remove', False) is True
    if hasattr(objmap, 'remove'):
        del(objmap.remove)

    relname = getattr(objmap, 'relname', None)
    if hasattr(objmap, 'relname'):
        del(objmap.relname)

    rel = getattr(device, relname, None)
    if not rel:
        return False

    if remove:
        return self._removeRelObject(device, objmap, relname)

    obj = rel._getOb(objmap.id, None)
    if obj:
        return self._updateObject(obj, objmap)

    return self._createRelObject(device, objmap, relname)[0]


@monkeypatch('Products.DataCollector.ApplyDataMap.ApplyDataMap')
def _removeRelObject(self, device, objmap, relname):
    '''
    Remove an object in a relationship using its ObjectMap.

    Return True if a change was made or False if no change was made.
    '''
    rel = getattr(device, relname, None)
    if not rel:
        return False

    obj = rel._getOb(objmap.id, None)
    if not obj:
        return False

    if isinstance(obj, Lockable) and obj.isLockedFromDeletion():
        msg = "Deletion Blocked: {} '{}' on {}".format(
            obj.meta_type, obj.id, obj.device().id)

        ADM_LOG.warn(msg)
        if obj.sendEventWhenBlocked():
            self.logEvent(
                device, obj, Change_Remove_Blocked, msg, Event.Warning)

        return False

    self.logChange(
        device, obj, Change_Remove,
        "removing object {} from rel {} on {}".format(
            obj.id, relname, device.id))

    rel._delObject(obj.id)

    return True
