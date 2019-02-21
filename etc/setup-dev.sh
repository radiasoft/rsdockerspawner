#!/bin/bash
set -euo pipefail
_bivio_pyenv_version 3.6.6 jh
pip install 'ipython[all]'
mkdir -p ~/src/jupyterhub
cd ~/src/jupyterhub
gcl jupyterhub
gcl dockerspawner
cd jupyterhub
# Version 0.9.4
git checkout -b rn b1111363fd75ddd90a099e7db23ea1b769d2019e
pip install -e .
cd ../dockerspawner
pip install -e .
cd ~/src/radiasoft/pykern
git pull
pip install -e .
cd ~/src/radiasoft/rsdockerspawner
pip install -e .
npm install --no-save configurable-http-proxy
rm -f ~/bin/configurable-http-proxy
ln -s $PWD/node_modules/configurable-http-proxy/bin/configurable-http-proxy ~/bin
docker pull radiasoft/beamsim-jupyter | cat
rm -rf run
mkdir -p run/{docker_tls,jupyterhub/vagrant}
ln -s -r $PWD/etc/jupyterhub_config.py run/jupyterhub_config.py
(
    set -euo pipefail
    cd run/docker_tls
    mkdir localhost.localdomain
    cd localhost.localdomain
    for i in cert.pem key.pem; do
        sudo cat /etc/docker/tls/$i > $i
    done
    cp cert.pem cacert.pem
    cd ..
    mkdir v2.radia.run
    cd v2.radia.run
    for i in cert.pem key.pem; do
        ssh v2.radia.run sudo cat /etc/docker/tls/$i > $i
    done
    cp cert.pem cacert.pem
)
(cd run && exec jupyterhub -f jupyterhub_config.py)


# If you want to get access to a public server, you might need this
socat TCP-LISTEN:8000,fork,reuseaddr TCP:v.radia.run:8000
# and updating iptables
-A INPUT -i <DEV> -s <SOURCE> -p tcp -m state --state NEW -m tcp --match multiport --dports 8000 -j ACCEPT
