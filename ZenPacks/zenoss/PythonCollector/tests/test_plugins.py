##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from Products.ZenTestCase.BaseTestCase import BaseTestCase

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource \
    import PythonDataSourcePlugin


class TestPythonPlugin(BaseTestCase):
    '''
    Test suite for PythonDataSourcePlugin.
    '''
    def afterSetUp(self):
        self.plugin = PythonDataSourcePlugin()

    def test_classmethods(self):
        self.assertTrue(hasattr(PythonDataSourcePlugin, 'config_key'))
        self.assertTrue(hasattr(PythonDataSourcePlugin, 'params'))

    def test_properties(self):
        self.assertTrue(hasattr(self.plugin, 'proxy_attributes'))
        self.assertTrue(hasattr(self.plugin, 'is_blocking'))
        self.assertTrue(hasattr(self.plugin, 'cleanup'))

    def test_new_data(self):
        new_data = self.plugin.new_data()
        self.assertTrue('values' in new_data)
        self.assertTrue('maps' in new_data)
        self.assertTrue('events' in new_data)

    def test_methods(self):
        plugin = self.plugin
        self.assertEqual(plugin.collect({}), NotImplementedError)
        self.assertEqual(plugin.onResult([], {}), [])
        self.assertEqual(plugin.onSuccess([], {}), [])
        self.assertEqual(plugin.onError([], {}), [])
        self.assertEqual(plugin.onComplete([], {}), [])

def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestPythonPlugin))
    return suite
