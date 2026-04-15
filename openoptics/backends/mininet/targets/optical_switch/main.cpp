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
 *
 */

/* Switch instance */

#include <bm/config.h>

#include <bm/OpticalSwitch.h>
#include <bm/bm_runtime/bm_runtime.h>
#include <bm/bm_sim/options_parse.h>
#include <bm/bm_sim/target_parser.h>

#include "optical_switch.h"

namespace {
OpticalSwitch *optical_switch;
}  // namespace

namespace oswitch_runtime {
shared_ptr<OpticalSwitchIf> get_handler(OpticalSwitch *sw);
}  // namespace oswitch_runtime

int
main(int argc, char* argv[]) {
  bm::TargetParserBasicWithDynModules optical_switch_parser;
  optical_switch_parser.add_flag_option(
      "enable-swap",
      "Enable JSON swapping at runtime");
  optical_switch_parser.add_uint_option(
      "drop-port",
      "Choose drop port number (default is 511)");
  optical_switch_parser.add_uint_option(
      "priority-queues",
      "Number of priority queues (default is 1)");
  optical_switch_parser.add_uint_option(
      "nb-time-slices",
      "Number of time slices (default is 1)");
  optical_switch_parser.add_uint_option(
      "time-slice-duration-ms",
      "Time slice duration in ms (default is 0)");

  bm::OptionsParser parser;
  parser.parse(argc, argv, &optical_switch_parser);

  bool enable_swap_flag = false;
  if (optical_switch_parser.get_flag_option("enable-swap", &enable_swap_flag)
      != bm::TargetParserBasic::ReturnCode::SUCCESS) {
    std::exit(1);
  }

  uint32_t drop_port = 0xffffffff;
  {
    auto rc = optical_switch_parser.get_uint_option("drop-port", &drop_port);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      drop_port = OpticalSwitch::default_drop_port;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  uint32_t priority_queues = 0xffffffff;
  {
    auto rc = optical_switch_parser.get_uint_option(
        "priority-queues", &priority_queues);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      priority_queues = OpticalSwitch::default_nb_queues_per_port;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  uint32_t nb_time_slices = 0xffffffff;
  {
    auto rc = optical_switch_parser.get_uint_option(
        "nb-time-slices", &nb_time_slices);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      nb_time_slices = OpticalSwitch::default_nb_time_slices;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  uint32_t time_slice_duration_ms = 0xffffffff;
  {
    auto rc = optical_switch_parser.get_uint_option(
        "time-slice-duration-ms", &time_slice_duration_ms);
    if (rc == bm::TargetParserBasic::ReturnCode::OPTION_NOT_PROVIDED)
      time_slice_duration_ms = OpticalSwitch::default_time_slice_duration_ms;
    else if (rc != bm::TargetParserBasic::ReturnCode::SUCCESS)
      std::exit(1);
  }

  optical_switch = new OpticalSwitch(enable_swap_flag, drop_port,
                                   priority_queues,
                                   nb_time_slices,
                                   time_slice_duration_ms);

  int status = optical_switch->init_from_options_parser(parser);
  if (status != 0) std::exit(status);

  int thrift_port = optical_switch->get_runtime_port();
  bm_runtime::start_server(optical_switch, thrift_port);
  using ::oswitch_runtime::OpticalSwitchIf;
  using ::oswitch_runtime::OpticalSwitchProcessor;
  bm_runtime::add_service<OpticalSwitchIf, OpticalSwitchProcessor>(
      "optical_switch", oswitch_runtime::get_handler(optical_switch));
  optical_switch->start_and_return();

  while (true) std::this_thread::sleep_for(std::chrono::seconds(100));

  return 0;
}
