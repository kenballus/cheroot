"""Command line tool for starting a Cheroot WSGI/HTTP server instance.

Basic usage::

    # Start a server on 127.0.0.1:8000 with the default settings
    # for the WSGI app myapp/wsgi.py:application()
    cheroot myapp.wsgi

    # Start a server on 0.0.0.0:9000 with 8 threads
    # for the WSGI app myapp/wsgi.py:main_app()
    cheroot myapp.wsgi:main_app --bind 0.0.0.0:9000 --threads 8

    # Start a server for the cheroot.server.Gateway subclass
    # myapp/gateway.py:HTTPGateway
    cheroot myapp.gateway:HTTPGateway

    # Start a server on the UNIX socket /var/spool/myapp.sock
    cheroot myapp.wsgi --bind /var/spool/myapp.sock

    # Start a server on the abstract UNIX socket CherootServer
    cheroot myapp.wsgi --bind @CherootServer
"""

import argparse
from importlib import import_module
import os
import sys
import contextlib

import six

from . import server
from . import wsgi


class BindLocation(object):
    """A class for storing the bind location for a Cheroot instance."""

    def __init__(
        self, address=None, port=None, file_socket=None, abstract_socket=None
    ):
        """Initialize BindLocation instance.

        Args:
            address (str): Host name or IP address
            port (int): TCP port number
            file_socket (str): UNIX socket file path
            abstract_socket (str): Abstract UNIX socket name
        """
        self.address = address
        self.port = port
        self.file_socket = file_socket
        self.abstract_socket = abstract_socket

    @property
    def bind_addr(self):
        """Return the bind location as expected by cheroot.wsgi.Server."""
        return self._bind_addr() or self.file_socket or self._abstract_socket()

    def _bind_addr(self):
        if self.address is None or self.port is None:
            return

        return self.address, self.port

    def _abstract_socket(self):
        return self.abstract_socket and '\0{}'.format(self.abstract_socket)


class Application:
    @classmethod
    def resolve(cls, full_path):
        """Read WSGI app/Gateway path string and import application module."""
        mod_path, app_path = full_path.partition(':')
        app = getattr(import_module(mod_path), app_path or 'application')

        with contextlib.suppress(TypeError):
            if issubclass(app, server.Gateway):
                return Gateway(app)

        return cls(app)

    def __init__(self, wsgi_app):
        if not callable(wsgi_app):
            raise TypeError(
                'Application must be a callable object or '
                'cheroot.server.Gateway subclass'
            )
        self.wsgi_app = wsgi_app

    def server_args(self, parsed_args):
        args = {
            arg: value
            for arg, value in vars(parsed_args).items()
            if not arg.startswith('_') and value is not None
        }
        args.update(vars(self))
        return args

    def server(self, parsed_args):
        return wsgi.Server(**self.server_args())


class Gateway:
    def __init__(self, gateway_yo):
        self.gateway = gateway_yo

    def server(self, parsed_args):
        server_args = vars(self)
        server_args['bind_addr'] = parsed_args['bind_addr']
        if parsed_args.max is not None:
            server_args['maxthreads'] = parsed_args.max
        if parsed_args.numthreads is not None:
            server_args['minthreads'] = parsed_args.numthreads
        return server.HTTPServer(**server_args)


def parse_wsgi_bind_addr(bind_addr_string):
    """Convert bind address string to a BindLocation."""
    # try and match for an IP/hostname and port
    match = six.moves.urllib.parse.urlparse('//{}'.format(bind_addr_string))
    try:
        addr = match.hostname
        port = match.port
        if addr is not None or port is not None:
            return BindLocation(address=addr, port=port)
    except ValueError:
        pass

    # else, assume a UNIX socket path
    # if the string begins with an @ symbol, use an abstract socket
    if bind_addr_string.startswith('@'):
        return BindLocation(abstract_socket=bind_addr_string[1:])
    return BindLocation(file_socket=bind_addr_string)


_arg_spec = {
    '_wsgi_app': dict(
        metavar='APP_MODULE',
        type=Application.resolve,
        help='WSGI application callable or cheroot.server.Gateway subclass',
    ),
    '--bind': dict(
        metavar='ADDRESS',
        dest='bind_addr',
        type=parse_wsgi_bind_addr,
        default='127.0.0.1:8000',
        help='Network interface to listen on (default: 127.0.0.1:8000)',
    ),
    '--chdir': dict(
        metavar='PATH',
        type=os.chdir,
        help='Set the working directory',
    ),
    '--server-name': dict(
        dest='server_name',
        type=str,
        help='Web server name to be advertised via Server HTTP header',
    ),
    '--threads': dict(
        metavar='INT',
        dest='numthreads',
        type=int,
        help='Minimum number of worker threads',
    ),
    '--max-threads': dict(
        metavar='INT',
        dest='max',
        type=int,
        help='Maximum number of worker threads',
    ),
    '--timeout': dict(
        metavar='INT',
        dest='timeout',
        type=int,
        help='Timeout in seconds for accepted connections',
    ),
    '--shutdown-timeout': dict(
        metavar='INT',
        dest='shutdown_timeout',
        type=int,
        help='Time in seconds to wait for worker threads to cleanly exit',
    ),
    '--request-queue-size': dict(
        metavar='INT',
        dest='request_queue_size',
        type=int,
        help='Maximum number of queued connections',
    ),
    '--accepted-queue-size': dict(
        metavar='INT',
        dest='accepted_queue_size',
        type=int,
        help='Maximum number of active requests in queue',
    ),
    '--accepted-queue-timeout': dict(
        metavar='INT',
        dest='accepted_queue_timeout',
        type=int,
        help='Timeout in seconds for putting requests into queue',
    ),
}


def main():
    """Create a new Cheroot instance with arguments from the command line."""
    parser = argparse.ArgumentParser(
        description='Start an instance of the Cheroot WSGI/HTTP server.')
    for arg, spec in _arg_spec.items():
        parser.add_argument(arg, **spec)
    raw_args = parser.parse_args()

    # ensure cwd in sys.path
    '' in sys.path or sys.path.insert(0, '')

    # create a server based on the arguments provided
    raw_args._wsgi_app.server(raw_args).safe_start()
