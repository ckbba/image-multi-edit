import os
import time


def serve(connection, settings):
    connection.send({'ready': True})
    while True:
        request = connection.recv()
        if request['method'] == 'stop':
            return
        if request['method'] == 'crash':
            os._exit(91)
        if request['method'] == 'hang':
            time.sleep(30)
        connection.send({'ok': True, 'result': {'method': request['method'], 'pid': os.getpid()}})