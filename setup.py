from setuptools import setup, find_packages
import codecs

import gcalert

def long_description():
	with codecs.open('readme.md', encoding='utf8') as readme:
		return readme.read()

setup(
           name = gcalert.__program__,
        version = gcalert.__version__,
		 author = 'Kate Hart',
	description = 'Lightweight Google Calendar notifications',
	   keywords = 'google calendar notifications',
	        url = 'https://github.com/nejsan/gcalert',
	    license = 'GPLv3+',

	long_description = long_description(),
    packages = find_packages(),

	install_requires = [
		'notify2 >= 0.3',
		'python-dateutil >= 2.4.2',
		'google-api-python-client >= 1.4.2',
	],

	entry_points={
        'console_scripts': [
            'gcalert = gcalert.__main__:main',
        ],
    },

	classifiers = [
		'Intended Audience :: End Users/Desktop',
		'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
		'Environment :: Console',
		'Topic :: Terminals',
		'Intended Audience :: End Users/Desktop',
		'Development Status :: 4 - Beta',
	]
)
