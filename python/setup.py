from setuptools import setup

setup(
    name='aavs-system',
    version='1.0',
    packages=['pydaq', 'pydaq.persisters', 'pydaq.plotters', 'pyaavs', 'aavs_calibration', "aavs_subrack"],
    url='https://bitbucket.org/aavslmc/aavs-system',
    license='',
    author='Alessio Magro',
    author_email='alessio.magro@um.edu.mt',
    description='AAVS Software',
    install_requires=['h5py', 'pyyaml', 'lockfile', 'scapy', 'numpy', 'gitpython', 'pytz', 'configparser'
                      'future', 'astropy', 'matplotlib', 'scipy', 'mongoengine', 'pymongo']
)
