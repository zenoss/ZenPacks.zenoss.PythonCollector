##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

# These are the only symbols that should be used outside the module.
__all__ = ['start', 'timeout', 'set_timeout_file', 'get_timeout_entries']


import logging
LOG = logging.getLogger('zen.watchdog')

import contextlib
import os
import sys
import threading
import time


def start():
    Thread().start()


@contextlib.contextmanager
def timeout(seconds, name):
    Thread.start_timer(name, seconds)
    try:
        yield
    finally:
        Thread.clear_timer()


def set_timeout_file(timeout_file):
    Thread.timeout_file = timeout_file


def get_timeout_entries(timeout_file=None):
    return Thread.get_timeout_entries(timeout_file=timeout_file)


class Thread(threading.Thread):

    # Name the thread in case it appears in tracebacks.
    name = 'watchdog'

    # This causes the thread to die when the main thread exits.
    daemon = True

    # Where operations that timed out are persisted between restarts.
    timeout_file = None

    # Details about the currently running operation.
    op_name = None
    op_timestamp = None
    op_timeout = None

    def run(self):
        LOG.debug("started")
        cls = self.__class__

        while True:
            # Wait to check for blocking until the timeout expires.
            if all([cls.op_name, cls.op_timestamp, cls.op_timeout]):
                timeout_time = cls.op_timestamp + cls.op_timeout
                until_timeout = timeout_time - time.time()

                if until_timeout > 0:
                    time.sleep(until_timeout)

                if cls.op_blocked():
                    LOG.warning("timeout for %s", cls.op_name)
                    cls.append_timeout_entry()
                    LOG.warning("restarting process")
                    self.restart_process()

            # Wait for a second if no timer is currently running.
            else:
                time.sleep(1)

    @classmethod
    def start_timer(cls, name, seconds):
        if seconds and seconds > 0:
            cls.op_name = name
            cls.op_timestamp = time.time()
            cls.op_timeout = seconds

    @classmethod
    def clear_timer(cls):
        cls.op_name = None
        cls.op_timestamp = None
        cls.op_timeout = None

    @classmethod
    def restart_process(cls):
        try:
            os.execv(sys.argv[0], sys.argv)
        except Exception as e:
            LOG.error("failed to restart process: %s", e)

            # Reset op_timestamp to now. Otherwise we could get stuck in a
            # tight loop forever trying to kill the process when we can't for
            # some persistent reason. At least this way we will only attempt
            # to restart the process at op_timeout intervals.
            cls.op_timestamp = time.time()

    @classmethod
    def append_timeout_entry(cls):
        if not cls.timeout_file or not cls.op_name:
            return

        state = cls.get_timeout_entries()
        state.add(cls.op_name)

        try:
            with open(cls.timeout_file, 'w') as f:
                f.write('{}\n'.format('\n'.join(state)))
        except Exception as e:
            LOG.error(
                "failed to add %s to %s: %s",
                cls.op_name, cls.timeout_file,
                e)
        else:
            LOG.warning("added %s to %s", cls.op_name, cls.timeout_file)

    @classmethod
    def get_timeout_entries(cls, timeout_file=None):
        if timeout_file:
            cls.timeout_file = timeout_file

        state = set()

        if not cls.timeout_file:
            return state

        try:
            with open(cls.timeout_file, 'r') as f:
                for line in f:
                    state.add(line.strip())
        except Exception:
            pass

        return state

    @classmethod
    def op_blocked(cls):
        if not cls.op_name or not cls.op_timeout:
            return False

        if (time.time() - cls.op_timestamp) > cls.op_timeout:
            return True

        return False
