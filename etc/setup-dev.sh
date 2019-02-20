#!/bin/bash
set -euo pipefail
mkdir -p ~/src/jupyterhub
cd ~/src/jupyterhub
gcl jupyterhub
cd jupyterhub
# Version 0.9.4
git checkout -b rn b1111363fd75ddd90a099e7db23ea1b769d2019e
pip install -e .

cd ~/src/radiasoft/rsdockerspawner
npm install --no-save configurable-http-proxy
rm -f ~/bin/configurable-http-proxy
ln -s $PWD/node_modules/configurable-http-proxy/bin/configurable-http-proxy ~/bin
docker pull radiasoft/beamsim-jupyter
rm -rf run
mkdir -p run/{docker_tls/localhost.localdomain,jupyterhub/vagrant}
ln -s -r $PWD/etc/jupyterhub_config.py run/jupyterhub_config.py
d=run/docker_tls/localhost.localdomain
for i in cert key; do
    sudo cat /etc/docker/tls/$i.pem | install -m 600 /dev/stdin $d/$i.pem
done
cp -a $d/cert.pem $d/cacert.pem
(cd run && exec jupyterhub -f jupyterhub_config.py)
