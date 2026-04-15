#include <core.p4>
#if __TARGET_TOFINO__ == 2
#include <t2na.p4>
#else
#include <tna.p4>
#endif

#include "common/headers.p4"
#include "common/util.p4"

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
            PKTGEN_APP_ID_ROTATION : parse_pktgen;
            PKTGEN_APP_ID_KICKOFF  : parse_pktgen;
            default : parse_ethernet;
        }
    }

    state parse_pktgen {
        pkt.extract(hdr.pktgen_timer);
        transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select (hdr.ethernet.ether_type) {
            ETHERTYPE_ROTATION : accept;
            ETHERTYPE_IPV6 : accept;
            ETHERTYPE_IPV4 : accept;
            ETHERTYPE_OPTICS : parse_optics_l2;
            // Source-routed optics frames carry an extra sr_entry header
            // between ethernet and optics_l2. The OCS doesn't need to inspect
            // any of them — it forwards based on (cur_slice, ingress_port) only
            // — so we just accept the frame and let the deparser re-emit the
            // unparsed bytes as-is.
            ETHERTYPE_OPTICS_SR : accept;
            default : reject;
        }
    }

    state parse_optics_l2 {
        pkt.extract(hdr.optics_l2);
        transition accept;
    }
}


control Ingress(
        inout header_t hdr,
        inout metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md) {


        action set_egress_port(bit<9> egress_port) {
            ig_intr_tm_md.ucast_egress_port = egress_port;
        }

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
        RegisterAction<slice_t, bit<1>, slice_t>(slice_reg) incre_slice = {
            void apply(inout slice_t value, out slice_t rv) {
                if(value == (slice_t)SLICE_NUM-1) {
                    value = 0;
                } else {
                    value = value+1;
                }
                rv = value;
            }
        };

        action cal_slice_1() {
            ig_md.cur_slice = (slice_t)(hdr.pktgen_timer.batch_id << 1);
        }
        action cal_slice_2() {
            ig_md.cur_slice = ig_md.cur_slice + (slice_t)hdr.pktgen_timer.packet_id;
        }

        table ocs_table {
            key = {
                ig_md.cur_slice         : exact;
                ig_intr_md.ingress_port : exact;
            }
            actions = {
                set_egress_port;
                @defaultonly NoAction;
            }
            const default_action = NoAction;
            size = 512;
        }

        apply {

            if(hdr.ethernet.ether_type == ETHERTYPE_ROTATION) {
                if(hdr.pktgen_timer.isValid()) {
                    //The following calculation causes p4c error. Change to incrementing time slices.
                    //cal_slice_1();
                    //cal_slice_2();
                    //update_slice.execute(0);
                    
                    incre_slice.execute(0);
                }
                ig_intr_tm_md.mcast_grp_a = MCAST_GRP_ID;
                ig_intr_tm_md.rid = 0;

            } else {
                ig_md.cur_slice = read_slice.execute(0);
                ocs_table.apply();
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

    apply {
        pkt.emit(hdr);
    }
}

Pipeline(IngressParser(),
         Ingress(),
         IngressDeparser(),
         EmptyEgressParser(),
         EmptyEgress(),
         EmptyEgressDeparser()) pipe;

Switch(pipe) main;
