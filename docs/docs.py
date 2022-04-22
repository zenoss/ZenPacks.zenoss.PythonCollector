#! /usr/bin/env python

import re

try:

    with open('/tmp/README.html', 'r') as file:
        html = file.read()

    html = re.sub('images/', '/sites/default/files/zenpack/PythonCollector/', html)

    with open('/tmp/README.html', 'w') as file:
        file.write(html)

except Exception as ex:

    print "Error filtering html"
