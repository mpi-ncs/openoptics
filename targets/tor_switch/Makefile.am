if COND_NANOMSG
MAYBE_TESTS = tests
endif

if COND_PI
AM_CPPFLAGS += \
-DWITH_PI \
-I$(top_srcdir)/PI
PI_LIB = $(top_builddir)/PI/libbmpi.la
else
PI_LIB =
endif

SUBDIRS = . $(MAYBE_TESTS)

THRIFT_IDL = $(srcdir)/thrift/tor_switch.thrift

noinst_LTLIBRARIES = libtorswitch.la
lib_LTLIBRARIES = libtorswitch_runner.la

libtorswitch_la_SOURCES = \
tor_switch.cpp \
tor_switch.h \
primitives.cpp \
register_access.h

libtorswitch_runner_la_SOURCES = \
runner.cpp

nobase_include_HEADERS = bm/tor_switch/runner.h

libtorswitch_la_LIBADD = \
$(top_builddir)/src/bm_sim/libbmsim.la \
$(top_builddir)/src/bf_lpm_trie/libbflpmtrie.la \
$(top_builddir)/src/BMI/libbmi.la \
$(top_builddir)/third_party/jsoncpp/libjson.la \
-lboost_system $(THRIFT_LIB) -lboost_program_options -lboost_filesystem

libtorswitch_runner_la_LIBADD = \
$(PI_LIB) \
libtorswitch.la

if COND_THRIFT

tor_switch_thrift_py_files = \
gen-py/tswitch_runtime/constants.py \
gen-py/tswitch_runtime/__init__.py \
gen-py/tswitch_runtime/TorSwitch.py \
gen-py/tswitch_runtime/ttypes.py
tor_switch_thrift_files = \
gen-cpp/bm/tor_switch_constants.cpp \
gen-cpp/bm/tor_switch_constants.h \
gen-cpp/bm/TorSwitch.cpp \
gen-cpp/bm/TorSwitch.h \
gen-cpp/bm/tor_switch_types.cpp \
gen-cpp/bm/tor_switch_types.h

BUILT_SOURCES = $(tor_switch_thrift_files) $(tor_switch_thrift_py_files)

sswitchpydir = $(pythondir)/tswitch_runtime
nodist_sswitchpy_PYTHON = $(tor_switch_thrift_py_files)

python_PYTHON = tswitch_CLI.py

# See
# http://www.gnu.org/software/autoconf/manual/autoconf-2.69/html_node/Installation-Directory-Variables.html
edit = sed \
	-e 's|@pythondir[@]|$(pythondir)|g'

tor_switch_CLI: Makefile
	rm -f $@ $@.tmp
	$(edit) $(srcdir)/$@.in >$@.tmp
	chmod +x $@.tmp
	chmod a-w $@.tmp
	mv $@.tmp $@

tor_switch_CLI: tor_switch_CLI.in

EXTRA_DIST = \
tor_switch_CLI.in \
tswitch_CLI

bin_SCRIPTS = \
tor_switch_CLI

AM_CPPFLAGS += \
-I$(srcdir)/thrift/src/ \
-I$(builddir)/gen-cpp

libtorswitch_la_SOURCES += thrift/src/TorSwitch_server.cpp

bin_PROGRAMS = tor_switch

tor_switch_LDADD = \
$(top_builddir)/src/bm_runtime/libbmruntime.la \
$(top_builddir)/thrift_src/libruntimestubs.la \
libtorswitch.la \
libtorswitch_thrift.la

tor_switch_SOURCES = main.cpp
tor_switch_LDFLAGS =
if ENABLE_MODULES
tor_switch_LDFLAGS += -rdynamic
endif

lib_LTLIBRARIES += libtorswitch_thrift.la

nodist_libtorswitch_thrift_la_SOURCES = \
$(tor_switch_thrift_files)

# See http://www.gnu.org/software/automake/manual/html_node/Multiple-Outputs.html

EXTRA_DIST += $(THRIFT_IDL)

# We copy the generated Python code to srcdir/ if we have permissions (i.e. not
# for 'make distcheck'). This is to ensure we can run the CLI easily. Maybe I
# will think of a better solution later.
thrift_files.ts: $(THRIFT_IDL)
	@rm -f thrift_files.tmp
	@touch thrift_files.tmp
	@mkdir -p $(builddir)/gen-cpp/bm
	$(THRIFT) -out $(builddir)/gen-cpp/bm --gen cpp -r $(THRIFT_IDL)
	$(THRIFT) -o $(builddir) --gen py -r $(THRIFT_IDL)
	touch $(tor_switch_thrift_files)
	if mkdir $(srcdir)/tswitch_runtime.test 2>/dev/null; then \
	  rm -rf $(srcdir)/tswitch_runtime/; \
	  cp -r $(builddir)/gen-py/tswitch_runtime/ $(srcdir)/; \
	  rm -rf $(srcdir)/tswitch_runtime.test; else :; \
        fi
	@mv -f thrift_files.tmp $@

$(BUILT_SOURCES): thrift_files.ts
## Recover from the removal of $@
	@if test -f $@; then :; else \
	  trap 'rm -rf thrift_files.lock thrift_files.ts' 1 2 13 15; \
## mkdir is a portable test-and-set
	if mkdir thrift_files.lock 2>/dev/null; then \
## This code is being executed by the first process.
	  rm -f thrift_files.ts; \
	  $(MAKE) $(AM_MAKEFLAGS) thrift_files.ts; \
	  result=$$?; rm -rf thrift_files.lock; exit $$result; \
	else \
## This code is being executed by the follower processes.
## Wait until the first process is done.
	  while test -d thrift_files.lock; do sleep 1; done; \
## Succeed if and only if the first process succeeded.
	    test -f thrift_files.ts; \
	  fi; \
	fi

nodist_pkginclude_HEADERS = \
gen-cpp/bm/tor_switch_constants.h \
gen-cpp/bm/TorSwitch.h \
gen-cpp/bm/tor_switch_types.h

CLEANFILES = $(BUILT_SOURCES) \
thrift_files.ts \
gen-cpp/bm/TorSwitch_server.skeleton.cpp \
$(bin_SCRIPTS)

# I used to do a rm on gen-cpp, but it was removing a .deps directory, instead I
# am adding the skeleton file to CLEANFILES
clean-local:
	rm -rf gen-py

endif  # COND_THRIFT
