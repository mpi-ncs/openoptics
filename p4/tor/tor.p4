/*
 * Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
 * Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
 *
 * Author: Yiming Lei (ylei@mpi-inf.mpg.de)
 *
 * This software is licensed for non-commercial scientific research purposes only.
 *
 * License text: Creative Commons NC BY SA 4.0
 * https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
 */

/* -*- P4_16 -*- */
#include <core.p4>
#include <v1model.p4>

const bit<16> TYPE_IPV4 = 0x800;
const bit<16> TYPE_OpenOptics = 0x100;

const bit<8> TYPE_SOURCE_ROUTING = 0x10;
const bit<8> TYPE_PER_HOP_ROUTING = 0x20;

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;

typedef bit<8>  node_t;
typedef bit<8>  ts_t;
typedef bit<8>  port_t;

header ethernet_t {
    macAddr_t dstAddr;
    macAddr_t srcAddr;
    bit<16>   etherType;
}

header ipv4_t {
    bit<4>    version;
    bit<4>    ihl;
    bit<8>    diffserv;
    bit<16>   totalLen;
    bit<16>   identification;
    bit<3>    flags;
    bit<13>   fragOffset;
    bit<8>    ttl;
    bit<8>    protocol;
    bit<16>   hdrChecksum;
    ip4Addr_t srcAddr;
    ip4Addr_t dstAddr;
}

header oo_t {
    bit<8> forward_type; //source routing or per-hop routing
    node_t dst_node;
}

header source_routing_1_t {
    node_t cur_node;
    ts_t send_time_slice;
    port_t send_port_or_node;
}

header source_routing_2_t {
    node_t cur_node;
    ts_t send_time_slice;
    port_t send_port_or_node;

    node_t cur_node_2;
    ts_t send_time_slice_2;
    port_t send_port_or_node_2;
}

header source_routing_3_t {
    node_t cur_node;
    ts_t send_time_slice;
    port_t send_port_or_node;

    node_t cur_node_2;
    ts_t send_time_slice_2;
    port_t send_port_or_node_2;

    node_t cur_node_3;
    ts_t send_time_slice_3;
    port_t send_port_or_node_3;
}

header time_flow_entry_t {
    node_t cur_node;
    ts_t send_time_slice; // 255 for sending to a node
    port_t send_port_or_node;
}

struct metadata {
    ts_t send_time_slice;
    time_flow_entry_t time_flow_entry;
	bit<1> intermediateForward;
}

struct headers {
    ethernet_t   ethernet;
    oo_t oo_preamble;
    source_routing_1_t ssrr_1_hop;
    source_routing_2_t ssrr_2_hop;
    source_routing_3_t ssrr_3_hop;
    ipv4_t       ipv4;
}

/*************************************************************************
*********************** P A R S E R  ***********************************
*************************************************************************/

parser MyParser(packet_in packet,
                out headers hdr,
                inout metadata meta,
                inout standard_metadata_t standard_metadata) {

    state start {
        packet.extract(hdr.ethernet);
        transition select(hdr.ethernet.etherType){
            TYPE_IPV4: ipv4;
            TYPE_OpenOptics: extract_openoptics_preamble;
            //default: accept;
        }
    }

    state ipv4 {
        packet.extract(hdr.ipv4);
        transition accept;
    }

    state extract_openoptics_preamble {

        packet.extract(hdr.oo_preamble);
        transition select(hdr.oo_preamble.forward_type) {
            TYPE_PER_HOP_ROUTING  :  accept; // pending ssrr entry
            TYPE_SOURCE_ROUTING   :  extract_remaining_ssrr; // valid ssrr entry
        }
    }

    state extract_remaining_ssrr {

        packet.extract(meta.time_flow_entry);
        transition accept;
    }

}


/*************************************************************************
************   C H E C K S U M    V E R I F I C A T I O N   *************
*************************************************************************/

control MyVerifyChecksum(inout headers hdr, inout metadata meta) {
    apply {  }
}


