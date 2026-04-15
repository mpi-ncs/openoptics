/*
 * Control plane for OpenOptics ToR scheduler on Tofino2.
 * Configures pktgen apps for slice timing (AFC pause/resume) and
 * queue-depth measurement, then drops into the BFRt interactive shell.
 *
 * Build:  make
 * Run:    ./run_oo.sh <duration> <arch>
 *         duration: 1us | 2us | 10us | 25us | 50us | 100us | 500us
 *         arch:     direct | opera | vlb | hoho | hybrid | osa | electrical
 */
#include <stdio.h>
#include <stdlib.h>
#include <stddef.h>
#include <stdint.h>
#include <sched.h>
#include <string.h>
#include <time.h>
#include <assert.h>
#include <unistd.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <pthread.h>
#include <pcap.h>
#include <arpa/inet.h>

#include <bf_rt/bf_rt.hpp>

#ifdef __cplusplus
extern "C"
{
#endif
#include <bf_switchd/bf_switchd.h>
#include <pipe_mgr/pktgen_intf.h>
#include <tofino/pdfixed/pd_conn_mgr.h>
#include <tofino/pdfixed/pd_tm.h>
#include <tofino/pdfixed/pd_common.h>
#ifdef __cplusplus
}
#endif

/* ── Constants ─────────────────────────────────────────────────────────── */

#define ALL_PIPES         0xffff
#define THRIFT_PORT_NUM   7777

#define P4_PROGRAM_NAME   "openoptics_tor"

#define TOTAL_PORTS     32  /* all 100G front-panel ports across 4 pipes */
#define PKT_SIZE        64  /* pktgen packet buffer size in bytes */

/* Pktgen application IDs (must match P4 program expectations) */
#define PKTGEN_APP_PAUSE    1   /* one-shot: pause all queues at slice start */
#define PKTGEN_APP_ROTATION 3   /* periodic: drive slice rotation */
#define PKTGEN_APP_QDEPTH   5   /* periodic: trigger queue-depth register update */

/* Packet buffer offset for the qdepth pktgen app (distinct from pause app at 0) */
#define PKTGEN_BUF_OFFSET_QDEPTH  0x50

/*
 * D_P IDs for all 32 100G front-panel ports across 4 Tofino2 pipes
 * (8 ports per pipe at channel stride 8, offset by 128 * pipe).
 */
const int all_ports[TOTAL_PORTS] = {
	  8,  16,  24,  32,  40,  48,  56,  64,   /* pipe 0 */
	136, 144, 152, 160, 168, 176, 184, 192,   /* pipe 1 */
	264, 272, 280, 288, 296, 304, 312, 320,   /* pipe 2 */
	392, 400, 408, 416, 424, 432, 440, 448,   /* pipe 3 */
};

/* ── Globals ────────────────────────────────────────────────────────────── */

int slice_duration = -1;  /* nanoseconds, derived from CLI arg */
int slice_num = -1;     /* set in main() from argv */
int g_queue_num = -1;      /* overridden in main() from TOR_NUM / PORT_NUM env vars */

p4_pd_sess_hdl_t sess_hdl;
int switchid = 0;
uint64_t pkt_cnt;
uint64_t batch_cnt;
struct p4_pd_pktgen_app_cfg_tof2 app_cfg;

const bfrt::BfRtInfo *bfrtInfo = nullptr;

/* ── Helpers ─────────────────────────────────────────────────────────────── */

/*
 * Build a synthetic 64-byte pktgen packet in a fresh heap buffer.
 * Packet layout (bytes not listed are zeroed by calloc):
 *   [0]     = 0x99       marker byte (identifies pktgen-sourced packets in P4)
 *   [12:13] = 0x30, type  ethertype field; type identifies the pktgen app:
 *                          0x01 = AFC pause/rotation signal
 *                          0x02 = queue-depth update trigger
 */
