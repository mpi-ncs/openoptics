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

/*************************************************************************
*********************** H E A D E R S  ***********************************
*************************************************************************/

typedef bit<9>  egressSpec_t;
typedef bit<48> macAddr_t;
typedef bit<32> ip4Addr_t;
typedef bit<32> time_t;

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

struct metadata {

}

struct headers {
    ethernet_t   ethernet;
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
            TYPE_OpenOptics: accept;
            //default: reject;
        }

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

    time_t time_slice = 0;

    action calculate_timeslice(bit<8> time_slice_nb_log2, bit<8> time_slice_duration_log2) {
        time_t ts = (time_t)standard_metadata.ingress_global_timestamp;
        time_t time_slice_absolute = ts >> time_slice_duration_log2;
        // Use bitmask to emulate modulo: x % 2^n = x & ((1 << n) - 1)
        time_slice = time_slice_absolute & ((1 << time_slice_nb_log2) - 1);
    }

    table timestamp_to_slice {
        key = {}
        actions = {calculate_timeslice;}
    }

    action drop() {
        mark_to_drop(standard_metadata);
    }

    action ocs_forward(egressSpec_t port) {
        standard_metadata.egress_spec = port;
    }

    //direct_counter(CounterType.packets) ocs_table_counter;

    table ocs_schedule {
        key = {
            standard_metadata.ingress_port : exact;
            //time_slice : exact;
    	    standard_metadata.ingress_global_timestamp: exact @name("time_slice");
        }
        actions = {
            ocs_forward;
            drop;
            NoAction;
        }
        size = 1024;
        default_action = NoAction();
        //counters = ocs_table_counter;
    }

    counter(512, CounterType.packets_and_bytes) port_counter;

    apply {
        //timestamp_to_slice.apply();
        //only if IPV4 the rule is applied. Therefore other packets will not be forwarded.
        port_counter.count((bit<32>)standard_metadata.ingress_port);
        if (hdr.ethernet.etherType == TYPE_OpenOptics) {
            ocs_schedule.apply();
        } else {
            mark_to_drop(standard_metadata);
        }

    }
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


    }
}


/*************************************************************************
***********************  D E P A R S E R  *******************************
*************************************************************************/

control MyDeparser(packet_out packet, in headers hdr) {
    apply {

        //parsed headers have to be added again into the packet.
        packet.emit(hdr.ethernet);

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
