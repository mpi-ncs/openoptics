/* Copyright 2013-present Barefoot Networks, Inc.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/*
 * Antonin Bas (antonin@barefootnetworks.com)
 * Yiming Lei (ylei@mpi-inf.mpg.de)
 */

/* Switch instance */

#include <bm/config.h>

#include <bm/TorSwitch.h>
#include <bm/bm_runtime/bm_runtime.h>
#include <bm/bm_sim/options_parse.h>
#include <bm/bm_sim/target_parser.h>

#include "tor_switch.h"

namespace {
TorSwitch *tor_switch;
}  // namespace

namespace tswitch_runtime {
shared_ptr<TorSwitchIf> get_handler(TorSwitch *sw);
}  // namespace tswitch_runtime

int
main(int argc, char* argv[]) {
  bm::TargetParserBasicWithDynModules tor_switch_parser;
  tor_switch_parser.add_flag_option(
      "enable-swap",
      "Enable JSON swapping at runtime");
  tor_switch_parser.add_uint_option(
      "drop-port",
      "Choose drop port number (default is 511)");
  tor_switch_parser.add_uint_option(
      "priority-queues",
      "Number of priority queues (default is 1)");
  tor_switch_parser.add_uint_option(
      "tor-id",
      "ToR ID (default is 0)");
  tor_switch_parser.add_uint_option(
      "nb-time-slices",
      "Number of time slices (default is 1)");
  tor_switch_parser.add_uint_option(
      "time-slice-duration-ms",
      "Time slice duration in ms (default is 0)");
  tor_switch_parser.add_uint_option(
      "calendar-queue-mode",
      "Calendar queue mode (default is TIME_BASED)");

  bm::OptionsParser parser;
  parser.parse(argc, argv, &tor_switch_parser);

  bool enable_swap_flag = false;
  if (tor_switch_parser.get_flag_option("enable-swap", &enable_swap_flag)
      != bm::TargetParserBasic::ReturnCode::SUCCESS) {
    std::exit(1);
  }

  uint32_t drop_port = 0xffffffff;
  {
    auto rc = tor_switch_parser.get_uint_option("drop-port", &drop_port);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      drop_port = TorSwitch::default_drop_port;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  uint32_t priority_queues = 0xffffffff;
  {
    auto rc = tor_switch_parser.get_uint_option(
        "priority-queues", &priority_queues);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      priority_queues = TorSwitch::default_nb_queues_per_port;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  uint32_t tor_id = 0xffffffff;
  if (tor_switch_parser.get_uint_option("tor-id", &tor_id)
      != bm::TargetParserBasic::ReturnCode::SUCCESS) {
    std::exit(1);
  }

  uint32_t nb_time_slices = 0xffffffff;
  {
    auto rc = tor_switch_parser.get_uint_option(
        "nb-time-slices", &nb_time_slices);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      nb_time_slices = TorSwitch::default_nb_time_slices;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  uint32_t time_slice_duration_ms = 0xffffffff;
  {
    auto rc = tor_switch_parser.get_uint_option(
        "time-slice-duration-ms", &time_slice_duration_ms);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      time_slice_duration_ms = TorSwitch::default_time_slice_duration_ms;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  TorSwitch::CalendarQueueMode calendar_queue_mode;
  {
    uint32_t mode_int;
    auto rc = tor_switch_parser.get_uint_option(
        "calendar-queue-mode", &mode_int);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      calendar_queue_mode = TorSwitch::default_calendar_queue_mode;
    else if (rc == bm::TargetParserBasic::ReturnCode::SUCCESS){
      if (mode_int == 0)
        calendar_queue_mode = TorSwitch::CalendarQueueMode::TIME_BASED;
      else if (mode_int == 1)
        calendar_queue_mode = TorSwitch::CalendarQueueMode::CONTROL_BASED;
      else {
        std::cerr << "Invalid value for calendar-queue-mode: " << mode_int << std::endl;
        std::exit(1);
      }
    }
    else
      std::exit(1);
  }


  tor_switch = new TorSwitch(
    enable_swap_flag, drop_port,
    priority_queues,
    tor_id,
    nb_time_slices,
    time_slice_duration_ms,
    calendar_queue_mode
  );

  int status = tor_switch->init_from_options_parser(parser);
  if (status != 0) std::exit(status);

  int thrift_port = tor_switch->get_runtime_port();
  bm_runtime::start_server(tor_switch, thrift_port);
  using ::tswitch_runtime::TorSwitchIf;
  using ::tswitch_runtime::TorSwitchProcessor;
  bm_runtime::add_service<TorSwitchIf, TorSwitchProcessor>(
      "tor_switch", tswitch_runtime::get_handler(tor_switch));
  tor_switch->start_and_return();

  while (true) std::this_thread::sleep_for(std::chrono::seconds(100));

  return 0;
}
