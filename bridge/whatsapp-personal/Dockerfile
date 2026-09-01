FROM golang:1.22-bookworm AS build
WORKDIR /src
COPY go.mod ./
COPY *.go ./
# No go.sum is committed -- there's no Go toolchain in the environment this
# was written in to generate one for real. `go mod tidy` resolves and pins
# real versions here, at image-build time, where network access exists.
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /out/bridge .

FROM gcr.io/distroless/base-debian12
COPY --from=build /out/bridge /bridge
EXPOSE 8085
ENTRYPOINT ["/bridge"]
