# setup.py

from setuptools import setup, find_packages

setup(
    name='insighttrail',
    version='0.1.0',
    description='An observability tool for Microservice applications',
    author='Team InsightTrail',
    author_email='teaminsighttrail@gmail.com',
    packages=find_packages(),
    install_requires=[
        'Flask>=2.0',
    ],
)
