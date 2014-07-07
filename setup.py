"""Package setup information."""


from subprocess import call

from setuptools import Command, setup


class RunTests(Command):
    """Run all tests."""
    description = 'run tests'
    user_options = []

    def initialize_options(self):
        pass

    def finalize_options(self):
        pass

    def run(self):
        """Run all tests!"""
        errno = call(['py.test'])
        raise SystemExit(errno)


setup(

    # Basic package information:
    name = 'simpleq',
    version = '0.0.1',
    py_modules = ['simpleq'],

    # Packaging options:
    zip_safe = False,
    include_package_data = True,

    # Package dependencies:
    install_requires = ['boto>=2.30.0', 'gevent>=1.0.1'],

    # Metadata for PyPI:
    author = 'Randall Degges',
    author_email = 'r@rdegges.com',
    license = 'UNLICENSE',
    url = 'https://github.com/rdegges/simpleq',
    keywords = 'SQS AWS amazon web services queue worker tasks job',
    description = 'A simple, infinitely scalable, SQS based queue.',
    long_description = 'A simple, infinitely scalable, SQS based queue.',

    # Classifiers:
    platforms = 'any',
    classifiers = [
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'License :: Public Domain',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
        'Topic :: Internet :: WWW/HTTP :: Dynamic Content',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Database',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: Implementation :: PyPy',
    ],

    # Test helper:
    cmdclass = {'test': RunTests},

)
