# -*- coding: utf-8 -*-
u"""rsdockerspawner setup script

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from pykern import pksetup

pksetup.setup(
    name='rsdockerspawner',
    author='RadiaSoft LLC',
    author_email='pip@radiasoft.net',
    description='multi-node DockerSpawner',
    install_requires=[
        'pykern',
    ],
    license='http://www.apache.org/licenses/LICENSE-2.0.html',
    url='https://github.com/radiasoft/rsdockerspawner',
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: Apache Software License',
        'Natural Language :: English',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python',
        'Topic :: Utilities',
    ],
)
