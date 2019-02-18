# -*- coding: utf-8 -*-
u"""Front-end command line for :mod:`rsdockerspawner`.

See :mod:`pykern.pkcli` for how this module is used.

:copyright: Copyright (c) 2019 RadiaSoft LLC.  All Rights Reserved.
:license: http://www.apache.org/licenses/LICENSE-2.0.html
"""
from __future__ import absolute_import, division, print_function
from pykern import pkcli
import sys


def main():
    return pkcli.main('rsdockerspawner')


if __name__ == '__main__':
    sys.exit(main())
