##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import unittest
from ZenPacks.zenoss.PythonCollector.zenpython import checkInputs

class TestConvertFunction(unittest.TestCase):

    def test_str(self):
        value = '10'
        results = checkInputs(value)
        self.assertEqual(results, ('10', 'N'))
    
    def test_int(self):
        value = 10
        results = checkInputs(value)
        self.assertEqual(results, (10, 'N'))

    def test_float(self):
        value = 10.1
        results = checkInputs(value)
        self.assertEqual(results, (10.1, 'N'))

    def test_list(self):
        value = [10,'N']
        results = checkInputs(value)
        self.assertEqual(results, [10, 'N'])

    def test_tuple(self):
        value = (10,'N')
        results = checkInputs(value)
        self.assertEqual(results, (10, 'N'))

    def test_bad_tuple(self):
        value = (10,1,'N')
        results = checkInputs(value)
        self.assertEqual(results, [])

    def test_nested_tuple(self):
        value = ((10,'N'), (11, 123))
        results = checkInputs(value)
        self.assertEqual(results, ((10,'N'), (11, 123)))

    def test_checkInputs_nested_tuple(self):
        value = (10, (11, 123))
        results = checkInputs(value)
        self.assertEqual(results, ((10,'N'), (11, 123)))
    
    def test_nested_dict(self):
        value = [[10,'N'], [11, 123]]
        results = checkInputs(value)
        self.assertEqual(results, [[10,'N'], [11, 123]])
    
    def test_nested_dict2(self):
        value = [[10,'N'], [11, '123']]
        results = checkInputs(value)
        self.assertEqual(results, [[10,'N'], [11, '123']])

    def test_nested_dict3(self):
        value = [[10,'N'], [11, 123.0]]
        results = checkInputs(value)
        self.assertEqual(results, [[10,'N'], [11, 123.0]])

    def test_checkInputs_nested_dict(self):
        value = [10, [11, 123]]
        results = checkInputs(value)
        self.assertEqual(results, [(10,'N'), [11, 123]])

    def test_checkInputs_nested_dict_invalid(self):
        value = [10, [11, 123, 12]]
        results = checkInputs(value)
        self.assertEqual(results, [])

if __name__ == '__main__':
    unittest.main()
