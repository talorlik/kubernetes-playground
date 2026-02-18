FROM fluent/fluentd:v1.16.5-debian-1.0
USER root

# For node/journal logs: libsystemd for fluent-plugin-systemd (native extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libsystemd-dev \
    && rm -rf /var/lib/apt/lists/*

RUN gem install elasticsearch -v 7.17.10 && \
  gem install fluent-plugin-elasticsearch --no-document --version 5.4.3 && \
  gem install fluent-plugin-systemd --no-document -v 1.0.3

# Switch to the desired user
USER fluent