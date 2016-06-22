##############################################################################
#
# Copyright (C) Zenoss, Inc. 2016, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Test cases for PythonConfig hub service."""

import transaction

from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap
from Products.ZenTestCase.BaseTestCase import BaseTestCase

from ZenPacks.zenoss.PythonCollector.services.PythonConfig import PythonConfig


class remote_applyDataMapsTests(BaseTestCase):
    """Test case for PythonConfig.remote_applyDataMaps method."""

    def afterSetUp(self):
        """Preparation invoked before each test is run."""
        super(remote_applyDataMapsTests, self).afterSetUp()
        self.service = PythonConfig(self.dmd, "localhost")
        self.deviceclass = self.dmd.Devices.createOrganizer("/Test")
        self.device = self.deviceclass.createInstance("test-device")
        self.device.setPerformanceMonitor("localhost")
        self.device.setManageIp("192.0.2.77")
        self.device.index_object()
        transaction.commit()


    def test_updateDevice(self):
        """Test updating device properties."""
        device_om = ObjectMap({"rackSlot": "near-the-top"})

        changed = self.service.remote_applyDataMaps(self.device.id, [device_om])
        self.assertTrue(changed, "device not changed by first ObjectMap")

        self.assertEqual(
            "near-the-top", self.device.rackSlot,
            "device.rackSlot not updated by ObjectMap")

        changed = self.service.remote_applyDataMaps(self.device.id, [device_om])
        self.assertFalse(changed, "device changed by duplicate ObjectMap")

    def test_updateDeviceHW(self):
        """Test updating device.hw properties."""
        hw_om = ObjectMap({
            "compname": "hw",
            "totalMemory": 45097156608,
            })

        changed = self.service.remote_applyDataMaps(self.device.id, [hw_om])
        self.assertTrue(changed, "device.hw not changed by first ObjectMap")

        self.assertEqual(
            45097156608, self.device.hw.totalMemory,
            "device.hw.totalMemory not updated by ObjectMap")

        changed = self.service.remote_applyDataMaps(self.device.id, [hw_om])
        self.assertFalse(changed, "device.hw changed by duplicate ObjectMap")

    def test_updateComponent_implicit(self):
        """Test updating a component with implicit _add and _remove."""
        eth0_om = ObjectMap({
            "id": "eth0",
            "compname": "os",
            "relname": "interfaces",
            "modname": "Products.ZenModel.IpInterface",
            "speed": 10e9,
            })

        changed = self.service.remote_applyDataMaps(self.device.id, [eth0_om])
        self.assertTrue(changed, "eth0 not changed by first ObjectMap")

        self.assertEqual(
            1, self.device.os.interfaces.countObjects(),
            "wrong number of interfaces created by ObjectMap")

        self.assertEqual(
            10e9, self.device.os.interfaces.eth0.speed,
            "eth0.speed not updated by ObjectMap")

        changed = self.service.remote_applyDataMaps(self.device.id, [eth0_om])
        self.assertFalse(changed, "eth0 changed by duplicate ObjectMap")

    def test_updateComponent_addFalse(self):
        """Test updating a component with _add set to False."""
        eth0_om = ObjectMap({
            "id": "eth0",
            "compname": "os",
            "relname": "interfaces",
            "modname": "Products.ZenModel.IpInterface",
            "speed": 10e9,
            "_add": False,
            })

        changed = self.service.remote_applyDataMaps(self.device.id, [eth0_om])
        self.assertFalse(changed, "_add = False resulted in change")

        self.assertEqual(
            0, self.device.os.interfaces.countObjects(),
            "ObjectMap with _add = False created a component")

    def test_updatedComponent_removeTrue(self):
        """Test updating a component with _remove or remove set to True."""
        for remove_key in ('_remove', 'remove'):
            eth0_om = ObjectMap({
                "id": "eth0",
                "compname": "os",
                "relname": "interfaces",
                remove_key: True,
                })

            changed = self.service.remote_applyDataMaps(self.device.id, [eth0_om])
            self.assertFalse(
                changed,
                "{} = True resulted in change".format(remove_key))

            self.service.remote_applyDataMaps(self.device.id, [
                ObjectMap({
                    "id": "eth0",
                    "compname": "os",
                    "relname": "interfaces",
                    "modname": "Products.ZenModel.IpInterface",
                    "speed": 10e9,
                    })])

            changed = self.service.remote_applyDataMaps(self.device.id, [eth0_om])
            self.assertTrue(
                changed,
                "{} = True didn't result in change".format(remove_key))

            self.assertEqual(
                0, self.device.os.interfaces.countObjects(),
                "{} = True didn't remove the component".format(remove_key))

    def test_updateRelationship(self):
        """Test relationship creation."""
        rm = RelationshipMap(
            compname="os",
            relname="interfaces",
            modname="Products.ZenModel.IpInterface",
            objmaps=[
                ObjectMap({"id": "eth0"}),
                ObjectMap({"id": "eth1"}),
                ])

        changed = self.service.remote_applyDataMaps(self.device.id, [rm])
        self.assertTrue(
            changed,
            "device.os.interfaces not changed by first RelationshipMap")

        self.assertEqual(
            2, self.device.os.interfaces.countObjects(),
            "wrong number of interfaces created by first RelationshipMap")

        changed = self.service.remote_applyDataMaps(self.device.id, [rm])
        self.assertFalse(
            changed,
            "device.os.interfaces changed by second RelationshipMap")

        rm.maps = rm.maps[:1]
        changed = self.service.remote_applyDataMaps(self.device.id, [rm])
        self.assertTrue(
            changed,
            "device.os.interfaces not changed by trimmed RelationshipMap")

        self.assertEquals(
            1, self.device.os.interfaces.countObjects(),
            "wrong number of interfaces after trimmed RelationshipMap")

        rm.maps = []
        changed = self.service.remote_applyDataMaps(self.device.id, [rm])
        self.assertTrue(
            changed,
            "device.os.interfaces not changed by empty RelationshipMap")

        self.assertEquals(
            0, self.device.os.interfaces.countObjects(),
            "wrong number of interfaces after empty RelationshipMap")
