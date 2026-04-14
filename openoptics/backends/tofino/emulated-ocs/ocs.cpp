/*
 * Control Plane program for test tofino2 pktgen
 * Compile using following command : make 
 * To Execute, Run: ./run.sh
 *
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
#include <unistd.h>
#include <pcap.h>
#include <arpa/inet.h>

#include <bf_rt/bf_rt.hpp>

//#include "pktgen.cpp"
using namespace std;

#define ALL_PIPES 0xffff

#define PKTGEN_APP_ID_KICKOFF  7
#define PKTGEN_APP_ID_ROTATION 3

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

#define THRIFT_PORT_NUM 7777
#define SIZE 64

int slice_duration = -1;
int slice_num = -1;

p4_pd_sess_hdl_t sess_hdl;
int switchid = 0;
uint64_t pkt_cnt;
uint64_t batch_cnt;
struct p4_pd_pktgen_app_cfg_tof2 app_cfg;

const bfrt::BfRtInfo *bfrtInfo = nullptr;

void init_bf_switchd(const char* progname) {
	bf_switchd_context_t *switchd_main_ctx = NULL;
	char *install_dir;	
	char target_conf_file[100];
	bf_status_t bf_status;
	install_dir = getenv("SDE_INSTALL");
	if (!install_dir) {
		fprintf(stderr, "ERROR: SDE_INSTALL environment variable is not set.\n");
		exit(1);
	}
	sprintf(target_conf_file, "%s/share/p4/targets/tofino2/%s.conf", install_dir, progname);

	/* Allocate memory to hold switchd configuration and state */
	if ((switchd_main_ctx = (bf_switchd_context_t *)calloc(1, sizeof(bf_switchd_context_t))) == NULL) {
		printf("ERROR: Failed to allocate memory for switchd context\n");
		return;
	}

	memset(switchd_main_ctx, 0, sizeof(bf_switchd_context_t));
	switchd_main_ctx->install_dir = install_dir;
	switchd_main_ctx->conf_file = target_conf_file;
	switchd_main_ctx->skip_p4 = false;
	switchd_main_ctx->skip_port_add = false;
	switchd_main_ctx->running_in_background = true;
	switchd_main_ctx->dev_sts_thread = true;
	switchd_main_ctx->dev_sts_port = THRIFT_PORT_NUM;

	bf_status = bf_switchd_lib_init(switchd_main_ctx);
	printf("Initialized bf_switchd, status = %d\n", bf_status);
}

/* Table population is handled by deploy.py via bfshell over SSH. */

static char *make_pkt_buf(uint8_t type) {
	char *b = (char *)calloc(1, SIZE);
	b[0]  = 0x99;
	b[12] = 0x30;
	b[13] = (char)type;
	return b;
}

void set_rotation_pktgen(p4_pd_dev_target_t pd_dev_tgt) {

	p4_pd_status_t pd_status;

	for(int pipe_id = 0; pipe_id < 4; pipe_id++){
    	pd_status = p4_pd_pktgen_enable(sess_hdl, 0, 6 + 128 * pipe_id);
		if (pd_status != 0) {
			printf("Failed to enable pktgen status = %d!!\n", pd_status);
			return;
		}

		bool enable;
		p4_pd_pktgen_enable_state_get(sess_hdl, 0, 6 + 128 * pipe_id, &enable);
		printf("port %d pktgen enable state %d\n", 6 + 128 * pipe_id, enable);
	}

    app_cfg.trigger_type = PD_PKTGEN_TRIGGER_TIMER_PERIODIC;
	//app_cfg.trigger_type = PD_PKTGEN_TRIGGER_TIMER_ONE_SHOT;
	//app_cfg.trigger_type = PD_PKTGEN_TRIGGER_DPRSR;

	app_cfg.batch_count = slice_num / 2 - 1;
    app_cfg.packets_per_batch = 1;
    app_cfg.timer_nanosec = slice_duration;
	app_cfg.ibg = 0;
    app_cfg.ibg_jitter = 0;
	app_cfg.ipg = slice_duration; //slice sending time
    app_cfg.ipg_jitter = 0;
    app_cfg.source_port = 6;
	app_cfg.assigned_chnl_id = 6;
    app_cfg.increment_source_port = false;
    app_cfg.pkt_buffer_offset = 0;
    app_cfg.length = 60;

	char *pkt = make_pkt_buf(0x01);
	pd_status = p4_pd_pktgen_write_pkt_buffer(sess_hdl, pd_dev_tgt, 0, 64, (uint8_t*)pkt);
	free(pkt);
    
    if (pd_status != 0) {
        printf("Pktgen: Writing Packet buffer failed!\n");
        return;
    }

    p4_pd_pktgen_cfg_app_tof2(sess_hdl, pd_dev_tgt, (int)PKTGEN_APP_ID_ROTATION, app_cfg);
    p4_pd_pktgen_app_enable(sess_hdl, pd_dev_tgt, PKTGEN_APP_ID_ROTATION);

	p4_pd_pktgen_get_pkt_counter(sess_hdl, pd_dev_tgt, 3, &pkt_cnt);
	p4_pd_pktgen_get_batch_counter(sess_hdl, pd_dev_tgt, 3, &batch_cnt);
    printf("app=3, pkt_cnt=%lu, batch_cnt=%lu\n", pkt_cnt, batch_cnt);
}

