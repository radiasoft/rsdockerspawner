#!/bin/bash
set -euo pipefail
_bivio_pyenv_version 3.6.6 jh
pyenv global jh
pip install 'ipython[all]'
mkdir -p ~/src/jupyterhub
cd ~/src/jupyterhub
gcl jupyterhub
gcl dockerspawner
cd jupyterhub
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
if [[ ! -r ~/.ssh/id_ed25519 ]]; then
    ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -q -N ''
fi
rm -rf run
mkdir -p run/{docker_tls,user/vagrant}
ln -s -r $PWD/etc/jupyterhub_config.py run/jupyterhub_config.py
mkdir -p run/template
(
    set -euo pipefail
    cd run/docker_tls
    mkdir -p v3.radia.run
    cd v3.radia.run
    for i in cert.pem key.pem; do
        sudo cat /etc/docker/tls/$i > $i
    done
    cp cert.pem cacert.pem
    cd ..
    mkdir -p v2.radia.run
    cd v2.radia.run
    if ! ssh v2.radia.run true; then
        echo "echo '$(cat /home/vagrant/.ssh/id_ed25519.pub)' >> ~/.ssh/authorized_keys"
        echo 'chmod 600 ~/.ssh/authorized_keys'
        read -p 'Continue? '
    fi
    for i in cert.pem key.pem; do
        ssh v2.radia.run sudo cat /etc/docker/tls/$i > $i
    done
    cp cert.pem cacert.pem
)

sudo useradd --create-home participant
echo participant:participant | sudo chpasswd

(cd run && exec jupyterhub -f jupyterhub_config.py)
# you may need to restart to chown
sudo chown -R vagrant: run/user

# Proxy port 8000 on the host in screen (not VM)
socat TCP-LISTEN:8000,fork,reuseaddr TCP:v3.radia.run:8000
# and updating iptables
-A INPUT -i <DEV> -s <SOURCE> -p tcp -m state --state NEW -m tcp --match multiport --dports 8000 -j ACCEPT
systemctl restart iptables

# If you want to bypass authentication, modify jupyterhub.auth
class PAMAuthenticator(LocalAuthenticator):
    def add_user(...):
        return

    def authenticate(...):
       if data['password'] == 'magic pass':
          return username


NFS:
on v3:
echo '/home/vagrant/src 10.10.10.0/24(rw,no_root_squash,no_subtree_check,async,secure)' > /etc/exports.d/home_vagrant_src.exports
exportfs -a

On v2:
echo 'v3.radia.run:/home/vagrant/src /home/vagrant/src nfs defaults,vers=4.1,soft,noacl,_netdev 0 0' | ssh v2.radia.run bash -c 'sudo cat >> /etc/fstab'
