#include "common/headers.p4"
#include "reg.p4"

control RoutingDecision (
        inout header_t hdr,
        inout metadata_t ig_md,
        in ingress_intrinsic_metadata_t ig_intr_md,
        in ingress_intrinsic_metadata_from_parser_t ig_intr_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_intr_tm_md) {

    slice_t send_slice = 0;
    slice_t dst_group = 0;
    bit<9> send_port = 0;
    mac_addr_t next_hop = 0;

    slice_t alternate_send_slice = 0;
    bit<9> alternate_send_port = 0;
    mac_addr_t alternate_next_hop = 0;
    bit<8> alternate_rank = 0;

    const bit<9> to_server_port = 0xff;
    bit<1> enqueue = 0;

    // ---------------------------------------------------------------------------
    // Per-port admission control machinery (normal traffic path)
    // ---------------------------------------------------------------------------
    #define PORT_DEFINE(P)  \
    bit<8> p## P ##_rank=0;   \
    qdepth_t p## P ##_max_lossless_qdepth = 0;    \
    \
    RegisterAction<qdepth_t, bit<8>, qdepth_t>(p## P ##_max_lossless_qdepth_reg) read_p## P ##_max_lossless_qdepth = {  \
        void apply(inout qdepth_t value, out qdepth_t rv) { \
            rv = value; \
        }   \
    };  \
    \
    action read_p## P ##_max_lossless_qdepth_action() {   \
        p## P ##_max_lossless_qdepth = read_p## P ##_max_lossless_qdepth.execute(0);    \
    }   \
    \
    RegisterAction2<qdepth_t, bit<8>, qdepth_t, qdepth_t>(p## P ##_qdepth_reg_table) update_p## P ##_qdepth = { \
        void apply(inout qdepth_t qdepth, out qdepth_t rv_enqueue, out qdepth_t rv_es_qdepth) { \
            if(qdepth >= p## P ##_max_lossless_qdepth) {  \
                rv_enqueue = 0; \
            } else {    \
                rv_es_qdepth = qdepth;  \
                qdepth = qdepth + hdr.optics_l2.frame_size;   \
                rv_enqueue = 1; \
            }   \
        }   \
    };  \
    \
    action update_p## P ##_qdepth_action(){   \
        enqueue = (bit<1>)update_p## P ##_qdepth.execute(p## P ##_rank, hdr.optics_l2.es_qdepth); \
    }   \
    \
    action p## P ##_count_pkt_size_for_active_queue_action(){ \
        p## P ##_max_lossless_qdepth = p## P ##_max_lossless_qdepth |-| hdr.optics_l2.frame_size; \
    }   \
    \
    action read_p## P ##_paused_max_qdepth_action(qdepth_t max_qdepth){ \
        p## P ##_max_lossless_qdepth = max_qdepth; \
    }   \
    action p## P ##_count_pkt_size_for_paused_queue_action(){ \
        p## P ##_max_lossless_qdepth = p## P ##_max_lossless_qdepth |-| hdr.optics_l2.frame_size; \
    }   \
    table tb_read_p## P ##_max_qdepth{   \
        key = { \
               \
        }   \
        actions = { \
            read_p## P ##_paused_max_qdepth_action;    \
        }   \
        size = 8; \
    }   \
    \
    action compute_p## P ##_rank(bit<8> computed_rank) { \
        p## P ##_rank = computed_rank;    \
    }   \
    \
    table tb_compute_p## P ##_rank{   \
        key = { \
            send_slice : exact;   \
        }   \
        actions = { \
            compute_p## P ##_rank;    \
        }   \
        size = 512; \
    }   \
    \

    FOR_EACH_PORT(PORT_DEFINE)

    // ---------------------------------------------------------------------------
    // Frame size adjustment (header overhead)
    // ---------------------------------------------------------------------------
    action add_ipv4_length(qdepth_t adjustment) {
        hdr.optics_l2.frame_size = hdr.optics_l2.frame_size + adjustment;
    }

    action add_ipv6_length(qdepth_t adjustment) {
        hdr.optics_l2.frame_size = hdr.optics_l2.frame_size + adjustment;
    }

    table tb_adjust_optics_frame_size {
        key = {
            hdr.ethernet.ether_type : exact;
        }
        actions = {
            add_ipv4_length;
            add_ipv6_length;
        }
        size = 8;
    }

    action nop() {}

    // ---------------------------------------------------------------------------
    // Source-ToR IP → dst-MAC rewrite (eliminates static ARP on servers)
    //
    // Servers send packets with whatever MAC normal Linux ARP produces (a dummy).
    // The source ToR looks up the destination IP and overwrites hdr.ethernet.dst_addr
    // with the magic MAC (0x000000000010 + dst_tor_id).  The existing
    //     dst_group = (bit<16>)hdr.ethernet.dst_addr
    // then picks up the rewritten MAC, so all downstream logic (time_flow_table_*,
    // tb_check_to_server) is unchanged.
    // ---------------------------------------------------------------------------
    DirectCounter<bit<32>>(CounterType_t.PACKETS) ip_to_dst_mac_counter;

    action rewrite_dst_mac(mac_addr_t dst_mac) {
        hdr.ethernet.dst_addr = dst_mac;
        ip_to_dst_mac_counter.count();
    }

    table tb_ipv4_to_dst_mac {
        key = {
            hdr.ipv4.dst_addr : exact;
        }
        actions = {
            rewrite_dst_mac;
            @defaultonly nop;
        }
        const default_action = nop;
        size = 256;
        counters = ip_to_dst_mac_counter;
    }

    DirectCounter<bit<32>>(CounterType_t.PACKETS) ipv6_to_dst_mac_counter;

    action rewrite_dst_mac_v6(mac_addr_t dst_mac) {
        hdr.ethernet.dst_addr = dst_mac;
        ipv6_to_dst_mac_counter.count();
    }

    table tb_ipv6_to_dst_mac {
        key = {
            hdr.ipv6.dst_addr : exact;
        }
        actions = {
            rewrite_dst_mac_v6;
            @defaultonly nop;
        }
        const default_action = nop;
        size = 256;
        counters = ipv6_to_dst_mac_counter;
    }

    // ---------------------------------------------------------------------------
    // HoHo routing: primary send-slice lookup
    // ---------------------------------------------------------------------------
    Register<bit<16>, bit<16>>(size = 1) hop_reg;
    RegisterAction<bit<16>, bit<8>, bit<16>>(hop_reg) record_hop_count = {
        void apply(inout bit<16> value) {
            if (hdr.optics_l2.hop_ctr > value)
                value = hdr.optics_l2.hop_ctr;
        }
    };

    DirectCounter<bit<32>>(CounterType_t.PACKETS) optics_counter;

    action set_send_slice (bit<8> port, slice_t slot, bit<8> next_tor,
            bit<8> alternate_port, slice_t alternate_slot, bit<8> alternate_next_tor,
            bit<8> alt_rank) {
        send_port = (bit<9>)port;
        send_slice = slot;
        next_hop = (mac_addr_t)next_tor;

        alternate_send_slice = alternate_slot;
        alternate_next_hop = (mac_addr_t)alternate_next_tor;
        alternate_send_port = (bit<9>)alternate_port;
        alternate_rank = alt_rank;

        optics_counter.count();
    }

    table time_flow_table_per_hop{
        key = {
            ig_md.cur_slice : exact;
            dst_group : exact;
        }
        actions = {
            set_send_slice;
            @defaultonly nop;
        }
        const default_action = nop;
        size = 512;
        counters = optics_counter;
    }

    // ---------------------------------------------------------------------------
    // Source routing: per-(cur_slice, dst) path lookup at the source ToR.
    //
    // A 1-hop path uses set_sr_1_hops (identical to the per-hop action — the
    // hop is consumed at this ToR and nothing rides on the wire). A 2-hop
    // path uses set_sr_2_hops: hop-0 drives this ToR's egress, and hop-1 is
    // written into hdr.sr_entry so the next ToR can consume it without
    // another table lookup. ether_type is flipped to OPTICS_SR so the next
    // ToR's parser extracts sr_entry.
    // ---------------------------------------------------------------------------
    DirectCounter<bit<32>>(CounterType_t.PACKETS) source_routing_counter;

    // Source routing has no admission-control fallback: the entire path is
    // pre-computed at the source, so there's no meaningful alternate to bounce
    // to. The action signatures therefore don't take alternate_* params; we
    // still assign alternate_* = primary internally to keep the compiler's
    // data-flow analysis happy (otherwise bf-p4c hits an ICE when reading
    // uninitialized alternate_* in the later ENQUEUE machinery).

    action set_sr_1_hops(bit<8> port, slice_t slot, bit<8> next_tor) {
        send_port = (bit<9>)port;
        send_slice = slot;
        next_hop = (mac_addr_t)next_tor;

        alternate_send_port = (bit<9>)port;
        alternate_send_slice = slot;
        alternate_next_hop = (mac_addr_t)next_tor;

        source_routing_counter.count();
    }

    action set_sr_2_hops(bit<8> port, slice_t slot, bit<8> next_tor,
            bit<8> hop1_cur_node, slice_t hop1_send_slice,
            bit<8> hop1_send_port, bit<8> hop1_next_tor) {
        send_port = (bit<9>)port;
        send_slice = slot;
        next_hop = (mac_addr_t)next_tor;

        alternate_send_port = (bit<9>)port;
        alternate_send_slice = slot;
        alternate_next_hop = (mac_addr_t)next_tor;

        hdr.sr_entry.setValid();
        hdr.sr_entry.cur_node = hop1_cur_node;
        hdr.sr_entry.send_slice = hop1_send_slice;
        hdr.sr_entry.send_port = hop1_send_port;
        hdr.sr_entry.next_tor = hop1_next_tor;
        hdr.ethernet.ether_type = ETHERTYPE_OPTICS_SR;

        source_routing_counter.count();
    }

    table time_flow_table_source{
        key = {
            ig_md.cur_slice : exact;
            dst_group : exact;
        }
        actions = {
            set_sr_1_hops;
            set_sr_2_hops;
            @defaultonly nop;
        }
        const default_action = nop;
        size = 512;
        counters = source_routing_counter;
    }

    // Load send_port / send_slice / next_hop from the carried sr_entry header
    // at a transit ToR. Alternate_* are set equal to primary (SR carries no
    // admission-control fallback — the entire path is pre-computed).
    //
    // NOTE: a cur_node sanity check (drop packets that arrived at an unexpected
    // intermediate) was prototyped with a verify_sr_cur_node table but removed.
    // The Tofino PHV scheduler kept reading the check key at a stage where the
    // metadata had been overwritten by a mutex-allocated field, causing all
    // legitimate transit packets to drop. Since the source ToR precomputes the
    // whole path correctly, the check is redundant in practice.
    action apply_sr_entry() {
        send_port = (bit<9>)hdr.sr_entry.send_port;
        send_slice = hdr.sr_entry.send_slice;
        next_hop = (mac_addr_t)hdr.sr_entry.next_tor;

        alternate_send_port = (bit<9>)hdr.sr_entry.send_port;
        alternate_send_slice = hdr.sr_entry.send_slice;
        alternate_next_hop = (mac_addr_t)hdr.sr_entry.next_tor;
    }

    // ---------------------------------------------------------------------------
    // Generic sentinel: random port at current slice (send_port == 0xff)
    //
    // Any routing table can set send_port = 0xff to request runtime-random
    // port selection.  A random byte is mapped to a port index via
    // tb_random_to_port (pre-populated with port = random_id % PORT_NUM,
    // giving a uniform distribution for any PORT_NUM).  Used by VLB routing
    // with random=True to pick a random intermediate ToR per packet.
    // ---------------------------------------------------------------------------
    Random<bit<8>>() rng;
    bit<8> random_id = 0;

    action set_random_port(bit<9> port) {
        send_port = port;
    }

    table tb_random_to_port {
        key = { random_id : exact; }
        actions = { set_random_port; }
        size = 256;
    }

    // ---------------------------------------------------------------------------
    // Generic sentinel: node-indexed forwarding (send_slice == 255)
    //
    // Any routing table can set send_slice = 255 to indicate "forward to the
    // node whose id is in send_port". cal_port_slice_to_node resolves that
    // into a concrete (port, slice, next_tor) based on the transit ToR's
    // current slice and the OCS schedule. Borrowed from Mininet's design
    // (p4/tor/tor.p4:340, utils.py:170).  Used by VLB routing for the
    // intermediate-to-destination hop.
    // ---------------------------------------------------------------------------
    action resolve_node_to_port(bit<8> resolved_port, slice_t resolved_slice,
                                bit<8> resolved_next_tor) {
        send_port  = (bit<9>)resolved_port;
        send_slice = resolved_slice;
        next_hop   = (mac_addr_t)resolved_next_tor;
        alternate_send_port  = (bit<9>)resolved_port;
        alternate_send_slice = resolved_slice;
        alternate_next_hop   = (mac_addr_t)resolved_next_tor;
    }

    table cal_port_slice_to_node {
        key = {
            send_port       : exact;   // dst_node_id (loaded by apply_sr_entry)
            ig_md.cur_slice : exact;
        }
        actions = { resolve_node_to_port; nop; }
        const default_action = nop;
        size = 512;
    }

    // ---------------------------------------------------------------------------
    // Egress port and electrical hop selection
    // ---------------------------------------------------------------------------
    action set_egress_port (bit<9> port) {
        ig_intr_tm_md.ucast_egress_port = port;
    }

    table tb_set_egress_port{
        key = {
            send_port : exact;
        }
        actions = {
            set_egress_port;
            @defaultonly nop;
        }
        const default_action = nop;
        size = 8;
    }

    action set_elec_hop (bit<16> elechop) {
        hdr.optics_l2.elec_layer_ctr = elechop;
    }

    table tb_set_elec_hop{
        key = {
            send_port : exact;
        }
        actions = {
            set_elec_hop;
        }
        size = 8;
    }

    // ---------------------------------------------------------------------------
    // Pkt arrives at the destination server
    // ---------------------------------------------------------------------------
    action set_to_server_port () {
        send_port = to_server_port;
    }

    table tb_check_to_server{
        key = {
            dst_group : exact;
        }
        actions = {
            set_to_server_port;
            @defaultonly nop;
        }
        const default_action = nop;
        size = 8;
    }

    action to_server(mac_addr_t server_mac_addr) {
        hdr.ethernet.dst_addr = server_mac_addr;
    }

    table set_server_mac {
        key = {
            ig_intr_tm_md.ucast_egress_port : exact;
        }
        actions = {
            to_server;
        }
        size = 128;
    }

    Counter<bit<32>, bit<16>>(16, CounterType_t.PACKETS) slice_pkt_ctr;

    apply {
        // hoho_l2 initialization (moved from Ingress pre-call setup)
        hdr.optics_l2.setValid();
        if(hdr.ethernet.ether_type == ETHERTYPE_IPV6) {
            hdr.optics_l2.frame_size = (qdepth_t)hdr.ipv6.payload_len;
        } else if (hdr.ethernet.ether_type == ETHERTYPE_IPV4) {
            hdr.optics_l2.frame_size = (qdepth_t)hdr.ipv4.total_len;
        }

        //normal traffic
        if(hdr.ethernet.ether_type == ETHERTYPE_IPV6 || hdr.ethernet.ether_type == ETHERTYPE_IPV4) {
            hdr.optics_l2.hop_ctr = 0;

            // Rewrite dst MAC based on dst IP so servers don't need static ARP.
            // Runs only at the source ToR (ETHERTYPE_OPTICS/OPTICS_SR packets skip this).
            if (hdr.ipv4.isValid()) {
                tb_ipv4_to_dst_mac.apply();
            } else if (hdr.ipv6.isValid()) {
                tb_ipv6_to_dst_mac.apply();
            }
        } else {
            if (hdr.optics_l2.intended_slice != ig_md.cur_slice) {
                hdr.optics_l2.sync_error_flag = 1;
            }
            hdr.optics_l2.hop_ctr = hdr.optics_l2.hop_ctr + 1;
        }

        tb_adjust_optics_frame_size.apply();

        // Default outgoing ether_type. set_sr_2_hops overrides to OPTICS_SR
        // when the action installs a hop-1 entry into hdr.sr_entry.
        hdr.ethernet.ether_type = ETHERTYPE_OPTICS;

        if(hdr.pktgen_timer.isValid()){
            dst_group = (bit<16>)hdr.pktgen_timer.packet_id % 2;
        } else {
            dst_group = (bit<16>)hdr.ethernet.dst_addr; //for trace
        }

        // Routing decision: three mutually exclusive sources of (send_port,
        // send_slice, next_hop):
        //   1. Transit source-routed packet — read from hdr.sr_entry.
        //   2. Source ToR, source-routing path installed — time_flow_table_source.
        //   3. Source ToR, per-hop routing — time_flow_table_per_hop.
        bit<1> routing_hit = 0;

        if (hdr.sr_entry.isValid()) {
            apply_sr_entry();
            hdr.sr_entry.setInvalid();
            routing_hit = 1;
        } else if (time_flow_table_source.apply().hit) {
            routing_hit = 1;
        } else if (time_flow_table_per_hop.apply().hit) {
            routing_hit = 1;
        }

        if (routing_hit == 1) {

            // --- Generic sentinels (fire for any routing mode) ---
            // Random port: send_port == 0xff → pick a random port, send NOW.
            if (send_port == 0xff) {
                random_id = rng.get();
                tb_random_to_port.apply();
                send_slice = ig_md.cur_slice;
            }
            // Node-indexed forwarding: send_slice == 255 → resolve
            // (send_port=dst_node_id, cur_slice) into concrete (port, slice).
            if (send_slice == 255) {
                cal_port_slice_to_node.apply();
            }

            #define ENQUEUE(P)  \
            if(send_port == P)  \
            {   \
                if(send_slice == ig_md.cur_slice) { \
                    read_p## P ##_max_lossless_qdepth_action();   \
                    p## P ##_count_pkt_size_for_active_queue_action();    \
                } else {    \
                    tb_read_p## P ##_max_qdepth.apply();  \
                    p## P ##_count_pkt_size_for_paused_queue_action();    \
                }   \
                tb_compute_p## P ##_rank.apply(); \
                update_p## P ##_qdepth_action();  \
                \
                ig_intr_tm_md.qid = (bit<7>)p## P ##_rank;    \
            }   \

            FOR_EACH_PORT(ENQUEUE)

            record_hop_count.execute(0);
            hdr.optics_l2.next_tor = next_hop;

            // ADM fallback: if the primary queue can't accept the packet,
            // bounce it to the pre-computed alternate. On the SR path,
            // alternate_* are set equal to the primary by set_sr_*_hops /
            // apply_sr_entry, so this branch is a no-op for SR packets.
            if(enqueue == 1w0) {
                //new implementation of adm: enqueue to the second option.

                ig_intr_tm_md.qid = (bit<7>)alternate_rank;

                send_port = alternate_send_port;
                send_slice = alternate_send_slice;
                hdr.optics_l2.next_tor = alternate_next_hop;

            }

            hdr.optics_l2.intended_slice = send_slice;

            tb_set_egress_port.apply();
            tb_set_elec_hop.apply();

        } else {
            //to servers
            if(tb_check_to_server.apply().hit) {
                slice_pkt_ctr.count(ig_md.cur_slice);
                hdr.udp.checksum = 0;
                tb_set_egress_port.apply();
                hdr.optics_l2.setInvalid();
                hdr.ethernet.ether_type = ETHERTYPE_IPV4;
                set_server_mac.apply();
            }
        }
    }
}
