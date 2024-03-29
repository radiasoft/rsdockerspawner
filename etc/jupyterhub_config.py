from rsdockerspawner.rsdockerspawner import RSDockerSpawner
from jupyter_client.localinterfaces import public_ips
import base64
import os

run_d = os.environ["PWD"]
c.JupyterHub.spawner_class = RSDockerSpawner
c.JupyterHub.template_paths = [RSDockerSpawner.sirepo_template_dir()]
c.Authenticator.admin_users = set(["vagrant"])
import jupyterhub.auth


class _Auth(jupyterhub.auth.Authenticator):
    async def authenticate(self, handler, data):
        if data["password"] == "jupyter":
            return data["username"]
        return None


c.JupyterHub.authenticator_class = _Auth

c.DockerSpawner.http_timeout = 120
c.DockerSpawner.image = "radiasoft/beamsim-jupyter"
# needs to be true b/c create_object will invoke port bindings otherwise
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.network_name = "host"
c.RSDockerSpawner.cfg = (
    '''{
    "port_base": 8100,
    "tls_dir": "'''
    + run_d
    + '''/docker_tls",
    "pools": {
        "everybody": {
            "hosts": [ ],
            "min_activity_hours": 0.1,
            "servers_per_host": 1
        },
        "private": {
            "cap_add": ["SYS_PTRACE"],
            "hosts": [ "localhost.localdomain" ],
            "min_activity_hours": 1,
            "servers_per_host": 1,
            "user_groups": [ "instructors" ]
        }
    },
    "user_groups": {
        "instructors": [ "vagrant", "participant" ]
    },
    "volumes": {
        "'''
    + run_d
    + '''/user/{username}": {
            "bind": "/home/vagrant/jupyter"
        },
        "'''
    + run_d
    + '''/workshop": {
            "bind": "/home/vagrant/jupyter/workshop",
            "mode": {
                "ro": [ "everybody" ]
            }
        },
        "'''
    + run_d
    + """/workshop/{username}": {
            "bind": "/home/vagrant/jupyter/workshop/{username}",
            "mode": {
                "rw": [ "instructors" ]
            }
        }
    }
}"""
)

# this doesn't seem to work
# c.JupyerHub.active_server_limit = 2

# c.JupyterHub.template_vars = {'announcement': 'some_text'}
c.JupyterHub.confirm_no_ssl = True
c.JupyterHub.cookie_secret = base64.b64decode(
    "qBdGBamOJTk5REgm7GUdsReB4utbp4g+vBja0SwY2IQojyCxA+CwzOV5dTyPJWvK13s61Yie0c/WDUfy8HtU2w=="
)
# hardwired network for v*.radia.run
c.JupyterHub.hub_ip = [i for i in public_ips() if i.startswith("10.10.10.")][0]
c.JupyterHub.ip = "0.0.0.0"
c.JupyterHub.port = 8000

# NEED THIS to keep servers alive after restart of hub
# this doesn't work if False
#    docker.errors.APIError: 409 Client Error: Conflict ("Conflict. The container name "/jupyter-vagrant" is
#    already in use by container "cb44afddee641143a798d6ee1dfa508014f4e4fbf097307d73702ee57664b652".
c.JupyterHub.cleanup_servers = False

# NEED THIS so people can restart their containers for real
c.DockerSpawner.remove = True

c.JupyterHub.proxy_auth_token = "+UFr+ALeDDPR4jg0WNX+hgaF0EV5FNat1A3Sv0swbrg="

# Debugging only
c.Application.log_level = "DEBUG"
# Might not want this, but for now it's useful to see everything
# c.JupyterHub.debug_db = True
c.ConfigurableHTTPProxy.debug = True
c.JupyterHub.log_level = "DEBUG"
c.LocalProcessSpawner.debug = True
c.Spawner.debug = True
