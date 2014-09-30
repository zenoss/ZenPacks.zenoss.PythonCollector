##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

# Logging
import logging
log = logging.getLogger('zen.python')

from decimal import Decimal


def get_dp_values(input_values):
    """Generate (value, timestamp) tuples suitable for storing.

    The following 'input_values' types are supported:

    1. int: 123
    2. float: 123.4
    3. numeric string: '123.4'
    4. Decimal: Decimal('123')
    5. above with 'N' timestamp: (123, 'N')
    6. above with int timestamp: (123.4, 1404160028)
    7. above with float timestamp: ('123.4', 1404160028.789839)
    8. list or tuple of above::

        [
            123, 123.4, '123.4',
            (123, 'N'), (123.4, 1404160028), ('123.4', 1404160028.789839),
        ]
    """
    is_value = lambda x: isinstance(x, (basestring, float, int, long))
    is_decimal = lambda x: isinstance(x, Decimal)
    is_timestamp = lambda x: get_dp_ts(x) is not None
    is_value_ts = lambda x: isinstance(x, (list, tuple)) and len(x) == 2 and is_value(x[0]) and is_timestamp(x[1])
    is_value_list = lambda x: isinstance(x, (list, tuple))

    # Input types 1-3.
    if is_value(input_values):
        yield (input_values, 'N')

    # Input type 4
    elif is_decimal(input_values):
        yield (str(input_values), 'N')

    # Input types 5-7.
    elif is_value_ts(input_values):
        yield (input_values[0], get_dp_ts(input_values[1]))

    # Input type 8.
    elif is_value_list(input_values):
        for input_value in input_values:
            for value in get_dp_values(input_value):
                yield value

    else:
        log.warn('attempted to store invalid values: %r', input_values)


def get_dp_ts(ts):
    """Return ts converted to int or 'N' if applicable.

    Return None if ts is not a valid timestamp.
    """
    if ts is None or ts in ('N', 'n'):
        return 'N'

    try:
        return int(float(ts))
    except Exception:
        return
