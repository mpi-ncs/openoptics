/*******************************************************************************
 *  INTEL CONFIDENTIAL
 *
 *  Copyright (c) 2021 Intel Corporation
 *  All Rights Reserved.
 *
 *  This software and the related documents are Intel copyrighted materials,
 *  and your use of them is governed by the express license under which they
 *  were provided to you ("License"). Unless the License provides otherwise,
 *  you may not use, modify, copy, publish, distribute, disclose or transmit
 *  this software or the related documents without Intel's prior written
 *  permission.
 *
 *  This software and the related documents are provided as is, with no express
 *  or implied warranties, other than those that are expressly stated in the
 *  License.
 ******************************************************************************/


#ifndef _HEADERS_
#define _HEADERS_

const int MCAST_GRP_ID = 1;

typedef bit<48> mac_addr_t;
typedef bit<32> ipv4_addr_t;
typedef bit<128> ipv6_addr_t;
typedef bit<12> vlan_id_t;

typedef bit<16> ether_type_t;
const ether_type_t ETHERTYPE_IPV4 = 16w0x0800;
const ether_type_t ETHERTYPE_ARP = 16w0x0806;
const ether_type_t ETHERTYPE_IPV6 = 16w0x86dd;
const ether_type_t ETHERTYPE_VLAN = 16w0x8100;

typedef bit<8> ip_protocol_t;
const ip_protocol_t IP_PROTOCOLS_ICMP = 1;
const ip_protocol_t IP_PROTOCOLS_TCP = 6;
const ip_protocol_t IP_PROTOCOLS_UDP = 17;

header ethernet_h {
    mac_addr_t dst_addr;
    mac_addr_t src_addr;
    bit<16> ether_type;
}

header vlan_tag_h {
    bit<3> pcp;
    bit<1> cfi;
    vlan_id_t vid;
    bit<16> ether_type;
}

header mpls_h {
    bit<20> label;
    bit<3> exp;
    bit<1> bos;
    bit<8> ttl;
}

header ipv4_h {
    bit<4> version;
    bit<4> ihl;
    bit<8> diffserv;
    bit<16> total_len;
    bit<16> identification;
    bit<3> flags;
    bit<13> frag_offset;
    bit<8> ttl;
    bit<8> protocol;
    bit<16> hdr_checksum;
    ipv4_addr_t src_addr;
    ipv4_addr_t dst_addr;
}

header ipv6_h {
    bit<4> version;
    bit<8> traffic_class;
    bit<20> flow_label;
    bit<16> payload_len;
    bit<8> next_hdr;
    bit<8> hop_limit;
    ipv6_addr_t src_addr;
    ipv6_addr_t dst_addr;
}

header tcp_h {
    bit<16> src_port;
    bit<16> dst_port;
    bit<32> seq_no;
    bit<32> ack_no;
    bit<4> data_offset;
    bit<4> res;
    bit<8> flags;
    bit<16> window;
    bit<16> checksum;
    bit<16> urgent_ptr;
}

header udp_h {
    bit<16> src_port;
    bit<16> dst_port;
    bit<16> hdr_length;
    bit<16> checksum;
}

header icmp_h {
    bit<8> type_;
    bit<8> code;
    bit<16> hdr_checksum;
}

// Address Resolution Protocol -- RFC 6747
header arp_h {
    bit<16> hw_type;
    bit<16> proto_type;
    bit<8> hw_addr_len;
    bit<8> proto_addr_len;
    bit<16> opcode;
    // ...
}


struct empty_header_t {}

struct empty_metadata_t {}

const ether_type_t ETHERTYPE_OPTICS = 16w0x3000;
const ether_type_t ETHERTYPE_ROTATION = 16w0x3001;
const ether_type_t ETHERTYPE_OPTICS_SR = 16w0x3003;

// SLICE_NUM must be set at compile time: p4_build.sh -DSLICE_NUM=8
#ifndef SLICE_NUM
#error "SLICE_NUM not defined. Pass -DSLICE_NUM=<value> to p4_build.sh."
#endif

const bit<4> PKTGEN_APP_ID_KICKOFF  = 7;
const bit<4> PKTGEN_APP_ID_ROTATION = 3;

typedef bit<32> qdepth_t;
typedef bit<16> slice_t;
typedef bit<32> ts_t;
typedef bit<9> port_t;

const bit<32> PORT_RATE = 100;
const bit<32> UPDATE_INTERVAL = 50;

header optics_l2_h {
    qdepth_t frame_size;
    qdepth_t es_qdepth;
    mac_addr_t next_tor;
    bit<16> hop_ctr; // Debug counter
    bit<16> elec_layer_ctr; // Emulate multiple hops in the electrical switches
    bit<16> intended_slice; // Telemetry
    bit<16> sync_error_flag; // Telemetry
}

struct metadata_t {
    slice_t cur_slice;
    slice_t _pad; // PHV pressure: keeps cur_slice in a 16-bit container for SALU access
}

struct header_t {
    pktgen_timer_header_t pktgen_timer;
    pktgen_deparser_header_t pktgen_dprsr;
    ethernet_h ethernet;
    ipv4_h ipv4;
    optics_l2_h optics_l2;
}


#endif /* _HEADERS_ */
