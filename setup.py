# -*- coding: utf-8 -*-
"""Aleph Message - Python library for the Aleph.im message specification
(c) 2021 OKESO for Aleph.im
"""

import os

from setuptools import setup

# allow setup.py to be run from any path
os.chdir(os.path.normpath(os.path.join(os.path.abspath(__file__), os.pardir)))

with open('README.md') as file:
    long_description = file.read()

setup(name='Aleph Message',
      version='0.0.1',
      description='Aleph.im message specification ',
      long_description=long_description,
      author='Hugo Herter',
      author_email='git@hugoherter.com',
      url='https://github.com/aleph-im/aleph-message',
      packages=['aleph_message'],
      data_files=[],
      install_requires=[
          'pydantic',
      ],
      license='MIT',
      platform='any',
      keywords="aleph.im message validation specification",
      classifiers=['Development Status :: 3 - Alpha',
                   'Programming Language :: Python :: 3',
                   'Intended Audience :: Developers',
                   ],
      )