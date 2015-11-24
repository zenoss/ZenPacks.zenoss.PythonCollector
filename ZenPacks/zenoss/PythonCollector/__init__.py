##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import Globals  # noqa

import logging
LOG = logging.getLogger('zen.PythonCollector')

import os

from Products.ZenModel.ZenPack import ZenPack as ZenPackBase
from Products.ZenUtils.Utils import unused


class ZenPack(ZenPackBase):
    def install(self, app):
        # Our objects.xml assumes the /Zenoss OSProcessOrganizer already
        # exists. It might not, so we have to create it before calling
        # super.
        app.getDmdRoot('Processes').createOrganizer('Zenoss')

        super(ZenPack, self).install(app)

        # zenpython.py must be executable for its optional watchdog to
        # succesfully restart it.
        try:
            os.system('chmod 0755 {}'.format(self.path('zenpython.py')))
        except Exception as e:
            LOG.error("failed to make zenpython.py executable: %s", e)


# Patch last to avoid import recursion problems.
from ZenPacks.zenoss.PythonCollector import patches
unused(patches)
