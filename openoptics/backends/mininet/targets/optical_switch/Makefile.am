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

THRIFT_IDL = $(srcdir)/thrift/optical_switch.thrift

noinst_LTLIBRARIES = libtorswitch.la
lib_LTLIBRARIES = libtorswitch_runner.la

libtorswitch_la_SOURCES = \
optical_switch.cpp \
optical_switch.h \
primitives.cpp \
register_access.h

libtorswitch_runner_la_SOURCES = \
runner.cpp

nobase_include_HEADERS = bm/optical_switch/runner.h

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

optical_switch_thrift_py_files = \
gen-py/oswitch_runtime/constants.py \
gen-py/oswitch_runtime/__init__.py \
gen-py/oswitch_runtime/OpticalSwitch.py \
gen-py/oswitch_runtime/ttypes.py
optical_switch_thrift_files = \
gen-cpp/bm/optical_switch_constants.cpp \
gen-cpp/bm/optical_switch_constants.h \
gen-cpp/bm/OpticalSwitch.cpp \
gen-cpp/bm/OpticalSwitch.h \
gen-cpp/bm/optical_switch_types.cpp \
gen-cpp/bm/optical_switch_types.h

BUILT_SOURCES = $(optical_switch_thrift_files) $(optical_switch_thrift_py_files)

sswitchpydir = $(pythondir)/oswitch_runtime
nodist_sswitchpy_PYTHON = $(optical_switch_thrift_py_files)

python_PYTHON = oswitch_CLI.py

# See
# http://www.gnu.org/software/autoconf/manual/autoconf-2.69/html_node/Installation-Directory-Variables.html
edit = sed \
	-e 's|@pythondir[@]|$(pythondir)|g'

optical_switch_CLI: Makefile
	rm -f $@ $@.tmp
	$(edit) $(srcdir)/$@.in >$@.tmp
	chmod +x $@.tmp
	chmod a-w $@.tmp
	mv $@.tmp $@

optical_switch_CLI: optical_switch_CLI.in

EXTRA_DIST = \
optical_switch_CLI.in \
oswitch_CLI

bin_SCRIPTS = \
optical_switch_CLI

AM_CPPFLAGS += \
-I$(srcdir)/thrift/src/ \
-I$(builddir)/gen-cpp

libtorswitch_la_SOURCES += thrift/src/OpticalSwitch_server.cpp

bin_PROGRAMS = optical_switch

optical_switch_LDADD = \
$(top_builddir)/src/bm_runtime/libbmruntime.la \
$(top_builddir)/thrift_src/libruntimestubs.la \
libtorswitch.la \
libtorswitch_thrift.la

optical_switch_SOURCES = main.cpp
optical_switch_LDFLAGS =
if ENABLE_MODULES
optical_switch_LDFLAGS += -rdynamic
endif

lib_LTLIBRARIES += libtorswitch_thrift.la

nodist_libtorswitch_thrift_la_SOURCES = \
$(optical_switch_thrift_files)

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
	touch $(optical_switch_thrift_files)
	if mkdir $(srcdir)/oswitch_runtime.test 2>/dev/null; then \
	  rm -rf $(srcdir)/oswitch_runtime/; \
	  cp -r $(builddir)/gen-py/oswitch_runtime/ $(srcdir)/; \
	  rm -rf $(srcdir)/oswitch_runtime.test; else :; \
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
gen-cpp/bm/optical_switch_constants.h \
gen-cpp/bm/OpticalSwitch.h \
gen-cpp/bm/optical_switch_types.h

CLEANFILES = $(BUILT_SOURCES) \
thrift_files.ts \
gen-cpp/bm/OpticalSwitch_server.skeleton.cpp \
$(bin_SCRIPTS)

# I used to do a rm on gen-cpp, but it was removing a .deps directory, instead I
# am adding the skeleton file to CLEANFILES
clean-local:
	rm -rf gen-py

endif  # COND_THRIFT
