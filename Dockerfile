FROM python:3.11-slim

ENV CHROME_PATH=/usr/bin/google-chrome-stable
ENV LANG=zh_CN.UTF-8
ENV LANGUAGE=zh_CN
ENV LC_ALL=zh_CN.UTF-8
ENV DISPLAY=:99

RUN mkdir -p /app/

COPY . /app/
COPY supervisord.conf /etc/supervisord.conf
COPY start.sh /start.sh
RUN chmod +x /start.sh

# 安装 uv 与系统依赖
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    wget \
    gnupg \
    ca-certificates \
    xvfb \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    fonts-wqy-microhei \
    locales \
    curl \
    supervisor \
    x11vnc \
    net-tools \
    git \
    python3-numpy \
    python3-pil && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 添加 Google Chrome 官方 apt 源并安装 Chrome
RUN wget -qO /usr/share/keyrings/google-chrome.asc https://dl-ssl.google.com/linux/linux_signing_key.pub && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/google-chrome.asc] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends google-chrome-stable && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# 生成中文区域设置
RUN echo "zh_CN.UTF-8 UTF-8" > /etc/locale.gen && \
    locale-gen zh_CN.UTF-8 && \
    update-locale LANG=zh_CN.UTF-8 LANGUAGE=zh_CN:zh LC_ALL=zh_CN.UTF-8

# 安装 noVNC
RUN git clone --depth 1 https://github.com/novnc/noVNC.git /opt/noVNC && \
    git clone --depth 1 https://github.com/novnc/websockify /opt/noVNC/utils/websockify && \
    ln -s /opt/noVNC/vnc.html /opt/noVNC/index.html

# 使用 uv 安装 Python 依赖
RUN cd /app && \
    uv venv .venv && \
    uv sync --frozen --no-cache && \
    rm -rf /root/.cache

EXPOSE 9850 6080 5900

WORKDIR /app

CMD ["/start.sh"]
