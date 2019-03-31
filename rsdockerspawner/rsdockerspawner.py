# -*- coding: utf-8 -*-
u"""Multi-host Docker execution with host networking

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from dockerspawner import dockerspawner
from pykern import pkcollections
from pykern import pkconfig
from pykern import pkio
from pykern import pkjson
from pykern.pkdebug import pkdp
import copy
import docker
import glob
import os
import os.path
import socket
import time
import tornado
import tornado.locks
import traitlets


#: container label for jupyter port
_PORT_LABEL = 'rsdockerspawner_port'

#: CPU Fair Scheduler (CFS) period (see below)
_CPU_PERIOD_US = 100000

#: dump the slots whenever an update happens
_POOLS_DUMP_FILE = 'rsdockerspawner_pools.json'

#: Name of the default pool, which must not have any users
_DEFAULT_POOL_NAME = 'default'

#: Large time out for minimum allowed activity (effectively infinite)
_DEFAULT_MIN_ACTIVITY_HOURS = 1e6

#: Minimum five mins so we don't garbage collect too frequently
_MIN_MIN_ACTIVITY_SECS = 5.0 if pkconfig.channel_in_internal_test() else 300.0


class RSDockerSpawner(dockerspawner.DockerSpawner):

    cfg = traitlets.Unicode(config=True)

    __class_lock = tornado.locks.Lock()

    #: shared variable to ensure initialization happens once
    __class_is_initialized = set()

    __slot = None

    __pools = pkcollections.Dict()

    __cfg = pkcollections.Dict()

    __client = None

    @property
    def client(self):
        if self.__client is None:
            self.__client = self.__docker_client(self.__slot.host)
        return self.__client

    @tornado.gen.coroutine
    def create_object(self, *args, **kwargs):
        yield self.__slot_alloc()
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
        if not (yield self.__slot_alloc(no_raise=True)):
            return None
        res = yield super(RSDockerSpawner, self).get_object(*args, **kwargs)
        if not res:
            self.__slot_free()
        return res

    @tornado.gen.coroutine
    def pull_image(self, *args, **kwargs):
        yield self.__slot_alloc()
        yield super(RSDockerSpawner, self).pull_image(*args, **kwargs)

    @tornado.gen.coroutine
    def remove_object(self, *args, **kwargs):
        if not self.__slot:
            return
        yield super(RSDockerSpawner, self).remove_object(*args, **kwargs)
        self.__slot_free()

    @tornado.gen.coroutine
    def stop_object(self, *args, **kwargs):
        if not self.__slot:
            return
        yield super(RSDockerSpawner, self).stop_object(*args, **kwargs)

    def _volumes_to_binds(self, *args, **kwargs):
        """Ensure the bind directories exist"""
        binds = super(RSDockerSpawner, self)._volumes_to_binds(*args, **kwargs)
        # POSIT: user running jupyterhub is also the jupyter user
        for v in binds:
            while not os.path.exists(v):
                os.mkdir(v)
                v = os.path.dirname(v)
            return binds

    @classmethod
    def __docker_client(cls, host):
        k = {
            'version': 'auto',
            'base_url': 'tcp://{}:2376'.format(host),
        }
        d = cls.__cfg.tls_dir.join(host)
        assert d.check(dir=True), \
            f'tls_dir/<host> does not exist: {d}'
        k['tls'] = docker.tls.TLSConfig(
            client_cert=(str(d.join('cert.pem')), str(d.join('key.pem'))),
            ca_cert=str(d.join('cacert.pem')),
            verify=True,
        )
        return docker.APIClient(**k)

    def __cname(self):
        return '/' + self.object_name

    @tornado.gen.coroutine
    def __init_class(self):
        cls = self.__class__
        with (yield cls.__class_lock.acquire()):
            if cls.__class_is_initialized:
                return
            # easiest way to access config generated by rsconf shared by instances
            cls.__cfg.update(pkjson.load_any(self.cfg))
            assert cls.__cfg.pools, \
                'No pools in cfg'
            d = pkio.py_path(cls.__cfg.tls_dir)
            assert d.check(dir=True), \
                'tls_dir={} does not exist'.format(d)
            cls.__cfg.tls_dir = d
            yield cls.__init_pools(self.log)
            cls.__class_is_initialized.add(True)

    @classmethod
    @tornado.gen.coroutine
    def __init_containers(cls, pool, log):
        c = None
        hosts_copy = pool.hosts[:]
        for h in hosts_copy:
            try:
                d = cls.__docker_client(h)
            except docker.errors.DockerException as e:
                log.error('Docker error on pool=%s host=%s: %s', pool.name, h, e)
                pool.hosts.remove(h)
                for s in list(pool.slots):
                    if s.host == h:
                        pool.slots.remove(s)
                continue
            for c in d.containers(all=True):
                if _PORT_LABEL not in c['Labels']:
                    # not ours
                    continue
                p = int(c['Labels'][_PORT_LABEL])
                n = c['Names'][0]
                i = c['Id']
                s = cls.__init_slot_find(pool, h, p)
                log.info(
                    'init_containers: found slot=%s for cname=%s cid=%s host=%s port=%s',
                    s and s.num,
                    n,
                    i,
                    h,
                    p,
                )
                if s and c['State'] == 'running':
                    if s.cname:
                        log.error(
                            'init_containers: found cname=%s for slot=%s with cname=%s',
                            n,
                            s.num,
                            s.cname,
                        )
                    else:
                        s2 = cls.__slot_for_container(n)[0]
                        if s2:
                            log.error(
                                'init_containers: another slot=%s for cname=%s so removing slot=%s host=%s',
                                s2.num,
                                n,
                                s.num,
                                s.host,
                            )
                        else:
                            log.info(
                                'init_containers: assigning cname=%s to slot=%s host=%s',
                                n,
                                s.num,
                                s.host,
                            )
                            cls.__slot_assign(s, n)
                            continue
                log.info(
                    'init_containers: removing unallocated cname=%s cid=%s host=%s',
                    n,
                    s.num,
                    s.host,
                )
                try:
                    m = getattr(d, 'remove_container')
                    yield self.executor.submit(m, i, force=True)
                except Exception as e:
                    log.error('init_containers: remove cid=%s failed: %s', i, e)

    @classmethod
    @tornado.gen.coroutine
    def __init_pools(cls, log):
        seen_user = pkcollections.Dict()

        def _assert_user(c, n):
            # use copy
            for u in c.users:
                assert u not in seen_user, \
                    'Duplicate user {} in pools={}, {}'.format(
                        u,
                        seen_user[u],
                        n,
                    )
                seen_user[u] = n

        slot_base = 1
        for n, c in cls.__cfg.pools.items():
            p = copy.deepcopy(c)
            p.name = n
            _assert_user(c, n)
            assert p.hosts, \
                'No hosts in pool={}'.format(n)
            p.setdefault('mem_limit', None)
            p.setdefault('cpu_limit', None)
            h = p.min_activity_hours or _DEFAULT_MIN_ACTIVITY_HOURS
            p.min_activity_secs = float(h) * 3600.
            assert p.min_activity_secs >= _MIN_MIN_ACTIVITY_SECS, \
                'min_activity_hours={} must not be less than {}'.format(
                    h,
                    int(_MIN_MIN_ACTIVITY_SECS / 3600.),
                )
            p.slots = cls.__init_slots(p, slot_base)
            p.lock = tornado.locks.Lock()
            slot_base += len(p.slots)
            cls.__pools[n] = p
            yield cls.__init_containers(p, log)
            log.info(
                'pool=%s hosts=%s slots=%s slots_in_use=%s',
                n,
                ' '.join(p.hosts),
                len(p.slots),
                len([x for x in p.slots if x.cname]),
            )
        if _DEFAULT_POOL_NAME not in cls.__pools:
            # Minimal configuration for default pool
            cls.__pools[_DEFAULT_POOL_NAME] = pkcollections.Dict(
                name=_DEFAULT_POOL_NAME,
                slots=[],
            )

    @classmethod
    def __init_slot_find(cls, pool, host, port):
        for s in pool.slots:
            if s.host == host and s.port == port:
                return s
        return None

    @classmethod
    def __init_slots(cls, pool, slot_base):
        res = []
        c = cls.__cfg
        for h in pool.hosts:
            for p in range(c.port_base, c.port_base + pool.servers_per_host):
                res.append(
                    pkcollections.Dict(
                        activity_secs=0.,
                        cname=None,
                        host=h,
                        port=p,
                    ),
                )
        # sort by port first so we distribute servers across hosts
        res = sorted(res, key=lambda x: str(x.port) + x.host)
        for s in res:
            s.num = slot_base
            slot_base += 1
        return res

    def __pool_for_user(self):
        u  = self.user.name
        for p in self.__pools.values():
            if u in p.users:
                break
        else:
            p = self.__pools[_DEFAULT_POOL_NAME]
        if len(p.slots) == 0:
            # If the slots are 0, then the pool is empty, and there
            # are no allocations for this user. This could be a config
            # error, or it could be all the servers in the pool are
            # unavailable.
            raise tornado.web.HTTPError(
                403,
                'No servers have been allocated for this user.',
            )
        return p

    @tornado.gen.coroutine
    def __pool_gc(self, pool):
        # all slots have names, and the pool is locked
        s = sorted(pool.slots, key=lambda x: x.activity_secs)[0]
        t = time.time() - s.activity_secs
        if t < pool.min_activity_secs:
            self.log.info(
                'pool_gc: least active slot=%s cname=%s inactivity_secs=%s',
                s.num,
                s.cname,
                int(t),
            )
            return None
        self.log.info(
            'pool_gc: removing slot=%s cname=%s inactivity_secs=%s for new user=%s',
            s.num,
            s.cname,
            int(t),
            self.user.name,
        )
        # No backlinks to self so clear cname to indicate slot is
        # free. If we crash in the below, that's ok. We may have
        # extra containers running, but we need then to poll the
        # entire collection of containers to make sure everything
        # is ok.
        # TODO(robnagler) audit pools
        cname = s.cname
        s.cname = None
        try:
            m = getattr(self.__docker_client(s.host), 'remove_container')
            yield self.executor.submit(m, cname, force=True)
        except Exception as e:
            self.log.error(
                'pool_gc: remove failed: slot=%s cname=%s pool=%s host=%s error=%s',
                s.num,
                cname,
                pool.name,
                s.host,
                e,
            )
        return s

    def __pools_dump(self):
        pools = copy.deepcopy(self.__pools)
        for p in pools.values():
            del p['lock']
        pkjson.dump_pretty(pools, filename=_POOLS_DUMP_FILE)

    @tornado.gen.coroutine
    def __slot_alloc(self, no_raise=False):
        n = self.__cname()
        if self.__slot:
            if self.__slot.cname == n:
                # Most likely its a poll() and only case where we use last_activity
                self.__slot.activity_secs = self.user.last_activity.timestamp()
                self.log.debug(
                    'slot_alloc: already allocated slot=%s cname=%s inactivity_secs=%s',
                    self.__slot.num,
                    self.__slot.cname,
                    int(time.time() - self.__slot.activity_secs),
                )
                return True
            self.log.warn(
                'slot_alloc: gc cleanup slot=%s slot.cname=%s != %s=self.__cname',
                self.__slot.num,
                self.__slot.cname,
                n,
            )
            self.__slot_free()
        else:
            if not self.__class_is_initialized:
                yield self.__init_class()
        pool, s = self.__slot_for_container(n)
        if s:
            # Ensures pool_gc doesn't select this slot
            s.activity_secs = time.time()
            self.log.info(
                'slot_alloc: found slot=%s cname=%s pool=%s host=%s',
                s.num,
                n,
                pool.name,
                s.host,
            )
        else:
            s, pool = yield self.__slot_alloc_try(no_raise)
            if not s:
                self.log.info('alloc: no slot for user=%s', self.user.name)
                return False
            self.log.info(
                'slot_alloc: allocated slot=%s cname=%s pool=%s host=%s',
                s.num,
                n,
                pool.name,
                s.host,
            )
        self.__slot = s
        self.__client = None
        self.mem_limit = pool.mem_limit
        self.cpu_limit = pool.cpu_limit
        self.__pools_dump()
        return True

    @tornado.gen.coroutine
    def __slot_alloc_try(self, no_raise):
        pool = self.__pool_for_user()
        with (yield pool.lock.acquire()):
            for s in pool.slots:
                if not s.cname:
                    break
            else:
                if no_raise:
                    return None, None
                s = yield self.__pool_gc(pool)
                if not s:
                    self.log.warn(
                        'slot_alloc_try: no more servers, pool=%s slots_in_use=%s',
                        pool.name,
                        len(pool.slots),
                    )
                    # copied from jupyter.handlers.base The error
                    # message doesn't show up the first time, but will
                    # show up if the user refreshes the browser.
                    raise tornado.web.HTTPError(
                        429,
                        'No more servers available. Try again in a few minutes.',
                    )
            self.__slot_assign(s, self.__cname())
            return s, pool

    @classmethod
    def __slot_assign(cls, slot, cname):
        slot.activity_secs = time.time()
        slot.cname = cname

    @classmethod
    def __slot_for_container(cls, cname):
        for p in cls.__pools.values():
            for s in p.slots:
                if s.cname == cname:
                    return p, s
        return None, None

    def __slot_free(self):
        if not self.__slot:
            return
        self.log.info(
            'free slot=%s cname=%s user=%s host=%s',
            self.__slot.num,
            self.__slot.cname,
            self.user.name,
            self.__slot.host,
        )
        self.__client = None
        if self.__cname() == self.__slot.cname:
            # Might have been garbage collected
            self.__slot.cname = None
        self.__slot = None
        self.__pools_dump()
