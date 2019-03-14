from rsdockerspawner.rsdockerspawner import RSDockerSpawner
from jupyter_client.localinterfaces import public_ips
import base64
import os

run_d = os.environ['PWD']
c.JupyterHub.spawner_class = RSDockerSpawner
c.JupyterHub.authenticator_class = 'jupyterhub.auth.PAMAuthenticator'

c.Authenticator.admin_users = set(['vagrant'])

# will need to be implemented by spawner
c.Spawner.mem_limit = '1G'
c.Spawner.cpu_limit = 0.5

c.DockerSpawner.http_timeout = 120
c.DockerSpawner.image = 'radiasoft/beamsim-jupyter'
# needs to be true b/c create_object will invoke port bindings otherwise
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.network_name = 'host'
# c.DockerSpawner.read_only_volumes
c.DockerSpawner.volumes = {
    run_d + '/user/{username}': {
        # POSIT: notebook_dir in containers/radiasoft/beamsim-jupyter/build.sh
        'bind': '/home/vagrant/jupyter',
    },
}
c.RSDockerSpawner.cfg = '''{
    "port_base": 8100,
    "tls_dir": "''' + run_d + '''/docker_tls",
    "pools": {
        "private": {
            "servers_per_host": 1,
            "hosts": [ "v2.radia.run" ],
            "users": [ "vagrant" ]
        },
        "default": {
            "servers_per_host": 1,
            "hosts": [ "localhost.localdomain" ],
            "users": [ ]
        }
    }
}'''

# this doesn't seem to work
# c.JupyerHub.active_server_limit = 2

c.JupyterHub.confirm_no_ssl = True
c.JupyterHub.cookie_secret = base64.b64decode('qBdGBamOJTk5REgm7GUdsReB4utbp4g+vBja0SwY2IQojyCxA+CwzOV5dTyPJWvK13s61Yie0c/WDUfy8HtU2w==')
c.JupyterHub.hub_ip = [i for i in public_ips() if i.startswith('10.10.')][0]
c.JupyterHub.ip = '0.0.0.0'
c.JupyterHub.port = 8000

# NEED THIS to keep servers alive after restart of hub
# this doesn't work if False
#    docker.errors.APIError: 409 Client Error: Conflict ("Conflict. The container name "/jupyter-vagrant" is
#    already in use by container "cb44afddee641143a798d6ee1dfa508014f4e4fbf097307d73702ee57664b652".
c.JupyterHub.cleanup_servers = False

# NEED THIS so people can restart their containers for real
c.DockerSpawner.remove = True

c.JupyterHub.proxy_auth_token = '+UFr+ALeDDPR4jg0WNX+hgaF0EV5FNat1A3Sv0swbrg='

# Debugging only
c.Application.log_level = 'DEBUG'
# Might not want this, but for now it's useful to see everything
#c.JupyterHub.debug_db = True
c.ConfigurableHTTPProxy.debug = True
c.JupyterHub.log_level = 'DEBUG'
c.LocalProcessSpawner.debug = True
c.Spawner.debug = True

# Testing only; Need a passwd for vagrant inside container for PAMAuthenticator
#import subprocess
#subprocess.check_call('echo vagrant:vagrant|chpasswd', shell=True)
