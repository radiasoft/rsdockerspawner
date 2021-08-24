#!/bin/bash
set -euo pipefail
if [[ ! -f setup.py ]]; then
    echo 'run in radiasoft/rsdockerspawner directory' 1>&2
    exit 1
fi
pip install jupyterhub==1.1.0 jupyterlab==2.1.0
pip install ipywidgets
pip install git+https://github.com/jupyterhub/oauthenticator.git@0.10.0
pip install git+https://github.com/jupyterhub/dockerspawner.git@0.11.1
npm install -g configurable-http-proxy
if [[ ! $(type -p docker) ]]; then
    sudo su - -c 'radia_run redhat-docker'
fi
docker pull radiasoft/beamsim-jupyter:latest
pip install -e .
# install globally means for this user
mkdir -p run/{template,docker_tls/localhost.localdomain,user/vagrant}
ln -s -r "$PWD"/etc/jupyterhub_config.py run/jupyterhub_config.py
cd run/docker_tls/localhost.localdomain
for i in cert.pem key.pem; do
    sudo cat /etc/docker/tls/$i > $i
done
cp -a cert.pem cacert.pem
cat <<'EOF'
To execute:

cd run && jupyterhub -f jupyterhub_config.py
EOF
