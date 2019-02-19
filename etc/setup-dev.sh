#!/bin/bash
set -euo pipefail
npm install --no-save configurable-http-proxy
rm -f ~/bin/configurable-http-proxy
ln -s $PWD/node_modules/configurable-http-proxy/bin/configurable-http-proxy ~/bin
docker pull radiasoft/beamsim-jupyter
rm -rf run
mkdir -p run/{docker_tls,jupyterhub/vagrant}
ln -s -r $PWD/etc/jupyterhub_config.py run/jupyterhub_config.py
for i in cert key; do
    sudo cat /etc/docker/tls/$i.pem | install -m 600 /dev/stdin run/docker_tls/$i.pem
done
cp -a run/docker_tls/cert.pem run/docker_tls/cacert.pem
(cd run && exec jupyterhub -f jupyterhub_config.py)
