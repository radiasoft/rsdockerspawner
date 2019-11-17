# rsdockerspawner

multi-node DockerSpawner

Learn more at https://github.com/radiasoft/rsdockerspawner.

# Development

To test in an rsconf config, modify `/srv/jupyterhub/start` as follows:

```
exec docker run "${flags[@]}" --init --rm "--user=$user" --network=host -v '/srv/jupyterhub:/srv/jupyterhub' \
    -v /home/vagrant/src/radiasoft/rsdockerspawner/rsdockerspawner:/opt/conda/lib/python3.6/site-packages/rsdockerspawner \
    -v /home/vagrant/src/radiasoft/pykern/pykern:/opt/conda/lib/python3.6/site-packages/pykern \
    "${image_cmd[@]}"
```

# License

License: http://www.apache.org/licenses/LICENSE-2.0.html

Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
