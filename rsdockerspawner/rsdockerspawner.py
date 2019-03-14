# -*- coding: utf-8 -*-
u"""Multi-host Docker execution with host networking

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
_POOLS_FILE = 'rsdockerspawner_pools.json'

#: Name of the default pool, which must not have allowed_users
_DEFAULT_POOL_NAME = 'default'

class RSDockerSpawner(dockerspawner.DockerSpawner):

    rsconf = traitlets.Unicode('', config=True)

    #: shared variable to ensure initialization happens once
    __class_is_initialized = set()

    __slot = None

    __pools = pkcollections.Dict()

    __rsconf = pkcollections.Dict()

    __client = None

    @property
    def client(self):
        if self.__client is None:
            self.__client = self.__docker_client(self.__slot.host)
        return self.__client

    @tornado.gen.coroutine
    def create_object(self, *args, **kwargs):
        self.__allocate_slot()
        self.extra_create_kwargs = {
            'hostname': f'rs{self.__slot.num}.local',
            'labels': {_PORT_LABEL: str(self.__slot.port)},
        }
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
        # docker puts a slash preceding the Name
        n = '/' + self.object_name
        if self.__slot:
            if self.__slot.cname == n:
                return True
            # Should not get here
            self.log.error(
                'PROGRAM ERROR: removing existing slot=%s:%s cname=%s != object_name=%s',
                self.__slot.host,
                self.__slot.port,
                self.__slot.cname,
                n,
            )
            self.__slot = None
        self.__init_class()
        self.__client = None
        pool, s = self.__find_container(n)
        if not s:
            pool, slots = self.__slots_for_user()
            for s in slots:
                if not s.cname:
                    break
            else:
                if no_raise:
                    return False
                #TODO(robnagler) handle case where default pool is empty
                #TODO(robnagler) garbage collect and retry
                self.log.warn(
                    'no more servers, pool=%s slots_in_use=%s',
                    pool.name,
                    len(slots),
                )
                # copied from jupyter.handlers.base
                # The error message doesn't show up the first time, but will show up
                # if the user refreshes the browser.
                raise tornado.web.HTTPError(
                    429,
                    'No more servers available. Try again in a few minutes.',
                )
            s.cname = n
            pkjson.dump_pretty(self.__pools, filename=_POOLS_FILE)
        self.__slot = s
        self.mem_limit = pool.mem_limit
        self.cpu_limit = pool.cpu_limit
        return True

    def __deallocate_slot(self):
        if not self.__slot:
            return
        self.__client = None
        self.__slot.cname = None
        self.__slot = None
        pkjson.dump_pretty(self.__pools, filename=_POOLS_FILE)

    @classmethod
    def __docker_client(cls, host):
        k = {
            'version': 'auto',
            'base_url': 'tcp://{}:2376'.format(host),
        }
        d = pkio.py_path(cls.__rsconf.tls_dir).join(host)
        assert d.check(dir=True), \
            f'tls_dir/<host> does not exist: {d}'
        k['tls'] = docker.tls.TLSConfig(
            client_cert=(str(d.join('cert.pem')), str(d.join('key.pem'))),
            ca_cert=str(d.join('cacert.pem')),
            verify=True,
        )
        return docker.APIClient(**k)

    @classmethod
    def __find_container(cls, cname):
        for p in cls.__pools:
            for s in p.slots:
                if s.cname == cname:
                    return p, s
        return None, None

    @classmethod
    def __find_slot(cls, pool, host, port):
        for s in pool.slots:
            if s.host == host and s.port == port:
                return s
        return None

    def __init_class(self):
        if self.__class_is_initialized:
            return
        #TODO(robnagler) Must be single threaded. Not sure
        # how we do that here, because docker api is async...
        self.__class_is_initialized.add(True)
        cls = self.__class__
        # easiest way to access config generated by rsconf shared by instances
        cls.__rsconf.update(pkjson.load_any(self.rsconf))
        cls.__init_pools(self.log)


    def __init_pools(cls, log):
        for n, c in cls.__rsconf.pools.items():
            p = copy.deepcopy(c)
            p.name = n
            # reuse object so shared between instances
            p.slots = cls.__init_slots(p)
            cls.__pools[n] = p
            cls.__init_containers(p, log)
            self.log.info(
                'pool=%s hosts=%s slots=%s slots_in_use=%s',
                n,
                ' '.join(hosts),
                len(p.slots),
                len([x for x in p.slots if x.cname]),
            )
        if _DEFAULT_POOL_NAME not in cls.__pools:
            # Minimal configuration for default paul
            cls.__pools[_DEFAULT_POOL_NAME] = pkcollections.Dict(
                name=_DEFAULT_POOL_NAME,
                slots=[],
            )


    @classmethod
    def __init_containers(cls, pool, log):
        c = None
        hosts_copy = pool.hosts[:]
        for h in hosts_copy:
            try:
                d = cls.__docker_client(h)
            except docker.errors.DockerException as e:
                log.error(
                    'Docker error on pool=%s host=%s: %s',
                    pool.name,
                    h,
                    e,
                )
                pool.hosts.remove(h)
                for s in list(pool.slots):
                    if s.host == h:
                        pool.slots.remove(s)
                continue
            for c in d.containers(all=True):
                if _PORT_LABEL not in c['Labels']:
                    # not ours
                    continue
                s = cls.__find_slot(pool, h, int(c['Labels'][_PORT_LABEL]))
                n = c['Names'][0]
                i = c['Id']
                if s and c['State'] == 'running' and not cls.__find_container(n)[0]:
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
    def __init_slots(cls, pool):
        res = []
        c = cls.__rsconf
        for h in pool.hosts:
            for p in range(c.port, c.port + pool.servers_per_host):
                res.append(
                    pkcollections.Dict(
                        cname=None,
                        host=h,
                        port=p,
                    ),
                )
        # sort by port first so we distribute servers across hosts
        res = sorted(res, key=lambda x: str(x.port) + x.host)
        for i, s in enumerate(res):
            s.num = i + 1
        return res


    def __slots_for_user(self):
        u  = self.user.name
        for p in self.__pools.values():
            if u in p.allowed_users:
                break
        else:
            p = self.__pools[_DEFAULT_POOL_NAME]
        return p, p.slots