/*************************************************************************
**************  I N G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyIngress(inout headers hdr,
                  inout metadata meta,
                  inout standard_metadata_t standard_metadata) {

    ts_t arrival_time_slice;

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ts_to_slice() {
        // target tor_switch reuses ingress_global_timestamp as time slice.
        arrival_time_slice = (ts_t)standard_metadata.ingress_global_timestamp;
    }

    action write_dst(node_t dst_tor_in) {
        hdr.oo_preamble.dst_node = dst_tor_in;
    }

    table ip_to_dst_node {
        key = {
            hdr.ipv4.dstAddr   : exact;
        }
        actions = {
            write_dst;
        }
        size = 512;
    }

    action write_ssrr_header_0(
        node_t cur_node,
        ts_t send_time_slice,
        port_t send_port_or_node
        ) {

        meta.time_flow_entry.setValid();
        meta.time_flow_entry.cur_node = cur_node;
        meta.time_flow_entry.send_time_slice = send_time_slice;
        meta.time_flow_entry.send_port_or_node = send_port_or_node;
    }

    action write_ssrr_header_1(
        node_t cur_node,
        ts_t send_time_slice,
        port_t send_port_or_node,
        node_t cur_node_1,
        ts_t send_time_slice_1,
        port_t send_port_or_node_1
        ) {

        meta.time_flow_entry.setValid();
        meta.time_flow_entry.cur_node = cur_node;
        meta.time_flow_entry.send_time_slice = send_time_slice;
        meta.time_flow_entry.send_port_or_node = send_port_or_node;

        hdr.ssrr_1_hop.setValid();
        hdr.ssrr_1_hop.cur_node = cur_node_1;
        hdr.ssrr_1_hop.send_time_slice = send_time_slice_1;
        hdr.ssrr_1_hop.send_port_or_node = send_port_or_node_1;
    }

    action write_ssrr_header_2(
        node_t cur_node,
        ts_t send_time_slice,
        port_t send_port_or_node,
        node_t cur_node_1,
        ts_t send_time_slice_1,
        port_t send_port_or_node_1,
        node_t cur_node_2,
        ts_t send_time_slice_2,
        port_t send_port_or_node_2
        ) {

        meta.time_flow_entry.setValid();
        meta.time_flow_entry.cur_node = cur_node;
        meta.time_flow_entry.send_time_slice = send_time_slice;
        meta.time_flow_entry.send_port_or_node = send_port_or_node;

        hdr.ssrr_2_hop.setValid();
        hdr.ssrr_2_hop.cur_node = cur_node_1;
        hdr.ssrr_2_hop.send_time_slice = send_time_slice_1;
        hdr.ssrr_2_hop.send_port_or_node = send_port_or_node_1;

        hdr.ssrr_2_hop.cur_node_2 = cur_node_2;
        hdr.ssrr_2_hop.send_time_slice_2 = send_time_slice_2;
        hdr.ssrr_2_hop.send_port_or_node_2 = send_port_or_node_2;
    }
    
    
    table add_source_routing_entries {
        key = {
            hdr.oo_preamble.dst_node  : exact;
            arrival_time_slice : exact;
        }
        actions = {
            write_ssrr_header_0;
            write_ssrr_header_1;
            write_ssrr_header_2;
            drop;
        }
        size = 1024;
    }

    action write_time_flow_entry(
        node_t cur_node,
        ts_t send_time_slice,
        port_t send_port_or_node
        ) {

        meta.time_flow_entry.setValid();
        meta.time_flow_entry.cur_node = cur_node;
        meta.time_flow_entry.send_port_or_node = send_port_or_node;
        meta.time_flow_entry.send_time_slice = send_time_slice;
    }

    table per_hop_routing {
        key = {
            hdr.oo_preamble.dst_node  : exact;
            arrival_time_slice : exact;
        }
        actions = {
            write_time_flow_entry;
        }
    }

    action to_calendar_q(bit<9> egress_port, ts_t send_time_slice) {
        meta.send_time_slice = send_time_slice;
        standard_metadata.egress_spec = egress_port;

        hdr.ipv4.ttl = hdr.ipv4.ttl -1;
    }

    action to_calendar_q_table_action(bit<9> egress_port, ts_t send_time_slice) {
        meta.send_time_slice = send_time_slice;
        standard_metadata.egress_spec = egress_port;

        hdr.ipv4.ttl = hdr.ipv4.ttl -1;
    }

    table cal_port_slice_to_node {
        key = {
            meta.time_flow_entry.send_port_or_node : exact; // send_node
            arrival_time_slice : exact;
        }
        actions = {
            to_calendar_q_table_action;
            drop;
        }
        default_action = drop;
    }

    table verify_desired_node {
        key = {
            meta.time_flow_entry.cur_node : exact;
        }
        actions = {
            NoAction;
        }
    }

    action send_to_host(bit<9> egress_port) {
        meta.intermediateForward = 1; // Maybe useful. Let's see.
        standard_metadata.egress_spec = egress_port;
    }

    table arrive_at_dst {
        key = {
            hdr.oo_preamble.dst_node : exact;
        }
        actions = {
            send_to_host;
        }
    }

    apply {
		
        ts_to_slice(); //Set arrival time slice
        
        // Prepare oo_preamble header and meta.time_flow_entry
        if (hdr.ipv4.isValid()) { // sent from the host
            //Add source routing table
            hdr.ethernet.etherType = TYPE_OpenOptics;
            hdr.oo_preamble.setValid();
		    meta.intermediateForward = 0; //to-be-removed

            ip_to_dst_node.apply(); //Set dst node

            if (add_source_routing_entries.apply().hit) {
                // add source routing header and set type
                hdr.oo_preamble.forward_type = TYPE_SOURCE_ROUTING;

            } else {
                // set type
                hdr.oo_preamble.forward_type = TYPE_PER_HOP_ROUTING;

            }
		  
		}
        
        // Enforce forwarding
        if (hdr.oo_preamble.isValid()) { 
            if (arrive_at_dst.apply().hit) {
                // Arrived at dst. Send to host
                
                if (hdr.oo_preamble.forward_type == TYPE_SOURCE_ROUTING &&
                    meta.time_flow_entry.cur_node != 255 // 255 means it is the second hop of vlb. 
                    //It luck to reach dst at the first hop. We need to extract the additional hop
                    ) {
                    // In source routing last hop, we have extracted one extra time_flow_entry header. Append back.
                    hdr.ssrr_1_hop.setValid();
                    hdr.ssrr_1_hop.cur_node = meta.time_flow_entry.cur_node;
                    hdr.ssrr_1_hop.send_port_or_node = meta.time_flow_entry.send_port_or_node;
                    hdr.ssrr_1_hop.send_time_slice = meta.time_flow_entry.send_time_slice;
                }

                hdr.oo_preamble.setInvalid();
                hdr.ethernet.etherType = TYPE_IPV4;


            } else {
                //enqueue for per-hop and source routing
                if(per_hop_routing.apply().hit || hdr.oo_preamble.forward_type == TYPE_SOURCE_ROUTING) {

                    //Send to calendar q for source routing and per-hop routing
                    if (meta.time_flow_entry.send_time_slice == 255) { // Send to next node
                        cal_port_slice_to_node.apply(); // Find the next direct connection to next_node
                    } else { // send to port at time slice
                        to_calendar_q(send_time_slice = meta.time_flow_entry.send_time_slice,
                            egress_port = (bit<9>)meta.time_flow_entry.send_port_or_node);
                    }
                } else {
                    // make sure no match will drop
                    mark_to_drop(standard_metadata);
                }
                
                
                if (hdr.oo_preamble.forward_type == TYPE_SOURCE_ROUTING && 
                    verify_desired_node.apply().miss) {
                    // Desired node is not it self. Miss slice. Drop.
                    // To-do: re-route.
                    mark_to_drop(standard_metadata);
                }
            }
            
        } else {
            //Drop other packets
            mark_to_drop(standard_metadata);
        }

    }//End of ingress
}

/*************************************************************************
****************  E G R E S S   P R O C E S S I N G   *******************
*************************************************************************/

