# setup.py

from setuptools import setup, find_packages
import os

# Read the contents of your README file
with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="insighttrail",
    version="0.1.0",
    author="Team InsightTrail", 
    author_email="teaminsighttrail@gmail.com", 
    description="An observability middleware for Flask with a real-time analytics UI.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/insightTrail/insighttrail", 
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        "Flask>=2.0",
        "psutil",
        "requests"
    ],
    classifiers=[
        "Development Status :: 4 - Beta",
        "Framework :: Flask",
        "Intended Audience :: Developers",
        "Topic :: System :: Logging",
        "Topic :: System :: Monitoring",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Operating System :: OS Independent",
    ],
    python_requires='>=3.7',
)
