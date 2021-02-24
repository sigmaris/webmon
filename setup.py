from setuptools import setup

setup(
    name="webmon",
    packages=["webmon"],
    version="0.1.0",
    description="A system that monitors website availability over a network",
    author="Hugh Cole-Baker",
    license="BSD",
    author_email="sigmaris@gmail.com",
    #    url='https://github.com/sigmaris/webmon',
    python_requires=">=3.7",
    install_requires=[
        f'psycopg2 ~= 2.8 ; sys_platform != "darwin"',
        f'psycopg2-binary ~= 2.8 ; sys_platform == "darwin"',
        "kafka-python ~= 2.0"
    ],
    extras_require={
        "dev": [
            "pytest ~= 6.2",
            "pytest-postgresql ~= 2.6",
        ]
    },
    entry_points={
        "console_scripts": ["webmon-recorder=webmon.recorder:run_recorder_app"],
    },
)