static char *make_pkt_buf(uint8_t type) {
	char *buf = (char *)calloc(1, PKT_SIZE);
	buf[0]  = 0x99;
	buf[12] = 0x30;
	buf[13] = (char)type;
	return buf;
}

/* ── Initialization ─────────────────────────────────────────────────────── */

void init_bf_switchd(const char *progname) {
	bf_switchd_context_t *switchd_main_ctx = NULL;
	char *install_dir;
	char target_conf_file[256];
	bf_status_t bf_status;

	install_dir = getenv("SDE_INSTALL");
	if (!install_dir) {
		fprintf(stderr, "ERROR: SDE_INSTALL environment variable is not set.\n");
		exit(1);
	}
	snprintf(target_conf_file, sizeof(target_conf_file),
	         "%s/share/p4/targets/tofino2/%s.conf", install_dir, progname);

	switchd_main_ctx = (bf_switchd_context_t *)calloc(1, sizeof(bf_switchd_context_t));
	if (switchd_main_ctx == NULL) {
		printf("ERROR: Failed to allocate memory for switchd context\n");
		return;
	}

	switchd_main_ctx->install_dir          = install_dir;
	switchd_main_ctx->conf_file            = target_conf_file;
	switchd_main_ctx->skip_p4              = false;
	switchd_main_ctx->skip_port_add        = false;
	switchd_main_ctx->running_in_background = true;
	switchd_main_ctx->dev_sts_thread       = true;
	switchd_main_ctx->dev_sts_port         = THRIFT_PORT_NUM;

	bf_status = bf_switchd_lib_init(switchd_main_ctx);
	printf("Initialized bf_switchd, status = %d\n", bf_status);
}

/* Enable Advanced Flow Control (AFC/XOFF) on all OCS-facing queues. */
void init_afc() {
	p4_pd_status_t pd_status;
	bool enable;

	for (int pipe = 0; pipe < 4; pipe++) {
		pd_status = p4_pd_tm_sched_adv_fc_mode_enable_set(0, pipe, true);
		if (pd_status != 0) {
			printf("Error: Failed to enable AFC on pipe %d, status = %d\n", pipe, pd_status);
			return;
		}
		p4_pd_tm_sched_adv_fc_mode_enable_get(0, pipe, &enable);
		printf("Pipe %d: AFC enabled = %d\n", pipe, enable);
	}

	for (int port_id = 0; port_id < TOTAL_PORTS; port_id++) {
		for (int q_id = 0; q_id < g_queue_num; q_id++) {
			p4_pd_tm_sched_q_adv_fc_mode_set(0, all_ports[port_id], q_id,
			                                 PD_TM_SCH_ADV_FC_MODE_XOFF);
		}
	}
	printf("AFC XOFF set on %d ports x %d queues\n", TOTAL_PORTS, g_queue_num);
}

/* Reset queue watermarks so measurements start from a clean baseline. */
void clear_q_wm() {
	p4_pd_status_t pd_status;

	for (int port_id = 0; port_id < TOTAL_PORTS; port_id++) {
		for (int qid = 0; qid < g_queue_num; qid++) {
			pd_status = p4_pd_tm_q_watermark_clear(0, all_ports[port_id], qid);
			if (pd_status != 0) {
				printf("Failed to clear watermark on port %d queue %d\n",
				       all_ports[port_id], qid);
				return;
			}
		}
	}
	printf("Queue watermarks cleared.\n");
}

/* ── Pktgen app setup ───────────────────────────────────────────────────── */

/*
 * App PKTGEN_APP_PAUSE — one-shot: fires (SLICE_NUM/2) packets to assert
 * AFC XOFF on all queues at the start of the first slice.
 */
