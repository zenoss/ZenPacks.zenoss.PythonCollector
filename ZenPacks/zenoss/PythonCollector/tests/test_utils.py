##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

# stdlib Imports
import unittest

# ZenPack Imports
from ..utils import get_dp_values


class TestGetDPValues(unittest.TestCase):

    def test_str(self):
        value = '10'
        results = list(get_dp_values(value))
        self.assertEqual(results, [('10', 'N')])

    def test_int(self):
        value = 10
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N')])

    def test_float(self):
        value = 10.1
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10.1, 'N')])

    def test_tuple(self):
        value = (10, 'N')
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N')])

    def test_tuples(self):
        value = ((10, 'N'), (11, 123))
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N'), (11, 123)])

    def test_int_and_tuple(self):
        value = (10, (11, 123))
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N'), (11, 123)])

    def test_list(self):
        value = [10, 'N']
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N')])

    def test_lists(self):
        value = [[10, 'N'], [11, 123]]
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N'), (11, 123)])

    def test_lists2(self):
        value = [[10, 'N'], [11, '123']]
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N'), (11, 123)])

    def test_lists3(self):
        value = [[10, 'N'], [11, 123.0]]
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N'), (11, 123.0)])

    def test_int_and_list(self):
        value = [10, [11, 123]]
        results = list(get_dp_values(value))
        self.assertEqual(results, [(10, 'N'), (11, 123)])


if __name__ == '__main__':
    unittest.main()
