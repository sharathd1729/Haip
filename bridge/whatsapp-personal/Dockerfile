FROM golang:1.26-bookworm AS build
WORKDIR /src
# go.mod + go.sum pin every dependency (whatsmeow included) to an exact,
# checksum-verified version. Never run `go mod tidy` here: it would pull
# whatever is newest upstream on each rebuild. To upgrade, run
# `go get go.mau.fi/whatsmeow@latest && go mod tidy` locally and commit both files.
COPY go.mod go.sum ./
RUN go mod download && go mod verify
COPY *.go ./
RUN CGO_ENABLED=0 GOOS=linux go build -mod=readonly -o /out/bridge .

FROM gcr.io/distroless/base-debian12
COPY --from=build /out/bridge /bridge
EXPOSE 8085
ENTRYPOINT ["/bridge"]
