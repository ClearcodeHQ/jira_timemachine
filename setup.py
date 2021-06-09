# -*- coding: utf-8 -*-

import os
import re
from setuptools import setup, find_packages

here = os.path.dirname(__file__)
with open(os.path.join(here, "src", "jira_timemachine", "__init__.py")) as v_file:
    package_version = re.compile(r".*__version__ = '(.*?)'", re.S).match(v_file.read()).group(1)


def read(fname):
    """
    Read given file's content.

    :param str fname: file name
    :returns: file contents
    :rtype: str
    """
    with open(os.path.join(here, fname)) as f:
        return f.read()


requirements = ["arrow>=0.13.1", "attrs>=19.1.0", "Click>=7.0", "jira>=2.0.0", "typing>=3.6.6"]
test_requires = ["pytest>=4.4.0", "pytest-cov>=2.6.1", "mock>=2.0.0"]

extras_require = {"docs": ["sphinx"], "tests": test_requires}

setup(
    name="jira_timemachine",
    version=package_version,
    description="Synchronize worklogs between Jira instances",
    long_description=(read("README.rst") + "\n\n" + read("CHANGES.rst")),
    keywords="python template",
    author="Grzegorz Śliwiński",
    author_email="g.sliwinski@clearcode.cc",
    url="https://github.com/fizyk/jira_timemachine",
    license="MIT License",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Environment :: Web Environment",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Natural Language :: English",
        "Operating System :: OS Independent",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Topic :: Software Development :: Libraries :: Python Modules",
    ],
    package_dir={"": "src"},
    packages=find_packages("src"),
    install_requires=requirements,
    tests_require=test_requires,
    test_suite="tests",
    include_package_data=True,
    zip_safe=False,
    extras_require=extras_require,
    entry_points={
        "console_scripts": ["timemachine = jira_timemachine:timemachine", "timecheck = jira_timemachine:timecheck"]
    },
)
