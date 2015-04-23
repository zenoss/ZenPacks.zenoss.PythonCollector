##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################
import collections
from twisted.internet import defer

class BaseDataMapQueue(object):

    def __init__(self, maxlen):
        self.maxlen = maxlen

    def append(self, datamap):
        """
        Appends the datamap to the queue.

        @param datamap: The datamap.
        @return: If the queue is full, this will return the oldest event
                 which was discarded when this datamap was added.
        """
        raise NotImplementedError()

    def popleft(self):
        """
        Removes and returns the oldest datamap from the queue. If the queue
        is empty, raises IndexError.

        @return: The oldest datamap from the queue.
        @raise IndexError: If the queue is empty.
        """
        raise NotImplementedError()

    def extendleft(self, datamaps):
        """
        Appends the datamaps to the beginning of the queue (they will be the
        first ones removed with calls to popleft). The list of datamaps are
        expected to be in order, with the earliest queued datamaps listed
        first.

        @param datamaps: The datamaps to add to the beginning of the queue.
        @type datamaps: list
        @return A list of discarded datamaps that didn't fit on the queue.
        @rtype list
        """
        raise NotImplementedError()

    def __len__(self):
        """
        Returns the length of the queue.

        @return: The length of the queue.
        """
        raise NotImplementedError()

    def __iter__(self):
        """
        Returns an iterator over the elements in the queue (oldest datamaps
        are returned first).
        """
        raise NotImplementedError()

class DequeDataMapQueue(BaseDataMapQueue):
    """
    Event queue implementation backed by a deque. This queue does not
    perform de-duplication of datamaps.
    """

    def __init__(self, maxlen):
        super(DequeDataMapQueue, self).__init__(maxlen)
        self.queue = collections.deque()

    def append(self, datamap):
        discarded = None
        if len(self.queue) == self.maxlen:
            discarded = self.popleft()
        self.queue.append(datamap)
        return discarded

    def popleft(self):
        return self.queue.popleft()

    def extendleft(self, datamaps):
        if not datamaps:
            return datamaps
        available = self.maxlen - len(self.queue)
        if not available:
            return datamaps
        to_discard = 0
        if available < len(datamaps):
            to_discard = len(datamaps) - available
        self.queue.extendleft(reversed(datamaps[to_discard:]))
        return datamaps[:to_discard]

    def __len__(self):
        return len(self.queue)

    def __iter__(self):
        return iter(self.queue)

class DataMapQueueManager(object):

    def __init__(self, options, log):
        self.options = options
        self.log = log
        self.discarded_datamaps = 0

        self._initQueue()

    def _initQueue(self):
        maxlen = self.options.maxdatamapqueuelen
        #queue_type = DeDupingEventQueue if self.options.deduplicate_events \
        #    else DequeEventQueue
        queue_type = DequeDataMapQueue
        self.datamap_queue = queue_type(maxlen)

    def _addDataMaps(self, queue, device, devClass, datamaps):
        discarded = queue.append([device, devClass, datamaps])
        self.log.debug("Queued datamap (total of %d) %r", len(queue), [device, devClass, datamaps])

        if discarded:
            self.log.debug("Discarded datamap - queue overflow: %r", discarded)
            self.discarded_datamaps += 1

    def addDataMaps(self, device, devClass, datamaps):
        self._addDataMaps(self.datamap_queue, device, devClass, datamaps)

    @defer.inlineCallbacks
    def applyDataMaps(self, datamap_sender_fn):
        # Create new queue - we will flush the current queue and don't want to
        # get in a loop sending datamaps that are queued while we send this batch
        # ( the datamap sending is asynchronous).
        prev_datamap_queue = self.datamap_queue
        self._initQueue()
        datamaps = []

        try:
            def chunk_datamaps():
                chunk_remaining = self.options.datamapflushchunksize

                datamaps = []
                num_datamaps = min(chunk_remaining, len(prev_datamap_queue))
                for i in xrange(num_datamaps):
                    datamaps.append(prev_datamap_queue.popleft())
                return datamaps

            datamaps = chunk_datamaps()
            while datamaps:
                self.log.debug(
                   "Sending %d datamaps", len(datamaps))
                yield datamap_sender_fn(datamaps, True)
                datamaps = chunk_datamaps()

        except Exception, ex:
            # Restore datamaps that failed to send
            # Restore events that failed to send
            datamaps.extend(prev_datamap_queue)
            discarded_datamaps = self.datamap_queue.extendleft(datamaps)
            self.discarded_datamaps += len(discarded_datamaps)

    @property
    def datamap_queue_length(self):
        return len(self.datamap_queue)