void set_pause_all_pktgen(p4_pd_dev_target_t pd_dev_tgt) {
	p4_pd_status_t pd_status;

	/* Enable pktgen on port 6 of each pipe (port = 6 + 128 * pipe). */
	for (int pipe_id = 0; pipe_id < 4; pipe_id++) {
		int pktgen_port = 6 + 128 * pipe_id;
		pd_status = p4_pd_pktgen_enable(sess_hdl, 0, pktgen_port);
		if (pd_status != 0) {
			printf("Failed to enable pktgen on port %d, status = %d\n",
			       pktgen_port, pd_status);
			return;
		}
		bool enabled;
		p4_pd_pktgen_enable_state_get(sess_hdl, 0, pktgen_port, &enabled);
		printf("Pktgen port %d enabled = %d\n", pktgen_port, enabled);
	}

	app_cfg.trigger_type          = PD_PKTGEN_TRIGGER_TIMER_ONE_SHOT;
	app_cfg.batch_count           = slice_num / 2 - 1;
	app_cfg.packets_per_batch     = 1;
	app_cfg.timer_nanosec         = 0;
	app_cfg.ibg                   = 0;
	app_cfg.ibg_jitter            = 0;
	app_cfg.ipg                   = 0;
	app_cfg.ipg_jitter            = 0;
	app_cfg.source_port           = 6;
	app_cfg.assigned_chnl_id      = 6;
	app_cfg.increment_source_port = false;
	app_cfg.pkt_buffer_offset     = 0;
	app_cfg.length                = 60;

	char *buf = make_pkt_buf(0x01);
	pd_status = p4_pd_pktgen_write_pkt_buffer(sess_hdl, pd_dev_tgt, 0, PKT_SIZE, (uint8_t *)buf);
	free(buf);
	if (pd_status != 0) {
		printf("Pktgen: Writing packet buffer failed!\n");
		return;
	}

	p4_pd_pktgen_cfg_app_tof2(sess_hdl, pd_dev_tgt, PKTGEN_APP_PAUSE, app_cfg);
	p4_pd_pktgen_app_enable(sess_hdl, pd_dev_tgt, PKTGEN_APP_PAUSE);

	p4_pd_pktgen_get_pkt_counter(sess_hdl, pd_dev_tgt, PKTGEN_APP_PAUSE, &pkt_cnt);
	p4_pd_pktgen_get_batch_counter(sess_hdl, pd_dev_tgt, PKTGEN_APP_PAUSE, &batch_cnt);
	printf("app=%d pkt_cnt=%lu batch_cnt=%lu\n", PKTGEN_APP_PAUSE, pkt_cnt, batch_cnt);
}

/*
 * App PKTGEN_APP_ROTATION — periodic: fires one packet per slice period to
 * drive AFC pause/resume cycling through the schedule rotation.
 * Not used when set_pause_all_pktgen is sufficient (e.g. one-shot mode).
 */
void set_rotation_pktgen(p4_pd_dev_target_t pd_dev_tgt) {
	p4_pd_status_t pd_status;
	bool enabled;
	p4_pd_pktgen_enable_state_get(sess_hdl, 0, 6, &enabled);
	printf("Pktgen port 6 enabled = %d\n", enabled);

	app_cfg.trigger_type          = PD_PKTGEN_TRIGGER_TIMER_PERIODIC;
	app_cfg.batch_count           = 65535; /* max value: run until explicitly stopped */
	app_cfg.packets_per_batch     = 1;
	app_cfg.timer_nanosec         = slice_duration;
	app_cfg.ibg                   = 0;
	app_cfg.ibg_jitter            = 0;
	app_cfg.ipg                   = slice_duration; /* inter-packet gap = one slice period */
	app_cfg.ipg_jitter            = 0;
	app_cfg.source_port           = 6;
	app_cfg.assigned_chnl_id      = 6;
	app_cfg.increment_source_port = false;
	app_cfg.pkt_buffer_offset     = 0;
	app_cfg.length                = 60;

	char *buf = make_pkt_buf(0x01);
	pd_status = p4_pd_pktgen_write_pkt_buffer(sess_hdl, pd_dev_tgt, 0, PKT_SIZE, (uint8_t *)buf);
	free(buf);
	if (pd_status != 0) {
		printf("Pktgen: Writing packet buffer failed!\n");
		return;
	}

	p4_pd_pktgen_cfg_app_tof2(sess_hdl, pd_dev_tgt, PKTGEN_APP_ROTATION, app_cfg);
	p4_pd_pktgen_app_enable(sess_hdl, pd_dev_tgt, PKTGEN_APP_ROTATION);

	p4_pd_pktgen_get_pkt_counter(sess_hdl, pd_dev_tgt, PKTGEN_APP_ROTATION, &pkt_cnt);
	p4_pd_pktgen_get_batch_counter(sess_hdl, pd_dev_tgt, PKTGEN_APP_ROTATION, &batch_cnt);
	printf("app=%d pkt_cnt=%lu batch_cnt=%lu\n", PKTGEN_APP_ROTATION, pkt_cnt, batch_cnt);
}

