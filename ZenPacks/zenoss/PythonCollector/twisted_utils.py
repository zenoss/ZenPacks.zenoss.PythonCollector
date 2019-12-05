##############################################################################
#
# Copyright (C) Zenoss, Inc. 2017, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Utilities used with Twisted."""

from twisted.internet import defer, error, reactor
from twisted.python import failure


def add_timeout(deferred, seconds, exception_class=error.TimeoutError):
    """Timeout deferred by scheduling it to be cancelled after seconds."""
    timed_out = [False]

    def fire_timeout():
        timed_out[0] = True
        deferred.cancel()

    delayed_timeout = reactor.callLater(seconds, fire_timeout)

    def handle_result(result):
        if timed_out[0]:
            if isinstance(result, failure.Failure):
                result.trap(defer.CancelledError)
                raise exception_class()

        return result

    deferred.addBoth(handle_result)

    def cancel_timeout(result):
        if delayed_timeout.active():
            delayed_timeout.cancel()

        return result

    deferred.addBoth(cancel_timeout)

    return deferred


def sleep(seconds):
    """Return a Deferred that is called in given seconds."""
    d = defer.Deferred()
    reactor.callLater(seconds, d.callback, None)
    return d
