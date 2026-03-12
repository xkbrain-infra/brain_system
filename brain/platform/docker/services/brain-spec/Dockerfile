FROM alpine:3.20 AS spec

LABEL org.opencontainers.image.title="brain-spec"
LABEL org.opencontainers.image.description="Brain spec distribution image"

WORKDIR /spec

COPY brain/base/spec/ /spec/

ARG SPEC_VERSION=dev
RUN echo "${SPEC_VERSION}" > /spec/.version
