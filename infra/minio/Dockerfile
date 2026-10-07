# MinIO built from source. MinIO no longer publishes community container images
# (the minio/minio repository was removed from Docker Hub), only source releases.
FROM golang:1.24-alpine AS build
RUN apk add --no-cache git
ARG MINIO_RELEASE=RELEASE.2025-10-15T17-29-55Z
RUN git clone --depth 1 --branch "${MINIO_RELEASE}" https://github.com/minio/minio /src
WORKDIR /src
RUN CGO_ENABLED=0 go build -trimpath -ldflags "-s -w" -o /out/minio .

FROM alpine:3
RUN apk add --no-cache ca-certificates \
 && adduser -D -u 1000 minio \
 && mkdir /data && chown minio /data
COPY --from=build /out/minio /usr/bin/minio
USER minio
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]
