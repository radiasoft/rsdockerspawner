# -*- coding: utf-8 -*-
u"""Multi-host Docker execution with host networking

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from dockerspawner import dockerspawner
from pykern import pkconfig
from pykern import pkio
from pykern import pkjson
from pykern.pkcollections import PKDict
from pykern.pkdebug import pkdp, pkdpretty, pkdexc
import copy
import datetime
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

#: Default user when no specific volume for user ['*']
_DEFAULT_USER_GROUP = 'everybody'

#: Name of the default pool when no user patches
_DEFAULT_POOL = _DEFAULT_USER_GROUP

#: Large time out for minimum allowed activity (effectively infinite)
_DEFAULT_MIN_ACTIVITY_HOURS = 1e6

#: Minimum five mins so we don't garbage collect too frequently
_MIN_MIN_ACTIVITY_SECS = 5.0 if pkconfig.channel_in_internal_test() else 300.0

#: User that won't match a legimate user
_DEFAULT_USER = '*'


class RSDockerSpawner(dockerspawner.DockerSpawner):

    cfg = traitlets.Unicode(config=True)

    __class_lock = tornado.locks.Lock()

    #: shared variable to ensure initialization happens once
    __class_is_initialized = set()

    __slot = None

    __pools = PKDict()

    __cfg = PKDict()

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
        self.extra_host_config = dict(init=True)
        if self.shm_size:
            self.extra_host_config.update(
                shm_size=self.shm_size,
            )
        if self.cpu_limit:
            self.extra_host_config.update(
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
        res = yield super().create_object(*args, **kwargs)
        return res

    def docker(self, method, *args, **kwargs):
        if method == 'create_container' and self.__gpus:
            # See https://github.com/sigurdkb/docker-py/blob/f5e11cdc6e3bd179312aceededf323cbb7cdc448/docker/types/containers.py#L529
            kwargs['host_config']['DeviceRequests'] = [{
                'Driver': '',
                'Count': self.__gpus,
                'DeviceIDs': None,
                'Capabilities': [['gpu']],
                'Options': {},
            }]
        return super().docker(method, *args, **kwargs)

    def get_env(self, *args, **kwargs):
        res  = super().get_env(*args, **kwargs)
        res['RADIA_RUN_PORT'] = str(self.__slot.port)
        return res

    @tornado.gen.coroutine
    def get_ip_and_port(self):
        return (socket.gethostbyname(self.__slot.host), self.__slot.port)

    @tornado.gen.coroutine
    def get_object(self, *args, **kwargs):
        if not (yield self.__slot_alloc(no_raise=True)):
            return None
        res = yield super().get_object(*args, **kwargs)
        if not res:
            self.__slot_free()
        return res

    @tornado.gen.coroutine
    def pull_image(self, *args, **kwargs):
        yield self.__slot_alloc()
        yield super().pull_image(*args, **kwargs)

    @property
    def read_only_volumes(self):
        """See `volumes`"""
        return PKDict()

    @tornado.gen.coroutine
    def remove_object(self, *args, **kwargs):
        if not self.__slot:
            return
        yield super().remove_object(*args, **kwargs)
        self.__slot_free()

    @tornado.gen.coroutine
    def stop_object(self, *args, **kwargs):
        if not self.__slot:
            return
        yield super().stop_object(*args, **kwargs)

    def _volumes_to_binds(self, *args, **kwargs):
        """Ensure the bind directories exist"""
        binds = super()._volumes_to_binds(*args, **kwargs)
        # POSIT: user running jupyterhub is also the jupyter user
        for v in binds:
            if not os.path.exists(v):
                os.makedirs(v)
        return binds

    @property
    def volume_binds(self):
        """Find volumes for user

        _DEFAULT_USER_GROUP will not override user specific
        volumes.

        Returns:
            dict: DockerSpawner volume map
        """
        res = PKDict()
        for n in self.user.name, _DEFAULT_USER:
            if n not in self.__users_to_volumes:
                continue
            for s, v in self.__users_to_volumes[n].items():
                if s not in res:
                    res[s] = copy.deepcopy(v)
        self.log.debug('user=%s volumes=%s', self.user.name, res)
        return self._volumes_to_binds(res, {})

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
        pkdp(k['tls'].ca_cert)
        assert d.join('key.pem').exists(), '{}does not exist'.format(d.join('key.pem'))
        return docker.APIClient(**k)

    def __cname(self):
        return '/' + self.object_name

    @classmethod
    def __fixup_cfg(cls, cfg, volumes):
        pools = cfg.get('pools')
        if not pools or 'default' not in pools:
            return cfg
        e = pools.default
        del pools['default']
        del e['users']
        u = PKDict()
        n = 1
        for p in pools.values():
            g = 'g{}'.format(n)
            n += 1
            p.user_groups = [ g ]
            u[g] = p.users
            del p['users']
        # don't carry "trail
        v2 = PKDict()
        for k, v in volumes.items():
            v2[k] = PKDict(v)
        cfg.volumes = v2
        cfg.pools.everybody = e
        cfg.user_groups = u
        return cfg

    @tornado.gen.coroutine
    def __init_class(self):
        cls = self.__class__
        with (yield cls.__class_lock.acquire()):
            if cls.__class_is_initialized:
                return
            # easiest way to access config generated by rsconf shared by instances
            cls.__cfg.update(cls.__fixup_cfg(pkjson.load_any(self.cfg), self.volumes))
            assert cls.__cfg.pools, \
                'No pools in cfg'
            d = pkio.py_path(cls.__cfg.tls_dir)
            assert d.check(dir=True), \
                'tls_dir={} does not exist'.format(d)
            cls.__cfg.tls_dir = d
            cls.__init_volumes(self.log)
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
                log.error('Docker error on pool=%s host=%s stack=%s ', pool.name, h, pkdexc())
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
                            'init_containers: duplicate assigned cname=%s in slot=%s (trying to assign cname=%s)',
                            s.num,
                            s.cname,
                            n,
                        )
                    else:
                        s2 = cls.__slot_for_container(n)[1]
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
                    i,
                    h,
                )
                try:
                    m = getattr(d, 'remove_container')
                    yield self.executor.submit(m, i, force=True)
                except Exception as e:
                    log.error('init_containers: remove cid=%s failed: %s', i, e)

    @classmethod
    @tornado.gen.coroutine
    def __init_pools(cls, log):
        seen_user = PKDict()

        def _assert_user(users, n):
            # use copy
            for u in users:
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
            if _DEFAULT_POOL == n:
                assert not p.get('user_groups'), \
                    'no user_groups allowed for default pool: user_groups={}'.format(
                        p.user_groups,
                    )
                # users are not referenced, but convenient to model everybody
                p.user_groups = [_DEFAULT_USER_GROUP]
            p.users = cls.__users_for_groups(p.user_groups)
            _assert_user(p.users, n)
            assert p.hosts, \
                'No hosts in pool={}'.format(n)
            p.pksetdefault(
                cpu_limit=None,
                mem_limit=None,
                shm_size=None,
            )
            h = p.get('min_activity_hours', _DEFAULT_MIN_ACTIVITY_HOURS)
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
        if _DEFAULT_POOL not in cls.__pools:
            # Minimal configuration for default pool, which matches nobody
            cls.__pools[_DEFAULT_POOL] = PKDict(
                name=_DEFAULT_POOL,
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
                    PKDict(
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

    @classmethod
    def __init_volumes(cls, log):
        res = PKDict({_DEFAULT_USER: PKDict()})
        for s, v in cls.__cfg.volumes.items():
            if not ('mode' in v and isinstance(v.mode, dict)):
                res[_DEFAULT_USER][s] = copy.deepcopy(v)
                continue
            # rw must be first
            for m in 'rw', 'ro':
                v2 = copy.deepcopy(v)
                if not m in v.mode:
                    continue
                v2.mode = m
                for u in cls.__users_for_groups(v.mode[m]):
                    x = res.setdefault(u, PKDict())
                    assert s not in x, \
                        'duplicate bind={} for user="{}" other={}'.format(s, u, x[s])
                    x[s] = v2
        cls.__users_to_volumes = res
        log.debug('__users_to_volumes: %s', cls.__users_to_volumes)

    def __pool_for_user(self):
        u  = self.user.name
        for p in self.__pools.values():
            if u in p.users:
                break
        else:
            p = self.__pools[_DEFAULT_POOL]
        if len(p.slots) == 0:
            # If the slots are 0, then the pool is empty, and there
            # are no allocations for this user. This could be a config
            # error, or it could be all the servers in the pool are
            # unavailable.
            raise _Error(
                403,
                'You have not been allocated any servers.'
                    + ' Please contact support@radiasoft.net.',
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
            p.pkdel('lock')
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
        self.cpu_limit = pool.cpu_limit
        self.mem_limit = pool.mem_limit
        self.shm_size = pool.shm_size
        g = pool.get('gpus')
        if g:
            g = -1 if g == 'all' else int(g)
        self.__gpus = g
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
                    raise _Error(
                        429,
                        'There are no more servers available.'
                            + ' Please wait a few minutes before trying again.',
                    )
            self.__slot_assign(s, self.__cname())
            return s, pool

    @classmethod
    def __slot_assign(cls, slot, cname):
        slot.activity_secs = time.time()
        slot.start_time = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
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


    @classmethod
    def __users_for_groups(cls, groups):
        if not groups:
            return [];
        if _DEFAULT_USER_GROUP == groups[0]:
            return [_DEFAULT_USER]
        assert _DEFAULT_USER_GROUP not in groups, \
            '{} must be the only user in user_groups=[{}]'.format(
                _DEFAULT_USER_GROUP,
                groups,
            )
        res = set()
        for g in groups:
            res.update(cls.__cfg.user_groups[g])
        return sorted(res)


    @tornado.gen.coroutine
    def start(self, *args, **kwargs):
        """copied from dockerspawner and trimmed"""
        yield self.pull_image(self.image)
        obj = yield self.get_object()
        if obj:
            self.log.info(
                "Removing existing %s: %s (id: %s)",
                self.object_type,
                self.object_name,
                self.object_id[:7],
            )
            yield self.remove_object()
            for _ in range(10):
                obj = yield self.get_object()
                if not obj:
                    break
                tornado.gen.sleep(1)
            else:
                self.log.error(
                    "Remove failed %s: %s (id: %s); will try to start anyway",
                    self.object_type,
                    self.object_name,
                    self.object_id[:7],
                )
        obj = yield self.create_object()
        self.object_id = obj[self.object_id_key]
        self.log.info(
            "Starting %s %s (id: %s) from image %s",
            self.object_type,
            self.object_name,
            self.object_id[:7],
            self.image,
        )
        yield self.start_object()
        ip, port = yield self.get_ip_and_port()
        return (ip, port)


class _Error(tornado.web.HTTPError):
    def __init__(self, code, msg):
        super().__init__(code, msg)
        self.jupyterhub_message = msg
