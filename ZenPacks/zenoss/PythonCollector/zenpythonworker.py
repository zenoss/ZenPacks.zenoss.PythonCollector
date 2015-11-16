##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################


import Globals
from Products.DataCollector.Plugins import loadPlugins
from Products.ZenUtils.Utils import unused, zenPath
from Products.ZenUtils.ZCmdBase import ZCmdBase

from twisted.spread import pb
from twisted.internet import defer, reactor, error

import cPickle as pickle
import time
import signal
import os

IDLE = "None/None"


class zenpythonworker(ZCmdBase, pb.Referenceable):
    "Execute ZenPython requests in separate process"

    def __init__(self):
        ZCmdBase.__init__(self)

        self.current = IDLE
        self.currentStart = 0

        try:
            self.log.debug("establishing SIGUSR2 signal handler")
            signal.signal(signal.SIGUSR2, self.sighandler_USR2)
        except ValueError:
            # If we get called multiple times, this will generate an exception:
            # ValueError: signal only works in main thread
            # Ignore it as we've already set up the signal handler.
            pass

        self.zem = self.dmd.ZenEventManager
        loadPlugins(self.dmd)
        self.pid = os.getpid()

    def audit(self, action):
        """
        zenpythonworkers restart all the time, it is not necessary to audit log it.
        """
        pass

    def sighandler_USR2(self, *args):
        self.reportStats()

    def reportStats(self):
        now = time.time()
        if self.current != IDLE:
            self.log.debug("(%d) Currently performing %s, elapsed %.2f s",
                            self.pid, self.current, now-self.currentStart)
        else:
            self.log.debug("(%d) Currently IDLE", self.pid)


if __name__ == '__main__':
    zpw = zenpythonworker()
    reactor.run()