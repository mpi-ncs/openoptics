# OpenOptics ns-3 contrib module.
#
# This file is symlinked into <NS3_DIR>/contrib/openoptics/CMakeLists.txt by
# `openoptics-install-ns3`; ns-3's top-level CMake discovers contrib modules
# automatically via `./ns3 configure`.

build_lib(
    LIBNAME openoptics
    SOURCE_FILES
        model/openoptics-header.cc
        model/openoptics-source-route-header.cc
        model/openoptics-ocs-app.cc
        model/openoptics-tor-app.cc
    HEADER_FILES
        model/openoptics-header.h
        model/openoptics-source-route-header.h
        model/openoptics-calendar-queue.h
        model/openoptics-ocs-app.h
        model/openoptics-tor-app.h
    LIBRARIES_TO_LINK
        ${libcore}
        ${libnetwork}
        ${libinternet}
        ${libapplications}
        ${libpoint-to-point}
)
