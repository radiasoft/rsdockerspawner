# -*- coding: utf-8 -*-
u"""subclass docker spawner

:copyright: Copyright (c) 2019 Bivio Software, Inc.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from dockerspawner import dockerspawner
from pykern import pkio
from pykern.pkdebug import pkdp
import docker
import socket
import tornado
import traitlets


class RSDockerSpawner(dockerspawner.DockerSpawner):

    tls_dir = traitlets.Unicode('', config=True)

    __client = None

    @property
    def client(self):
        if self.__client is None:
            self.__host = 'localhost.localdomain'
            self.__port = 7777
            k = {
                'version': 'auto',
                'base_url': 'tcp://{}:2376'.format(self.__host),
            }
            d = pkio.py_path(self.tls_dir).join(self.__host)
            assert d.check(dir=True), \
                f'tls_dir/<host> does not exist: {d}'
            c = str(d.join('cert.pem'))
            k['tls'] = docker.tls.TLSConfig(
                client_cert=(c, str(d.join('key.pem'))),
                ca_cert=c,
                verify=True,
            )
            self.__client = docker.APIClient(**k)
        return self.__client


    def get_env(self, *args, **kwargs):
        res  = super(RSDockerSpawner, self).get_env(*args, **kwargs)
        res['RADIA_RUN_PORT'] = str(self.__port)
        return res

    @tornado.gen.coroutine
    def create_object(self, *args, **kwargs):
        res = yield super(RSDockerSpawner, self).create_object(*args, **kwargs)
        return res


    @tornado.gen.coroutine
    def get_ip_and_port(self):
        resp = yield self.docker("inspect_container", self.container_id)
        port = None
        for i in resp['Config']['Env']:
            if i.startswith('RADIA_RUN_PORT='):
                port = int(i.split('=')[1])
                break
        else:
             raise RuntimeError('RADIA_RUN_PORT not in Env: {}'.format(resp['Config']['Env']))
        return (socket.gethostbyname(self.__host), port)


    @property
    def TODO_object_name(self):
        # figure out if the object is running.
        # Inventory all hosts at first start
        pass


    @tornado.gen.coroutine
    def TODO_start(self, *args, **kwargs):
        establish ob
        res = super(RSDockerSpawner, self).start(*args, **kwargs)