int main(int argc, char **argv) {
	/*
	 * Usage: ocs <duration> <nb_time_slices> [--daemon]
	 *
	 *   duration:       slice length, e.g. "50us"
	 *   nb_time_slices: total time slices in the schedule
	 *   --daemon:       stay alive in headless mode (for deploy.py bfshell access)
	 */
	int daemon_mode = 0;

	/* Check for --daemon flag */
	int positional_argc = 0;
	for (int i = 1; i < argc; i++) {
		if (strcmp(argv[i], "--daemon") == 0)
			daemon_mode = 1;
		else
			positional_argc++;
	}

	if (positional_argc != 2) {
		fprintf(stderr, "Usage: %s <duration> <nb_time_slices> [--daemon]\n"
		        "  duration:       1us | 2us | 10us | 25us | 50us | 100us | 500us\n"
		        "  nb_time_slices: total time slices in the schedule\n"
		        "  --daemon:       headless mode for deploy.py\n",
		        argv[0]);
		return 1;
	}

	/* Collect positional args (skip --daemon) */
	const char *pos[2];
	int pi = 0;
	for (int i = 1; i < argc && pi < 2; i++) {
		if (strcmp(argv[i], "--daemon") != 0)
			pos[pi++] = argv[i];
	}

	int duration;
	if (sscanf(pos[0], "%d", &duration) != 1) {
		fprintf(stderr, "Error: Invalid duration '%s'\n", pos[0]);
		return 1;
	}
	slice_duration = duration * 1000;

	slice_num = atoi(pos[1]);
	if (slice_num <= 0) {
		fprintf(stderr, "Error: Invalid nb_time_slices '%s'\n", pos[1]);
		return 1;
	}

	printf("Slice duration: %d us, slice_num: %d (daemon=%d)\n", duration, slice_num, daemon_mode);

	const char *p4progname = "ocs";
	bf_dev_target_t dev_tgt;
	p4_pd_dev_target_t pd_dev_tgt;
	dev_tgt.device_id    = 0;
	dev_tgt.dev_pipe_id  = ALL_PIPES;
	pd_dev_tgt.device_id   = 0;
	pd_dev_tgt.dev_pipe_id = ALL_PIPES;

	init_bf_switchd(p4progname);

	/* Table population is handled by deploy.py via SSH bfshell. */

	sleep(10);

	set_rotation_pktgen(pd_dev_tgt);

	printf("Starting switch...\n");

	if (daemon_mode) {
		printf("Daemon mode active. BFRt gRPC on port 50052.\n");
		while (1) sleep(3600);
	} else {
		const char *sde_install = getenv("SDE_INSTALL");
		char bfshell_cmd[256];
		if (sde_install != NULL && sde_install[0] != '\0')
			snprintf(bfshell_cmd, sizeof(bfshell_cmd), "%s/bin/bfshell", sde_install);
		else
			snprintf(bfshell_cmd, sizeof(bfshell_cmd), "bfshell");
		system(bfshell_cmd);
	}

	return 0;
}