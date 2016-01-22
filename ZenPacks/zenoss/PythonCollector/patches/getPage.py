##############################################################################
#
# Copyright (C) Zenoss, Inc. 2016, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import twisted.web.client as txwebclient

from Products.ZenUtils.Utils import monkeypatch, unused
from ZenPacks.zenoss.PythonCollector.web.semaphores import getOverallDeferredSemaphore

unused(txwebclient)


@monkeypatch('twisted.web.client')
def getPage(*args, **kwargs):

    # Overall limit on concurrent queries
    semaphore = getOverallDeferredSemaphore()

    # original is injected by the @monkeypatch decorator.
    return semaphore.run(original, *args, **kwargs)
