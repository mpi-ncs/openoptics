#include <core.p4>
#if __TARGET_TOFINO__ == 2
#include <t2na.p4>
#define PKTGEN_PORT1 6
#else
#include <tna.p4>
#define PKTGEN_PORT1 68
#endif

#include "common/headers.p4"
#include "common/util.p4"
#include "queue.p4"
#include "routing.p4"

// ---------------------------------------------------------------------------
// Ingress parser
// ---------------------------------------------------------------------------
parser IngressParser(
        packet_in pkt,
        out header_t hdr,
        out metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {

    TofinoIngressParser() tofino_parser;

    state start {
        tofino_parser.apply(pkt, ig_intr_md);

        pktgen_timer_header_t pktgen_pd_hdr = pkt.lookahead<pktgen_timer_header_t>();
        transition select(pktgen_pd_hdr.app_id) {
            1 : parse_pktgen;
            2 : parse_pktgen;
            3 : parse_dp_triggered_pktgen;
            4 : parse_pktgen;
            5 : parse_pktgen;
            6 : parse_pktgen;
            7 : parse_kickoff_pktgen;
            default : parse_ethernet;
        }
    }

    state parse_dp_triggered_pktgen {
        pkt.extract(hdr.pktgen_timer);
        transition parse_ethernet;
    }

    state parse_kickoff_pktgen {
        pkt.extract(hdr.pktgen_timer);
        transition accept;
    }

    state parse_pktgen {
        pkt.extract(hdr.pktgen_timer);
        transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select (hdr.ethernet.ether_type) {
            ETHERTYPE_ROTATION : parse_rotation;
            ETHERTYPE_UPDATEQD : accept;
            ETHERTYPE_IPV6 : parse_ipv6;
            ETHERTYPE_OPTICS : parse_optics;
            ETHERTYPE_OPTICS_SR : parse_optics_sr;
            ETHERTYPE_IPV4 : parse_ipv4;
            default : reject;
        }
    }

    // For OPTICS_SR packets the wire format is
    //     ethernet | optics_l2 | sr_entry | ipv4
    // (header order matches struct header_t). Use a dedicated parser state
    // for the SR case: Tofino's parser cannot re-examine hdr.ethernet.ether_type
    // in a select after it's been extracted, so we can't conditionally branch
    // on ether_type inside parse_optics. Splitting the state keeps the
    // transition graph explicit.
    state parse_optics {
        pkt.extract(hdr.optics_l2);
        transition parse_ipv4;
    }

    state parse_optics_sr {
        pkt.extract(hdr.optics_l2);
        transition parse_sr_entry;
    }

    state parse_sr_entry {
        pkt.extract(hdr.sr_entry);
        transition parse_ipv4;
    }

    state parse_rotation {
        pkt.extract(hdr.rotation_msg);
        transition accept;
    }

    state parse_ipv4 {
        pkt.extract(hdr.ipv4);
        transition select (hdr.ipv4.protocol) {
            IP_PROTOCOLS_ICMP : accept;
            IP_PROTOCOLS_TCP : accept;
            IP_PROTOCOLS_UDP : parse_udp_seq_payload;
            default : accept;
        }
    }

    state parse_udp_seq_payload {
        pkt.extract(hdr.udp);
        transition accept;
    }

    state parse_ipv6 {
        pkt.extract(hdr.ipv6);
        transition select (hdr.ipv6.next_hdr) {
            default : accept;
        }
    }

}



control Ingress(
        inout header_t hdr,
        inout metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md) {

        QueueManager() queue_mgr;
        RoutingDecision() routing;

        Register<slice_t, bit<1>>(size = 1, initial_value=(bit<16>)SLICE_NUM-1) slice_reg;
        RegisterAction<slice_t, bit<1>, slice_t>(slice_reg) read_slice = {
            void apply(inout slice_t value, out slice_t rv) {
                rv = value;
            }
        };

        RegisterAction<slice_t, bit<1>, slice_t>(slice_reg) update_slice = {
            void apply(inout slice_t value, out slice_t rv) {
                value = ig_md.cur_slice;
                rv = value;
            }
        };

        action cal_slice_1() {
            ig_md.cur_slice = (slice_t)(hdr.pktgen_timer.batch_id << 1);
        }

        action cal_slice_2() {
            ig_md.cur_slice = ig_md.cur_slice + (slice_t)hdr.pktgen_timer.packet_id;
        }

        apply {

            if(hdr.pktgen_timer.app_id == PKTGEN_APP_ID_KICKOFF) {
                ig_intr_dprsr_md.pktgen = 1;
                ig_intr_dprsr_md.pktgen_address = 0;
                ig_intr_dprsr_md.pktgen_length = 64;

            } else if(hdr.ethernet.ether_type == ETHERTYPE_ROTATION) {
                cal_slice_1();
                cal_slice_2();
                update_slice.execute(0);
                queue_mgr.apply(hdr, ig_md, ig_intr_md, ig_intr_prsr_md, ig_intr_dprsr_md, ig_intr_tm_md);

            } else {
                ig_md.cur_slice = read_slice.execute(0);
                if(hdr.ethernet.ether_type == ETHERTYPE_UPDATEQD) {
                    queue_mgr.apply(hdr, ig_md, ig_intr_md, ig_intr_prsr_md, ig_intr_dprsr_md, ig_intr_tm_md);
                } else {
                    routing.apply(hdr, ig_md, ig_intr_md, ig_intr_prsr_md, ig_intr_dprsr_md, ig_intr_tm_md);
                }
            }

            ig_intr_tm_md.bypass_egress = 1w1;
        }
}


// ---------------------------------------------------------------------------
// Ingress Deparser
// ---------------------------------------------------------------------------
control IngressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in metadata_t ig_md,
        in ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md) {

    Checksum() ipv4_checksum;

    apply {
        pkt.emit(hdr);
    }
}


// Single pipeline deployed across all 4 physical Tofino2 pipes.
// Per-ToR differentiation is done in setup_tor.py by scoping
// each bfrt table operation to a specific pipe (pipe 0–3 = ToR 0–3).
Pipeline(IngressParser(),
         Ingress(),
         IngressDeparser(),
         EmptyEgressParser(),
         EmptyEgress(),
         EmptyEgressDeparser()) tor_pipe;

Switch(tor_pipe) main;
