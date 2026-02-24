from setuptools import setup, find_packages

setup(
    name="qa-agent",
    version="0.1.0",
    packages=find_packages(),
    entry_points={
        "console_scripts": [
            "qa-agent=qa_agent.cli:main",
        ],
    },
)
