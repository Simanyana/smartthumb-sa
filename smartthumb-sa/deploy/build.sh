#!/usr/bin/env bash
# Builds build/smartthumb.zip with Pillow compiled for the Lambda runtime (Linux x86_64, Python 3.12).
# Works from Windows (Git Bash/WSL), macOS or Linux because pip downloads the Linux wheel.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf build && mkdir -p build/pkg
pip install --quiet --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 \
  --only-binary=:all: --upgrade --target build/pkg -r requirements.txt
cp src/lambda_function.py build/pkg/
( cd build/pkg && python -c "
import shutil; shutil.make_archive('../smartthumb','zip','.')" )
ls -lh build/smartthumb.zip
