FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium \
    xvfb \
    xauth \
    ca-certificates \
    wget \
    fonts-wqy-zenhei \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

COPY --from=xpzouying/xiaohongshu-mcp:v1.2.1-arm64 /app /app
WORKDIR /app

ENV ROD_BROWSER_BIN=/usr/bin/chromium
ENV TZ=Asia/Shanghai
EXPOSE 18060
CMD ["./app"]
