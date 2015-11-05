##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from Products.ZenTestCase.BaseTestCase import BaseTestCase

from ZenPacks.zenoss.PythonCollector import zenpython


class TestZenPython(BaseTestCase):
    '''
    Test suite for ZenPython.
    '''
    def afterSetUp(self):
        pass

    def test_constants(self):
        self.assertTrue(hasattr(zenpython, 'WRITERRD_ARGS'))

def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestZenPython))
    return suite
