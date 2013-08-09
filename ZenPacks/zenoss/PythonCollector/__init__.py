##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging
LOG = logging.getLogger('zen.PythonCollector')

from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from Products.ZenUtils.Utils import monkeypatch


@monkeypatch('Products.DataCollector.ApplyDataMap.ApplyDataMap')
def _updateRelationship(self, device, relmap):
    '''
    Add/Update/Remove objects to the target relationship.

    Overridden here to support adding and removing individual components
    with a bare ObjectMap. To invoke this new support you must add a
    relname property to the ObjectMap. To cause the ObjectMap to remove
    the object it would be mapped to, set a property named "remove" to
    True.
    '''
    relname = getattr(relmap, 'relname', None)
    if isinstance(relmap, ObjectMap) and relname:
        rel = getattr(device, relname, None)
        if not rel:
            LOG.warn(
                "no relationship:%s found on:%s (%s %s)",
                relmap.relname,
                device.id,
                device.__class__,
                device.zPythonClass)

            return False

        # Remove the relname property so we don't get warned about it
        # being an illegitimate attribute later.
        del(relmap.relname)

        if relmap.id in rel.objectIds():
            if getattr(relmap, 'remove', False) is True:
                rel._delObject(relmap.id)
                return True
            else:
                return self._updateObject(rel._getOb(relmap.id), relmap)
        else:
            return self._createRelObject(device, relmap, relname)

    elif isinstance(relmap, RelationshipMap):
        # Remove relname properties from contained ObjectMap objects so
        # we don't see the attribute not found warnings later.
        for objmap in relmap.maps:
            if isinstance(objmap, ObjectMap) and hasattr(objmap, 'relname'):
                del(objmap.relname)

    # original is injected into locals by the monkeypatch decorator.
    return original(self, device, relmap)
