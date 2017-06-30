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
    """Return new Deferred that will errback TimeoutError after seconds."""
    deferred_with_timeout = defer.Deferred()

    def fire_timeout():
        deferred.cancel()

        if not deferred_with_timeout.called:
            deferred_with_timeout.errback(exception_class())

    delayed_timeout = reactor.callLater(seconds, fire_timeout)

    def handle_result(result):
        # Cancel the timeout if it hasn't yet occurred.
        if delayed_timeout.active():
            delayed_timeout.cancel()

        if isinstance(result, failure.Failure):
            # Stop the errback chain if deferred was canceled by timeout.
            if isinstance(result.value, defer.CancelledError):
                return

            # Propagate other errors.
            deferred_with_timeout.errback(exception_class())
        else:
            # Propagate all good results.
            deferred_with_timeout.callback(result)

    deferred.addBoth(handle_result)

    return deferred_with_timeout


def sleep(seconds):
    """Return a Deferred that is called in given seconds."""
    d = defer.Deferred()
    reactor.callLater(seconds, d.callback, None)
    return d
