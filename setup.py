from os.path import abspath, dirname, join, normpath

from setuptools import setup


setup(

    # Basic package information:
    name = 'sqsq',
    version = '0.0.1',
    py_modules = ['sqsq'],

    # Packaging options:
    zip_safe = False,
    include_package_data = True,

    # Package dependencies:
    install_requires = ['pytest>=2.4.2'],

    # Metadata for PyPI:
    author = 'Randall Degges',
    author_email = 'rdegges@gmail.com',
    license = 'UNLICENSE',
    url = 'https://github.com/rdegges/sqsq',
    keywords = 'SQS AWS amazon web services queue worker tasks job',
    description = 'A simple, scalable, SQS queue.',
    long_description = open(normpath(join(dirname(abspath(__file__)),
        'README.md'))).read()

)
