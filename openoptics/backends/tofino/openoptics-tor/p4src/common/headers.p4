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

const bit<4> PKTGEN_APP_ID_KICKOFF = 7;

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

header udp_payload_h {
    ipv4_addr_t cur_direct_tor;
}

header udp_seq_payload_h {
    bit<32> seq;
    bit<16> hop_ctr;
    bit<16> sync_error_flag;
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
const ether_type_t ETHERTYPE_UPDATEQD = 16w0x3002;
const ether_type_t ETHERTYPE_OPTICS_SR = 16w0x3003;

// SLICE_NUM must be set at compile time: p4_build.sh -DSLICE_NUM=8
#ifndef SLICE_NUM
#error "SLICE_NUM not defined. Pass -DSLICE_NUM=<value> to p4_build.sh."
#endif
const mac_addr_t MY_MAC = 0xaaaaaaaaaaaa;

// ── Port count configuration ────────────────────────────────────────────────
// PORT_NUM must be set at compile time: p4_build.sh -DPORT_NUM=<value>
// (deploy.py forwards nb_link from the topology automatically).
// All per-port expansions in reg.p4, queue.p4, and routing.p4 follow automatically.
#ifndef PORT_NUM
#error "PORT_NUM not defined. Pass -DPORT_NUM=<value> to p4_build.sh."
#endif

#if PORT_NUM == 1
#  define FOR_EACH_PORT(M) M(0)
#elif PORT_NUM == 2
#  define FOR_EACH_PORT(M) M(0) M(1)
#elif PORT_NUM == 3
#  define FOR_EACH_PORT(M) M(0) M(1) M(2)
#elif PORT_NUM == 4
#  define FOR_EACH_PORT(M) M(0) M(1) M(2) M(3)
#else
#  error "Unsupported PORT_NUM (valid range: 1–4)"
#endif
// ────────────────────────────────────────────────────────────────────────────

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

// Source-routing entry carried on the wire. Holds the hop to consume at the
// NEXT ToR on the path. The source ToR never parses one (its own hop comes
// from the table action); intermediate ToRs parse exactly one entry, apply it,
// and invalidate before deparse so the final hop looks like a normal optics
// frame. Fixed 5-byte layout, one entry max — enough for 2-hop source paths.
header sr_entry_h {
    bit<8>  cur_node;    // ToR id this entry is intended for (drop-on-mismatch)
    slice_t send_slice;  // 16-bit slice id (next hop's send slice)
    bit<8>  send_port;   // logical uplink port (0..PORT_NUM-1)
    bit<8>  next_tor;    // 0x10 + tor_id of the hop AFTER this one
}

header rotation_h {
    bit<8> src_tor;
    slice_t slice_id;
}

@pa_container_size("ingress", "ig_md.p0_is_new_slice", 8)
#if PORT_NUM >= 2
@pa_container_size("ingress", "ig_md.p1_is_new_slice", 8)
#endif
#if PORT_NUM >= 3
@pa_container_size("ingress", "ig_md.p2_is_new_slice", 8)
#endif
#if PORT_NUM >= 4
@pa_container_size("ingress", "ig_md.p3_is_new_slice", 8)
#endif
struct metadata_t {
    slice_t cur_slice;
    bit<8>  p0_is_new_slice;   // 1 = reset max_lossless_qdepth_reg; 0 = drain
#if PORT_NUM >= 2
    bit<8>  p1_is_new_slice;
#endif
#if PORT_NUM >= 3
    bit<8>  p2_is_new_slice;
#endif
#if PORT_NUM >= 4
    bit<8>  p3_is_new_slice;
#endif
}

struct header_t {
    pktgen_timer_header_t pktgen_timer;
    pktgen_deparser_header_t pktgen_dprsr;
    ethernet_h ethernet;
    rotation_h rotation_msg;
    optics_l2_h optics_l2;
    sr_entry_h sr_entry;
    ipv4_h ipv4;
    ipv6_h ipv6;
    udp_h udp;
    udp_payload_h udp_payload;
    udp_seq_payload_h udp_seq_payload;
    // Add more headers here.
}


#endif /* _HEADERS_ */
