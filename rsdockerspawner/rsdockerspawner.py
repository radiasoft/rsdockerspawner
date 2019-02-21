# -*- coding: utf-8 -*-
u"""subclass docker spawner

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from dockerspawner import dockerspawner
from pykern import pkcollections
from pykern import pkio
from pykern import pkjson
from pykern.pkdebug import pkdp
import docker
import glob
import socket
import tornado
import traitlets


#: container label for jupyter port
_PORT_LABEL = 'rsdockerspawner_port'

#: CPU Fair Scheduler (CFS) period (see below)
_CPU_PERIOD_US = 100000

#: dump the slots whenever an update happens
_SLOTS_FILE = 'rsdockerspawner_slots.json'

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
            self.__client = self.__docker_client(self.__slot.host)
        return self.__client

    @tornado.gen.coroutine
    def create_object(self, *args, **kwargs):
        self.__allocate_slot()
        self.extra_create_kwargs = {'labels': {_PORT_LABEL: str(self.__slot.port)}}
        if self.cpu_limit:
            self.extra_host_config = dict(
                # The unreleased docker.py has "nano_cpus", which is --cpus * 1e9.
                # Which gets converted to cpu_period and cpu_quota in Docker source:
                # https://github.com/moby/moby/blob/ec87479/daemon/daemon_unix.go#L142
                # Also read this:
                # https://www.kernel.org/doc/Documentation/scheduler/sched-bwc.txt
                # You can see the values with:
                # id=$(docker inspect --format='{{.Id}}' jupyter-vagrant)
                # fs=/sys/fs/cgroup/cpu/docker/$id
                # cat $fs/cpu.cfs_period_us
                # cat $fs/cpu.cfs_quota_us
                cpu_period=_CPU_PERIOD_US,
                cpu_quota=int(float(_CPU_PERIOD_US) * self.cpu_limit),
            )
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
        if not self.__allocate_slot(no_raise=True):
            return None
        res = yield super(RSDockerSpawner, self).get_object(*args, **kwargs)
        if not res:
            self.__deallocate_slot()
        return res

    @tornado.gen.coroutine
    def remove_object(self, *args, **kwargs):
        if not self.__slot:
            return
        yield super(RSDockerSpawner, self).remove_object(*args, **kwargs)
        self.__deallocate_slot()

    @tornado.gen.coroutine
    def stop_object(self, *args, **kwargs):
        if not self.__slot:
            return
        yield super(RSDockerSpawner, self).stop_object(*args, **kwargs)

    def __allocate_slot(self, no_raise=False):
        if self.__slot:
            if self.__slot.cname == self.object_name:
                return True
            # Should not see this message
            self.log.warn(
                'removing slot=%s:%s cname=%s not same as object_name=%s',
                self.__slot.host,
                self.__slot.port,
                self.__slot.cname,
                self.object_name,
            )
            self.__slot = None
        self.__init_class()
        self.__client = None
        s = self.__find_container(self.object_name)
        if not s:
            for s in self.__slots:
                if not s.cname:
                    break
            else:
                if no_raise:
                    return False
                self.log.warn('not more servers, slots_in use=%s', len(self.__slots))
                # copied from jupyter.handlers.base
                # The error message doesn't show up the first time, but will show up
                # if the user refreshes the browser.
                raise tornado.web.HTTPError(
                    429,
                    'No more servers available. Try again in a few minutes.',
                )
            s.cname = self.object_name
            pkjson.dump_pretty(self.__slots, filename=_SLOTS_FILE)
        self.__slot = s
        return True

    def __deallocate_slot(self):
        if not self.__slot:
            return
        self.__client = None
        self.__slot.cname = None
        self.__slot = None
        pkjson.dump_pretty(self.__slots, filename=_SLOTS_FILE)

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
            ca_cert=str(d.join('cacert.pem')),
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
        cls.__init_containers(slots, hosts, self.log)
        cls.__slots.extend(slots)
        self.log.info(
            'hosts=%s slots=%s slots_in_use=%s',
            ' '.join(hosts),
            len(slots),
            len([x for x in slots if x.cname]),
        )

    @classmethod
    def __init_containers(cls, slots, hosts, log):
        c = None
        hosts_copy = hosts[:]
        for h in hosts_copy:
            try:
                d = cls.__docker_client(h)
            except docker.errors.DockerException as e:
                log.error('Docker error on %s: %s', h, e)
                hosts.remove(h)
                for s in list(slots):
                    if s.host == h:
                        slots.remove(s)
                continue
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
