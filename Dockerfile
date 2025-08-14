ARG PARENT_VERSION=latest
FROM p4lang/p4c:${PARENT_VERSION}
LABEL maintainer="P4 Developers <p4-dev@lists.p4.org>"

COPY . /openoptics/
WORKDIR /

RUN apt-get update -qq && \
    apt-get install -qq --no-install-recommends \
    wget \
    python3 \
    python3-pip \
    python3-dev \
    make \
    g++ \
    autoconf \
    libtool

ENV BM_DEPS automake \
            build-essential \
            clang-8 \
            clang-10 \
            curl \
            git \
            lcov \
            libgmp-dev \
            libpcap-dev \
            libboost-dev \
            libboost-iostreams1.71.0 \
            libboost-program-options-dev \
            libboost-system-dev \
            libboost-filesystem-dev \
            libboost-thread-dev \
            libtool \
            pkg-config
ENV BM_RUNTIME_DEPS libboost-program-options1.71.0 \
                    libboost-system1.71.0 \
                    libboost-filesystem1.71.0 \
                    libboost-thread1.71.0 \
                    libgmp10 \
                    libpcap0.8 \
                    python3 \
                    python-is-python3
RUN apt-get update -qq && apt-get install -qq --no-install-recommends $BM_DEPS $BM_RUNTIME_DEPS

RUN pip install --upgrade pip
RUN pip install --upgrade setuptools wheel packaging
RUN pip install --no-cache-dir networkx matplotlib mininet
RUN pip install --no-cache-dir asgiref Django
RUN pip uninstall channels
# Install Django first then channels["daphne"] to avoid some errors for installing daphne
RUN pip install --no-cache-dir channels-redis channels["daphne"]
RUN pip install --no-cache-dir nnpy

RUN rm -rf /usr/local/bin/thrift /usr/local/include/thrift /usr/local/include/bm/ /usr/local/bin/bm_CLI /usr/local/bin/bm_nanomsg_events /usr/local/bin/bm_p4dbg  

WORKDIR /
RUN wget https://dlcdn.apache.org/thrift/0.22.0/thrift-0.22.0.tar.gz
RUN tar -xvf thrift-0.22.0.tar.gz
WORKDIR thrift-0.22.0
RUN ./bootstrap.sh
RUN ./configure
RUN make -j$(nproc)
RUN make install
RUN ldconfig
# This is for python can import thrift
WORKDIR /thrift-0.22.0/lib/py
RUN python3 -m pip install .

WORKDIR /
RUN git clone https://github.com/p4lang/behavioral-model.git
WORKDIR /behavioral-model
RUN git checkout 8e183a39b372cb9dc563e9d0cf593323249cd88b
RUN cp -r /openoptics/targets/tor_switch ./targets
RUN cp -r /openoptics/targets/optical_switch ./targets
RUN cp /openoptics/targets/configure.ac ./configure.ac
RUN cp /openoptics/targets/Makefile.am ./targets

RUN ./autogen.sh
#RUN ./configure 'CXXFLAGS=-O0 -g' --enable-debugger
RUN ./configure --enable-debugger
RUN make -j$(nproc)
RUN make install

RUN rm -r /openoptics/

RUN apt-get install -qq --no-install-recommends \
    git \
    mininet \
    lsb-release \
    iputils-ping \
    ssh \
    redis-server \
    ethtool

#networkx mininet Django matplotlib daphne channels-redis
RUN service redis-server start

#EXPOSE 5201/tcp 5201/udp
#EXPOSE 5001/tcp 5001/udp

WORKDIR ..