/*
 * App PKTGEN_APP_QDEPTH — periodic: fires every 50 ns to trigger a P4
 * register read that snapshots current queue depth for HoHo routing decisions.
 */
void set_update_qdepth_pktgen(p4_pd_dev_target_t pd_dev_tgt) {
	p4_pd_status_t pd_status;
	bool enabled;
	p4_pd_pktgen_enable_state_get(sess_hdl, 0, 6, &enabled);
	printf("Pktgen port 6 enabled = %d\n", enabled);

	app_cfg.trigger_type          = PD_PKTGEN_TRIGGER_TIMER_PERIODIC;
	app_cfg.batch_count           = 0;
	app_cfg.packets_per_batch     = 0;
	app_cfg.timer_nanosec         = 50; /* 50 ns polling interval for queue depth */
	app_cfg.ibg                   = 0;
	app_cfg.ibg_jitter            = 0;
	app_cfg.ipg                   = 0;
	app_cfg.ipg_jitter            = 0;
	app_cfg.source_port           = 6;
	app_cfg.assigned_chnl_id      = 6;
	app_cfg.increment_source_port = false;
	app_cfg.pkt_buffer_offset     = PKTGEN_BUF_OFFSET_QDEPTH;
	app_cfg.length                = 60;

	char *buf = make_pkt_buf(0x02);
	pd_status = p4_pd_pktgen_write_pkt_buffer(sess_hdl, pd_dev_tgt,
	                                           PKTGEN_BUF_OFFSET_QDEPTH, PKT_SIZE, (uint8_t *)buf);
	free(buf);
	if (pd_status != 0) {
		printf("Pktgen: Writing packet buffer failed!\n");
		return;
	}

	p4_pd_pktgen_cfg_app_tof2(sess_hdl, pd_dev_tgt, PKTGEN_APP_QDEPTH, app_cfg);
	p4_pd_pktgen_app_enable(sess_hdl, pd_dev_tgt, PKTGEN_APP_QDEPTH);

	p4_pd_pktgen_get_pkt_counter(sess_hdl, pd_dev_tgt, PKTGEN_APP_QDEPTH, &pkt_cnt);
	p4_pd_pktgen_get_batch_counter(sess_hdl, pd_dev_tgt, PKTGEN_APP_QDEPTH, &batch_cnt);
	printf("app=%d pkt_cnt=%lu batch_cnt=%lu\n", PKTGEN_APP_QDEPTH, pkt_cnt, batch_cnt);
}

/* ── Main ────────────────────────────────────────────────────────────────── */

