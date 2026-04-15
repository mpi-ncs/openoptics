#ifndef _REG_P4_
#define _REG_P4_

#include "common/headers.p4"

/////////  per-port queue depth (shared between QueueManager and RoutingDecision)  ////////////
// Size must cover max num_queues per port across current configs.
// 8 is a generous upper bound for opera(4,1), opera(4,2), opera(8,2), opera(8,4).
#ifndef Q_REG_SIZE
#define Q_REG_SIZE 8
#endif

#define REG_DEFINE(P) \
    Register<qdepth_t, bit<8>>(size = Q_REG_SIZE)         p## P ##_qdepth_reg_table;        \
    Register<qdepth_t, bit<8>>(size = 1, initial_value=0) p## P ##_max_lossless_qdepth_reg; \

FOR_EACH_PORT(REG_DEFINE)
#undef REG_DEFINE

#endif /* _REG_P4_ */
