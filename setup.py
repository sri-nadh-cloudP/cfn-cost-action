from setuptools import setup, find_packages

setup(
    name="cfn-sanitizer",
    version="0.1.0",
    packages=find_packages(),
    include_package_data=True,
    package_data={"cfn_sanitizer": ["patterns.yaml"]},
    install_requires=[
        "PyYAML>=5.4",
        "click>=8.0"
    ],
    entry_points={
        "console_scripts": [
            "sanitize-cfn=cfn_sanitizer.cli:main",
        ]
    },
    python_requires=">=3.6",
)
