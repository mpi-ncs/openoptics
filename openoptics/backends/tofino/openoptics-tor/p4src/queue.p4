#include "common/headers.p4"
#include "reg.p4"
control QueueManager (
        inout header_t hdr,
        inout metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md) {

    // ---------------------------------------------------------------------------
    // New-slice marker: tb_set_new_slice_for_p{P} sets ig_md.is_new_slice
    // when cur_slice matches a configured new-slice value.  The actual register
    // reset is done by the merged update_p{P}_max_lossless_qdepth RegisterAction
    // which branches on is_new_slice.
    // ---------------------------------------------------------------------------
    #define NEW_SLICE(P)    \
    action set_p## P ##_is_new_slice() {    \
        ig_md.p## P ##_is_new_slice = 1; \
    }   \
    \
    table tb_set_new_slice_for_p## P ## {     \
        key = { \
            ig_md.cur_slice         : exact@name("cur_slice");  \
            ig_intr_md.ingress_port : exact;    \
        }   \
        \
        actions = { \
            set_p## P ##_is_new_slice;  \
            @defaultonly NoAction;  \
        }   \
        const default_action = NoAction;    \
        size = 32;   \
    }   \
    \

    FOR_EACH_PORT(NEW_SLICE)

    // ---------------------------------------------------------------------------
    // AFC signaling table (keyed on app_id, cur_slice, packet_id)
    // ---------------------------------------------------------------------------
    DirectCounter<bit<32>>(CounterType_t.PACKETS) direct_counter;

    action set_afc(bit<32> afc_msg) {
        ig_intr_dprsr_md.adv_flow_ctl = afc_msg;
        direct_counter.count();
    }

    table set_afc_tb {
        key = {
            hdr.pktgen_timer.app_id : exact;
            ig_md.cur_slice         : exact@name("slice_id");
            ig_intr_md.ingress_port : exact;
        }
        actions = {
            set_afc;
        }
        size = 512;
        counters = direct_counter;
    }

    // ---------------------------------------------------------------------------
    // Per-port queue-depth update machinery
    //
    // Single RegisterAction on p{P}_max_lossless_qdepth_reg that BOTH resets
    // (when is_new_slice=1) and drains (when is_new_slice=0).  This avoids
    // multiple RegisterActions on the same register, which the Tofino compiler
    // gates with a $ena flag and effectively disables one of them.
    // ---------------------------------------------------------------------------
    #define QUEUE_UPDATE_DEFINE(P)  \
    bit<8> p## P ##_active_rank=0; \
    \
    RegisterParam<qdepth_t>(1) p## P ##_qdepth_diff; \
    \
    RegisterAction<qdepth_t, bit<8>, bit<1>>(p## P ##_qdepth_reg_table) update_p## P ##_qdepth_diff = { \
        void apply(inout qdepth_t qdepth, out bit<1> rv) { \
            qdepth = qdepth |-| p## P ##_qdepth_diff.read(); \
            rv = 0; \
        } \
    }; \
    \
    action update_p## P ##_qdepth_diff_action() { \
        update_p## P ##_qdepth_diff.execute(p## P ##_active_rank);  \
    }   \
    \
    RegisterParam<qdepth_t>(1) p## P ##_max_qdepth; \
    RegisterParam<qdepth_t>(1) p## P ##_lossless_qdepth_diff; \
    RegisterAction<qdepth_t, bit<8>, qdepth_t>(p## P ##_max_lossless_qdepth_reg) update_p## P ##_max_lossless_qdepth = {    \
        void apply(inout qdepth_t value, out qdepth_t rv) { \
            if (ig_md.p## P ##_is_new_slice == 8w1) {    \
                value = p## P ##_max_qdepth.read();  \
            } else {    \
                value = value |-| p## P ##_lossless_qdepth_diff.read();   \
            }   \
            rv = value; \
        }   \
    };  \
    \
    action update_p## P ##_max_lossless_qdepth_action() { \
        update_p## P ##_max_lossless_qdepth.execute(0);   \
    }   \
    \
    action compute_p## P ##_active_rank(bit<8> computed_rank) {   \
        p## P ##_active_rank = computed_rank; \
    }   \
    \
    table tb_compute_p## P ##_active_rank{    \
        key = { \
            ig_md.cur_slice : exact@name("cur_slice");  \
        }   \
        actions = { \
            compute_p## P ##_active_rank; \
        }   \
        size = 512; \
    }   \
    \

    FOR_EACH_PORT(QUEUE_UPDATE_DEFINE)


    // UPDATE_QDEPTH no longer calls update_p{P}_max_lossless_qdepth_action
    // (moved to a single unconditional call site below to avoid the compiler
    // creating multiple physical instances of the action with $ena gateways).
    #define UPDATE_QDEPTH(P) \
    tb_compute_p## P ##_active_rank.apply();  \
    update_p## P ##_qdepth_diff_action(); \

    apply {
        // default: drain mode on every port
        #define DEFAULT_NEW_SLICE(P) ig_md.p## P ##_is_new_slice = 0;
        FOR_EACH_PORT(DEFAULT_NEW_SLICE)
        #undef DEFAULT_NEW_SLICE

        if(hdr.ethernet.ether_type == ETHERTYPE_ROTATION) {
            // ig_md.cur_slice already set by cal_slice_1/2 + update_slice in Ingress.
            // tb_set_new_slice_for_p{P} sets p{P}_is_new_slice = 1 if (cur_slice,
            // ingress_port) matches — so only port P's own uplink triggers P's reset.
            #define APPLY_NEW_SLICE(P) tb_set_new_slice_for_p## P ##.apply();
            FOR_EACH_PORT(APPLY_NEW_SLICE)
            #undef APPLY_NEW_SLICE

            hdr.ethernet.ether_type = 0;
            set_afc_tb.apply();


        } else if(hdr.ethernet.ether_type == ETHERTYPE_UPDATEQD) {
            // all p{P}_is_new_slice stay 0 → drain mode
            FOR_EACH_PORT(UPDATE_QDEPTH)

            ig_intr_dprsr_md.drop_ctl = 0x1;
        }

        // Single call site for the merged register update.  Compiler sees
        // exactly one invocation → one physical instance → no $ena gateway.
        // - ROTATION + matched cur_slice: is_new_slice=1 → reset
        // - ROTATION + unmatched: is_new_slice=0 → drain (negligible)
        // - UPDATEQD: is_new_slice=0 → drain
        #define APPLY_UPDATE(P) update_p## P ##_max_lossless_qdepth_action();
        FOR_EACH_PORT(APPLY_UPDATE)
        #undef APPLY_UPDATE
    }
}
