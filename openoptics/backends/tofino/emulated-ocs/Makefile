ifndef SDE_INSTALL
$(error SDE_INSTALL is not set)
endif

TARGET_NAME = ocs
ARCH = tofino2

SOURCES = ocs.cpp

CXX = g++

CFLAGS  = -I$(SDE_INSTALL)/include -g

BF_LIBS  = -lbf_switch             \
           -lpi                    \
           -lpi_dummy              \
           -lpifeproto             \
           -lavago                 \
           -ldriver                \
           -lbfutils               \
           -ltarget_sys            \
           -lpython3.10

LDLIBS   = -L$(SDE_INSTALL)/lib -L$(SDE_INSTALL)/lib/$(ARCH)pd
LDLIBS  += -Wl,-rpath-link,$(SDE_INSTALL)/lib
LDLIBS  += -Wl,--disable-new-dtags,-rpath,$(SDE_INSTALL)/lib
LDLIBS  += -Wl,--start-group $(BF_LIBS) -Wl,--end-group
LDLIBS  += -lm -pthread -lpcap -lstdc++ -ldl -levent -ldriver

.PHONY: all clean

all: $(TARGET_NAME)

$(TARGET_NAME):
	$(CXX) -g $(CFLAGS) $(SOURCES) -o $(TARGET_NAME) $(LDLIBS)
	@echo 'Finished building $(TARGET_NAME).'

clean:
	rm -f $(TARGET_NAME)