##############################################################################
#
# Copyright (C) Zenoss, Inc. 2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Model components useful for PythonCollector testing."""

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin

from twisted.internet import defer


class PythonCollector(PythonPlugin):
    relname = "pythonCollectorComponents"
    modname = "ZenPacks.test.PythonCollector.PythonCollectorComponent"

    deviceProperties = PythonPlugin.deviceProperties + (
        "zTestPythonCollectorComponents",
    )

    def collect(self, device, log):
        components = getattr(device, "zTestPythonCollectorComponents", 10)
        log.info("%s: faking %s components", device.id, components)

        return defer.succeed(components)


    def process(self, device, results, log):
        components = results
        log.info("%s: processing %s components", device.id, components)

        rm = self.relMap()
        for i in xrange(components):
            rm.append(self.objectMap({
                "id": "python-collector-component-{}".format(i),
                "title": "PythonCollectorComponent {}".format(i),
            }))

        return rm