int main(int argc, char **argv) {
	/*
	 * Usage: openoptics_tor <duration> <nb_time_slices> <tor_num> <port_num> [--daemon]
	 *
	 *   duration:       slice length, e.g. "50us"
	 *   nb_time_slices: total time slices in the schedule (from openoptics_config.json)
	 *   tor_num:        number of ToR nodes
	 *   port_num:       OCS uplink ports per ToR
	 *   --daemon:       stay alive in headless mode (for deploy.py bfshell access)
	 */
	int daemon_mode = 0;

	/* Check for --daemon flag anywhere in argv */
	int positional_argc = 0;
	for (int i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--daemon") == 0)
			daemon_mode = 1;
		else
			positional_argc++;
	}

	if (positional_argc != 4) {
		fprintf(stderr, "Usage: %s <duration> <nb_time_slices> <tor_num> <port_num> [--daemon]\n"
		        "  duration:       1us | 2us | 10us | 25us | 50us | 100us | 500us\n"
		        "  nb_time_slices: total time slices in the schedule\n"
		        "  tor_num:        number of ToR nodes\n"
		        "  port_num:       OCS uplink ports per ToR\n"
		        "  --daemon:       headless mode for deploy.py\n",
		        argv[0]);
		return 1;
	}

	/* Collect positional args (skip --daemon) */
	const char *pos[4];
	int pi = 0;
	for (int i = 1; i < argc && pi < 4; i++) {
		if (strcmp(argv[i], "--daemon") != 0)
			pos[pi++] = argv[i];
	}

	/* Parse duration */
	int duration;
	if (sscanf(pos[0], "%d", &duration) != 1) {
		fprintf(stderr, "Error: Invalid duration '%s'\n", pos[0]);
		return 1;
	}
	printf("Slice duration: %d us\n", duration);
	slice_duration = duration * 1000; /* convert µs → ns */

	/* Parse runtime constants */
	slice_num = atoi(pos[1]);
	int tor_num = atoi(pos[2]);
	int port_num = atoi(pos[3]);
	if (slice_num <= 0 || tor_num <= 0 || port_num <= 0) {
		fprintf(stderr, "Error: Invalid runtime params: nb_time_slices=%d tor_num=%d port_num=%d\n",
		        slice_num, tor_num, port_num);
		return 1;
	}
	g_queue_num = tor_num / port_num;
	printf("Runtime config: slice_num=%d, g_queue_num=%d (tor_num=%d, port_num=%d, daemon=%d)\n",
	       slice_num, g_queue_num, tor_num, port_num, daemon_mode);

	bf_dev_target_t dev_tgt;
	p4_pd_dev_target_t pd_dev_tgt;
	dev_tgt.device_id    = 0;
	dev_tgt.dev_pipe_id  = ALL_PIPES;
	pd_dev_tgt.device_id   = 0;
	pd_dev_tgt.dev_pipe_id = ALL_PIPES;

	/* Start the BF switchd and client session */
	init_bf_switchd(P4_PROGRAM_NAME);
	p4_pd_init();
	bf_status_t bf_status = p4_pd_client_init(&sess_hdl);
	if (bf_status == 0) {
		printf("Client initialized successfully.\n");
	} else {
		printf("Client init failed, status = %d\n", bf_status);
	}

	/* Configure AFC. Table population is handled by deploy.py which runs
	 * bfshell via SSH after daemon mode is active. */
	init_afc();

	printf("Starting switch...\n");

	auto &devMgr = bfrt::BfRtDevMgr::getInstance();
	bf_status = devMgr.bfRtInfoGet(dev_tgt.device_id, P4_PROGRAM_NAME, &bfrtInfo);
	bf_sys_assert(bf_status == BF_SUCCESS);

	sleep(2);

	set_pause_all_pktgen(pd_dev_tgt);
	set_update_qdepth_pktgen(pd_dev_tgt);

	sleep(2);
	clear_q_wm();

	if (daemon_mode) {
		printf("Daemon mode active. BFRt gRPC on port 50052.\n");
		while (1) sleep(3600);
	} else {
		const char *sde_install_shell = getenv("SDE_INSTALL");
		char bfshell_cmd[256];
		snprintf(bfshell_cmd, sizeof(bfshell_cmd), "%s/bin/bfshell",
		         sde_install_shell ? sde_install_shell : "");
		system(bfshell_cmd);
	}

	return 0;
}
