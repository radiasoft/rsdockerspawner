# -*- coding: utf-8 -*-
"""rsdockerspawner setup script

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from pykern import pksetup

pksetup.setup(
    name="rsdockerspawner",
    author="RadiaSoft LLC",
    author_email="pip@radiasoft.net",
    description="multi-node DockerSpawner",
    install_requires=[
        "pykern",
    ],
    license="http://www.apache.org/licenses/LICENSE-2.0.html",
    url="https://github.com/radiasoft/rsdockerspawner",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Framework :: JupyterHub",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: Apache Software License",
        "Natural Language :: English",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python",
        "Topic :: Utilities",
    ],
)
