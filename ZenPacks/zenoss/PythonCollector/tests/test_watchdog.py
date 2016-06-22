#!/usr/bin/env python
##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""Tests for watchdog module."""

import Globals  # NOQA: imported for side effects.

import argparse
import os
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest

from ZenPacks.zenoss.PythonCollector import watchdog


class TestWatchdog(unittest.TestCase):

    def test_start_then_exit(self):
        """Start and exit with a watchdog started.

        We have a problem with the watchdog thread not terminating with the
        main thread if this doesn't exit quickly with ExitCode.OK.

        """
        exitcode, _, _ = Scenario.run("start_then_exit")
        self.assertEquals(exitcode, ExitCode.OK)

    def test_start_then_ctrlc(self):
        """Start then simulate a CTRL-C (KeyboardInterrupt).

        We have a problem with the watchdog thread not terminating with the
        main thread if this doesn't exit quickly with ExitCode.INTERRUPTED.

        """
        exitcode, _, _ = Scenario.run("start_then_ctrlc")
        self.assertEquals(exitcode, ExitCode.INTERRUPTED)

    def test_complete_before_timeout(self):
        """Run an operation that will complete before the watchdog.timeout().

        We have a problem with the watchdog being too aggressive if this
        doesn't exit with ExitCode.OK. An ExitCode.KILLED would indicate that
        the watchdog is repeatedly restarting the process so it can't reach
        its own exit.

        """
        exitcode, _, _ = Scenario.run("complete_before_timeout")
        self.assertEquals(exitcode, ExitCode.OK)

    def test_timeout_before_complete(self):
        """Run an operation that will exceed the watchdog.timeout().

        Our scenario will kill the process and cause an ExitCode.KILLED if
        this is functioning correctly because the watchdog will continually
        restart the process and not let it get to its own exit.

        We have a problem with the watchdog not restarting the if this results
        in ExitCode.NOT_RESTARTED.

        """
        exitcode, _, _ = Scenario.run("timeout_before_complete")
        self.assertEquals(exitcode, ExitCode.KILLED)

    def test_timeout_file(self):
        """Run and persist an operation that will exceed watchdog.timeout().

        Our scenario will result in ExitCode.OK only if the watchdog correctly
        stores the operation resulting in a timeout, restarts the process, and
        is able to read the correct operation name from timeout_file.

        We have a problem with the watchdog not restarting the process if this
        results in ExitCode.NOT_RESTARTED.

        We have a problem with the persisting and retrieval of the operation
        that timed out if this results in ExitCode.KILLED.

        """
        exitcode, _, _ = Scenario.run("timeout_file")
        self.assertEquals(exitcode, ExitCode.OK)


class Scenario(object):

    """Scenarios used in TestWatchdog test case.

    The watchdog can only be observed and tested if its running in external
    processes. The following scenarios should all be run via "run" so they
    run in an external process.

    """

    @staticmethod
    def ensure_runnable(file):
        st = os.stat(file)
        xa = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        os.chmod(file, st.st_mode | xa)

    @staticmethod
    def run(scenario, seconds=5):
        """Run named scenario in another process. Kill it after seconds.

        Returns (exitcode, stdout, stderr)

        """
        src_file = __file__
        if src_file.endswith('.pyc'):
            src_file = os.path.splitext(__file__)[0]+'.py'
        Scenario.ensure_runnable(src_file)
        p = subprocess.Popen(
            [src_file, '--scenario', scenario],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        timer = threading.Timer(seconds, p.kill)
        try:
            timer.start()
            stdout, stderr = p.communicate()
        finally:
            timer.cancel()

        # The test runner complains about thread being left behind without
        # this sleep.
        time.sleep(0.1)

        return (p.returncode, stdout, stderr)

    @staticmethod
    def start_then_exit():
        """Start watchdog thread then exit."""
        watchdog.start()

        # Verify that watchdog did start.
        for thread in threading.enumerate():
            if thread.name == 'watchdog':
                sys.exit(ExitCode.OK)

        sys.exit(ExitCode.WATCHDOG_NOT_RUNNING)

    @staticmethod
    def start_then_ctrlc():
        """Start the watchdog thread then simulate a CTRL-C."""
        watchdog.start()
        raise KeyboardInterrupt
        sys.exit(ExitCode.OK)

    @staticmethod
    def complete_before_timeout():
        """Complete opertion before timeout occurs."""
        watchdog.start()
        with watchdog.timeout(10, "complete_before_timeout"):
            time.sleep(0.1)

        sys.exit(ExitCode.OK)

    @staticmethod
    def timeout_before_complete():
        """Timeout before operation completes."""
        watchdog.start()
        with watchdog.timeout(1, "timeout_before_complete"):
            time.sleep(2)

        sys.exit(ExitCode.NOT_RESTARTED)

    @staticmethod
    def timeout_file():
        """Validate operation timeout is recorded and we're restarted."""
        timeout_file = os.path.join(
            tempfile.gettempdir(),
            'test_watchdog.timeouts')

        entries = watchdog.get_timeout_entries(timeout_file=timeout_file)
        if os.path.isfile(timeout_file):
            os.unlink(timeout_file)

        if 'timeout_file' in entries:
            sys.exit(ExitCode.OK)
        else:
            watchdog.start()
            with watchdog.timeout(1, 'timeout_file'):
                time.sleep(2)

            sys.exit(ExitCode.NOT_RESTARTED)


class ExitCode(object):
    KILLED = -9
    OK = 0
    INTERRUPTED = 1
    WATCHDOG_NOT_RUNNING = 2
    NOT_RESTARTED = 3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--scenario", help="the scenario to run")
    args = parser.parse_args()

    if args.scenario:
        func = getattr(Scenario, args.scenario, None)
        if not func:
            sys.exit("{} is not a valid scenario.".format(args.scenario))
        else:
            func()
    else:
        unittest.main()


if __name__ == '__main__':
    main()
