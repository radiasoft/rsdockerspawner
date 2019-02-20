from rsdockerspawner.rsdockerspawner import RSDockerSpawner
from jupyter_client.localinterfaces import public_ips
import base64
import os

run_d = os.environ['PWD']
c.JupyterHub.spawner_class = RSDockerSpawner
c.JupyterHub.authenticator_class = 'jupyterhub.auth.PAMAuthenticator'

c.Authenticator.admin_users = set(['vagrant'])

# will need to be implemented by spawner
c.Spawner.mem_limit = '16G'
c.Spawner.cpu_limit = 5.0

c.DockerSpawner.http_timeout = 120
c.DockerSpawner.image = 'radiasoft/beamsim-jupyter'
c.DockerSpawner.remove = True
# needs to be true b/c create_object will invoke port bindings otherwise
c.DockerSpawner.use_internal_ip = True
c.DockerSpawner.network_name = 'host'
# c.DockerSpawner.read_only_volumes
c.DockerSpawner.volumes = {
    run_d + '/jupyterhub/{username}': {
        # POSIT: notebook_dir in containers/radiasoft/beamsim-jupyter/build.sh
        'bind': '/home/vagrant/jupyter',
    },
}
c.DockerSpawner.client_kwargs = dict(
    base_url="tcp://localhost.localdomain:2376",
)
c.DockerSpawner.tls_config = dict(
    client_cert=(run_d + '/docker_tls/cert.pem', run_d + '/docker_tls/key.pem'),
    ca_cert=run_d + '/docker_tls/cacert.pem',
    verify=True,
)
c.RSDockerSpawner.tls_dir = run_d + '/docker_tls'


c.JupyterHub.confirm_no_ssl = True
c.JupyterHub.cookie_secret = base64.b64decode('qBdGBamOJTk5REgm7GUdsReB4utbp4g+vBja0SwY2IQojyCxA+CwzOV5dTyPJWvK13s61Yie0c/WDUfy8HtU2w==')
c.JupyterHub.hub_ip = public_ips()[0]
c.JupyterHub.ip = '0.0.0.0'
c.JupyterHub.port = 8000
c.JupyterHub.proxy_auth_token = '+UFr+ALeDDPR4jg0WNX+hgaF0EV5FNat1A3Sv0swbrg='
c.JupyterHub.authenticator_class = 'jupyterhub.auth.PAMAuthenticator'

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
