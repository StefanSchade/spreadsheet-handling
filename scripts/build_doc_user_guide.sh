#! /bin/bash

VER="$(git describe --tags --always --dirty 2>/dev/null || echo DEV-SNAPSHOT)"
REV="$(git rev-parse --short HEAD 2>/dev/null || echo local)"

asciidoctor \
  -a project-version="$VER" \
  -a build-rev="$REV" \
  -a build-date="$(date -Iseconds)" \
  -D build/doc/user_guide \
  -o index.html \
  docs/user_guide/user_guide.adoc
