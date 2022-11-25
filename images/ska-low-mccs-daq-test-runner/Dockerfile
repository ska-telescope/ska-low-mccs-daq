FROM artefact.skao.int/ska-tango-images-pytango-builder:9.3.32 AS buildenv
FROM artefact.skao.int/ska-tango-images-pytango-runtime:9.3.19 AS runtime

RUN mkdir -p build/reports && \
  pip install -r requirements.txt
