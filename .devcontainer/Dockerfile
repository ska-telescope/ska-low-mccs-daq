FROM artefact.skao.int/ska-build-python:0.1.1 AS build
RUN apt-get update && apt-get install git gnupg2 graphviz openssh-client plantuml -y

RUN useradd --create-home --home /home/vscoder --shell /bin/bash vscoder
USER vscoder

RUN pipx ensurepath && pipx install poetry
