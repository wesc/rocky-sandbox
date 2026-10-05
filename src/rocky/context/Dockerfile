FROM debian:stable-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV SHELL=/bin/bash

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    iproute2 \
    iputils-ping \
    vim-tiny \
    git \
    less \
    sudo \
    build-essential \
    pkg-config \
    libssl-dev \
    ca-certificates \
    && apt-get autoremove --purge -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Toolchains live under /opt. /home/rocky is a mount, which hides anything the
# build puts there. The container's user takes the caller's uid at runtime, so
# no uid can own them: see the chmod below.
ENV NVM_DIR=/opt/nvm
ENV NODE_VERSION=26
ENV RUSTUP_HOME=/opt/rustup
ENV CARGO_HOME=/opt/cargo
ENV UV_INSTALL_DIR=/opt/uv/bin

# ~/.local/bin comes first, so a tool installed into the profile's home, such
# as Claude Code's own update, wins over the image's copy and outlives the
# container.
ENV PATH="/home/rocky/.local/bin:/opt/node/bin:/opt/cargo/bin:/opt/uv/bin:$PATH"

RUN mkdir -p "$NVM_DIR" "$RUSTUP_HOME" "$CARGO_HOME" "$UV_INSTALL_DIR"

# nvm's installer exits 1 if $NVM_DIR is not $HOME/.nvm and does not exist yet,
# hence the mkdir above. /opt/node points at the version nvm installed, so PATH
# never needs to name a version.
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.7/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install $NODE_VERSION \
    && nvm alias default $NODE_VERSION \
    && ln -s "$NVM_DIR/versions/node/$(ls $NVM_DIR/versions/node | tail -n 1)" /opt/node

# UV_INSTALL_DIR is an ENV, not an installer argument, so `uv self update` finds
# it at runtime.
RUN curl -LsSf https://astral.sh/uv/install.sh \
    | env INSTALLER_NO_MODIFY_PATH=1 sh

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs \
    | sh -s -- -y --default-toolchain stable --no-modify-path

# `rocky build --update` changes AGENTS_REFRESH, which rebuilds the layers from
# here down and keeps the toolchains above in the cache. A RUN must use the
# value, or the cache ignores it.
ARG AGENTS_REFRESH=0

RUN echo "agents refreshed at $AGENTS_REFRESH" > /opt/.agents-refresh \
    && npm install -g @anthropic-ai/claude-code \
    && npm install -g @agentclientprotocol/claude-agent-acp \
    && npm cache clean --force

RUN npm install -g --ignore-scripts @earendil-works/pi-coding-agent \
    && npm install -g --ignore-scripts @geohar/pi-acp \
    && npm cache clean --force

# Agents run `npm install -g`, Claude Code's updater, nvm, rustup and cargo as
# the caller, whose uid the image does not know. So every user may write the
# toolchains. That gives up nothing: the image's one user has passwordless
# sudo. This comes after the agent installs, to cover their node modules.
RUN chmod -R a+rwX /opt/nvm /opt/cargo /opt/rustup /opt/uv

# nvm is a shell function, so an interactive shell must source it. The system
# bashrc, not the skeleton's: a profile's home is seeded once and never sees a
# later image.
RUN printf '%s\n' '' \
    '# rocky: nvm is a shell function, so it has to be sourced to be usable.' \
    'if [ -s "$NVM_DIR/nvm.sh" ]; then . "$NVM_DIR/nvm.sh"; fi' \
    >> /etc/bash.bashrc

# The entrypoint replaces these ids with the caller's.
RUN groupadd -g 1000 rocky \
    && useradd -m -u 1000 -g 1000 -s /bin/bash rocky \
    && install -d -o 1000 -g 1000 /home/rocky/.local/bin \
    && echo 'rocky ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/rocky \
    && chmod 0440 /etc/sudoers.d/rocky

# The mount hides the home useradd made. The entrypoint copies this into a new
# profile.
RUN cp -a /home/rocky /opt/rocky-skel

# Programs test for /.rockyenv to tell they run in Rocky, as /.dockerenv tells
# them they run in docker. Keep it below the toolchains, so a change to it
# does not rebuild them.
RUN touch /.rockyenv

COPY entrypoint.sh /usr/local/bin/rocky-entrypoint
RUN chmod +x /usr/local/bin/rocky-entrypoint

ENTRYPOINT ["/usr/local/bin/rocky-entrypoint"]
CMD ["bash"]