control MyEgress(inout headers hdr,
                 inout metadata meta,
                 inout standard_metadata_t standard_metadata) {
    counter(512, CounterType.packets_and_bytes) port_counter;

    apply {
        port_counter.count((bit<32>)standard_metadata.egress_port);
    }
}

/*************************************************************************
*************   C H E C K S U M    C O M P U T A T I O N   **************
*************************************************************************/

control MyComputeChecksum(inout headers hdr, inout metadata meta) {
     apply {
    update_checksum(
        hdr.ipv4.isValid(),
            { hdr.ipv4.version,
          hdr.ipv4.ihl,
              hdr.ipv4.diffserv,
              hdr.ipv4.totalLen,
              hdr.ipv4.identification,
              hdr.ipv4.flags,
              hdr.ipv4.fragOffset,
              hdr.ipv4.ttl,
              hdr.ipv4.protocol,
              hdr.ipv4.srcAddr,
              hdr.ipv4.dstAddr },
            hdr.ipv4.hdrChecksum,
            HashAlgorithm.csum16);
    }
}


/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/

control MyDeparser(packet_out packet, in headers hdr) {
    apply {

        //parsed headers have to be added again into the packet.
        packet.emit(hdr);

    }
}

/*************************************************************************
***********************  S W I T C H  *******************************
*************************************************************************/

//switch architecture
V1Switch(
    MyParser(),
    MyVerifyChecksum(),
    MyIngress(),
    MyEgress(),
    MyComputeChecksum(),
    MyDeparser()
) main;
