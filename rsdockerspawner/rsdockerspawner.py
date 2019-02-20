# -*- coding: utf-8 -*-
u"""subclass docker spawner

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from dockerspawner import dockerspawner
from pykern import pkcollections
from pykern import pkio
from pykern.pkdebug import pkdp
import docker
import glob
import socket
import tornado
import traitlets


_PORT_LABEL = 'rsdockerspawner_port'


class RSDockerSpawner(dockerspawner.DockerSpawner):

    tls_dir = traitlets.Unicode('', config=True)
    servers_per_host = traitlets.Int(1, config=True)

    __slot = None

    __slots = []

    __traits = pkcollections.Dict()

    __client = None

    @property
    def client(self):
        if self.__client is None:
            self.__allocate_slot()
            self.__client = self.__docker_client(self.__slot.host)
        return self.__client

    @tornado.gen.coroutine
    def create_object(self, *args, **kwargs):
        self.__allocate_slot()
        self.extra_create_kwargs = {'labels': {_PORT_LABEL: str(self.__slot.port)}}
        res = yield super(RSDockerSpawner, self).create_object(*args, **kwargs)
        return res

    def get_env(self, *args, **kwargs):
        res  = super(RSDockerSpawner, self).get_env(*args, **kwargs)
        res['RADIA_RUN_PORT'] = str(self.__slot.port)
        return res

    @tornado.gen.coroutine
    def get_ip_and_port(self):
        return (socket.gethostbyname(self.__slot.host), self.__slot.port)


    @tornado.gen.coroutine
    def get_object(self, *args, **kwargs):
        """Initializes the slots and state first time"""
        self.__allocate_slot()
        res = yield super(RSDockerSpawner, self).get_object(*args, **kwargs)
        if not res:
            self.__deallocate_slot()
        return res

    @tornado.gen.coroutine
    def remove_object(self, *args, **kwargs):
        res = yield super(RSDockerSpawner, self).get_object(*args, **kwargs)
        self.__deallocate_slot()
        return res

    def __allocate_slot(self):
        if self.__slot:
            return
        self.__init_class()
        self.__client = None
        s = self.__find_container(self.object_name)
        if not s:
            for s in self.__slots:
                if not s.cname:
                    break
            else:
                self.log.info('{} slots in use, no more slots', len(self.__slots))
                # copied from jupyter.handlers.base
                # The error message doesn't show up the first time, but will show up
                # if the user refreshes the browser.
                raise tornado.web.HTTPError(
                    429,
                    'No more servers available. Try again in a few minutes.',
                )
            self.__slot = s
        self.__slot.cname = self.object_name

    def __deallocate_slot(self):
        if not self.__slot:
            return
        self.__client = None
        self.__slot.cname = None
        self.__slot = None

    @classmethod
    def __docker_client(cls, host):
        k = {
            'version': 'auto',
            'base_url': 'tcp://{}:2376'.format(host),
        }
        d = pkio.py_path(cls.__traits.tls_dir).join(host)
        assert d.check(dir=True), \
            f'tls_dir/<host> does not exist: {d}'
        c = str(d.join('cert.pem'))
        k['tls'] = docker.tls.TLSConfig(
            client_cert=(c, str(d.join('key.pem'))),
            ca_cert=c,
            verify=True,
        )
        return docker.APIClient(**k)

    @classmethod
    def __find_container(cls, cname):
        for s in cls.__slots:
            if s.cname == cname:
                return s
        return None

    @classmethod
    def __find_slot(cls, host, port):
        for s in cls.__slots:
            if s.host == host and s.port == port:
                return s
        return None

    def __init_class(self):
        if self.__slots:
            return
        cls = self.__class__
        # easiest way to access traits from a class
        cls.__traits.update(
            tls_dir=self.tls_dir,
            servers_per_host=self.servers_per_host,
            port=self.port,
        )
        t = cls.__traits
        hosts = []
        for i in pkio.py_path(t.tls_dir).listdir():
            if i.join('key.pem'):
                hosts.append(i.basename)
        slots = cls.__init_slots(hosts)
        cls.__init_containers(slots, hosts)
        cls.__slots.extend(slots)
        self.log.info(
            'hosts=%s slots=%s slots_in_use=%s',
            ' '.join(hosts),
            len(slots),
            len([x for x in slots if x.cname]),
        )

    @classmethod
    def __init_containers(cls, slots, hosts):
        c = None
        for h in hosts:
            d = cls.__docker_client(h)
            for c in d.containers(all=True):
                if _PORT_LABEL not in c['Labels']:
                    # not ours
                    continue
                p = int(c['Labels'][_PORT_LABEL])
                s = cls.__find_slot(h, p)
                n = c['Names'][0]
                i = c['Id']
                if s and c['State'] == 'running' and not cls.__find_container(n):
                    s.cname = n
                    continue
                # not running, duplicate, or port config changed
                try:
                    d.stop(i)
                except Exception:
                    pass
                try:
                    d.remove_container(i)
                except Exception:
                    pass


    @classmethod
    def __init_slots(cls, hosts):
        res = []
        t = cls.__traits
        for h in hosts:
            for p in range(t.port, t.port + t.servers_per_host):
                res.append(
                    pkcollections.Dict(
                        cname=None,
                        host=h,
                        port=p,
                    ),
                )
        # sort by port first so we distribute servers across hosts
        return sorted(res, key=lambda x: str(x.port) + x.host)
