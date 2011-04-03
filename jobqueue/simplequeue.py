import os
import threading
import Queue
from multiprocessing import Process

from . import runjob
from .jobid import get_jobid

class JobQueue(object):
    def __init__(self):
        self._lock = threading.Lock()
        self._nextjob = threading.Event()
        self._jobs = []
        self._pending = []
        self._info = {}
        self._status = {}
        self._result = {}
        self._jobmonitor = threading.Thread(target=self.run_queue)
        self._jobmonitor.start()
        self._current_id = None
        self._pending_cleanup = Queue.Queue()
    def run_queue(self):
        while True:
            self._nextjob.wait()
            with self._lock:
                if not self._pending:
                    self._nextjob.clear()
                    continue
                self._current_id = self._pending.pop(0)
                self._status[self._current_id] = 'ACTIVE'
                request = self._info[self._current_id]
                self._stopping = None
                self._current_process = Process(target=runjob.run_one,
                                                args=(self._current_id,request))
            self._current_process.start()
            self._current_process.join()
            result = runjob.fetch_result(self._current_id)
            with self._lock:
                self._result[self._current_id] = result
                self._status[self._current_id] = result['status']

            # Process directory cleanup in the work thread
            while not self._pending_cleanup.empty():
                id = self._pending_cleanup.get()
                runjob.clean_result(id)

    def list_jobs(self, status=None):
        with self._lock:
            if status is None:
                result = self._jobs[:]
            else:
                result = [j for j in self._jobs if self._status[j] == status]
        return result
    def submit(self, request):
        with self._lock:
            id = int(get_jobid())
            request['id'] = id
            self._jobs.append(id)
            self._info[id] = request
            self._status[id] = 'PENDING'
            self._result[id] = {'status':'PENDING'}
            self._pending.append(id)
            self._nextjob.set()
        return id
    def results(self, id):
        with self._lock:
            return self._result.get(id,{'status':'UNKNOWN'})
    def status(self, id):
        with self._lock:
            return self._status.get(id,'UNKNOWN')
    def info(self, id):
        with self._lock:
            return self._info[id]
    def stop(self, id):
        with self._lock:
            try: self._pending.remove(id)
            except ValueError: pass
            if self._current_id == id and not self._stopping == id:
                self._stopping = id
                self._current_process.terminate()
            self._status[id] = 'CANCEL'
    def delete(self, id):
        self.stop(id)
        with self._lock:
            try: self._jobs.remove(id)
            except ValueError: pass
            self._info.pop(id, None)
            self._result.pop(id, None)
            self._status.pop(id, None)
            self._pending_cleanup.put(id)