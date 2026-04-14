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

//! @file queueing.h
//! This file contains convenience classes that can be useful for targets that
//! wish to queue packets at some point during processing (for example, between
//! an ingress pipeline and an egress pipeline, as is the case for the standard
//! simple switch target). We realized that if one decided to use the bm::Queue
//! class (in queue.h) to achieve this, quite a lot of work was required, even
//! for the standard, basic case: one queue per egress port, with a limited
//! number of threads processing all the queues.

#include <algorithm>  // for std::max
#include <chrono>
#include <condition_variable>
#include <deque>
#include <mutex>
#include <queue>
#include <tuple>  // for std::forward_as_tuple
#include <unordered_map>
#include <utility>  // for std::piecewise_construct
#include <vector>

// These queueing implementations used to have one lock for each worker, which
// meant that as long as 2 queues were assigned to different workers, they could
// operate (push / pop) in parallel. Since we added support for arbitrary port
// ids (and the port id is used as the queue id), we no longer have a reasonable
// upper bound on the maximum possible port id at construction time and we can
// no longer use a vector indexed by the queue id to store queue
// information. Each push / pop operation can potentially insert a new entry
// into the map. In order to accomodate for this, we had to start using a single
// lock, shared by all the workers. It's unlikely that contention for this lock
// will be a bottleneck.

//! One of the most basic queueing block possible. Supports an arbitrary number
//! of logical queues (identified by arbitrary integer ids). Lets you choose (at
//! runtime) the number of worker threads that will be reading from these
//! queues. I write "logical queues" because the implementation actually uses as
//! many physical queues as there are worker threads. However, each logical
//! queue still has its own maximum capacity.  As of now, the behavior is
//! blocking for both read (pop_back()) and write (push_front()), but we may
//! offer additional options if there is interest expressed in the future.
//!
//! Template parameter `T` is the type (has to be movable) of the objects that
//! will be stored in the queues. Template parameter `FMap` is a callable object
//! that has to be able to map every logical queue id to a worker id. The
//! following is a good example of functor that meets the requirements:
//! @code
//! struct WorkerMapper {
//!   WorkerMapper(size_t nb_workers)
//!       : nb_workers(nb_workers) { }
//!
//!   size_t operator()(size_t queue_id) const {
//!     return queue_id % nb_workers;
//!   }
//!
//!   size_t nb_workers;
//! };
//! @endcode

template <typename T>
class CalendarQueue {
  using MutexType = std::mutex;
  using LockType = std::unique_lock<MutexType>;

 public:
  //! \p capacity is the number of objects that each logical queue
  //! can hold. 
  CalendarQueue(size_t capacity, size_t nb_calendar_queues)
      : capacity(capacity),
        nb_calendar_queues(nb_calendar_queues),
        q_not_empty(new std::condition_variable[nb_calendar_queues]),
        calendar_queues(new MyQ[nb_calendar_queues]) { }

  //! Makes a copy of \p item and pushes it to the front of the calendar queue
  //! with \p port_id  \p queue_id.
  //! Return -1 if drop because of out of buffer
  size_t push_front(size_t port_id, size_t queue_id, const T &item) {
    LockType lock(mutex);
    auto &q_info = get_queue(port_id, queue_id);
    if (q_info.size >= capacity) {
      return -1;
    }
    calendar_queues[queue_id].emplace_front(item, port_id);
    q_info.size++;
    overal_qdepth++;
    q_not_empty[queue_id].notify_one();
    return 0;
  }

  //! Moves \p item to the front of the logical queue with id \p queue_id.
  //! Return -1 if drop because of out of buffer
  bool push_front(size_t port_id, size_t queue_id, T &&item) {
    LockType lock(mutex);
    auto &q_info = get_queue(port_id, queue_id);
    if (q_info.size >= capacity) {
      return false;
    }
    calendar_queues[queue_id].emplace_front(std::move(item), port_id);
    q_info.size++;
    overal_qdepth++;
    q_not_empty[queue_id].notify_one();
    return true;
  }

  //! Retrieves the oldest element for the worker thread indentified by \p
  //! worker_id and moves it to \p pItem. The id of the logical queue which
  //! contained this element is copied to \p queue_id. As a remainder, the
  //! `map_to_worker` argument provided when constructing the class is used to
  //! map every queue id to the corresponding worker id. Therefore, if an
  //! element `E` was pushed to queue `queue_id`, you need to use the worker id
  //! `map_to_worker(queue_id)` to retrieve it with this function.
  bool pop_back(size_t queue_id, size_t *port_id, T *pItem) {
    LockType lock(mutex);
    auto &queue = calendar_queues[queue_id];
    //while (queue.size() == 0) {
    //  q_not_empty[queue_id].wait(lock);
    //}
    if (queue.size() == 0) {
      return false;
    }
    *port_id = queue.back().port_id;
    *pItem = std::move(queue.back().e);
    queue.pop_back();
    auto &q_info = get_queue_or_throw(*port_id, queue_id);
    q_info.size--;
    overal_qdepth--;

    return true;
  }

  //! Get the occupancy of the logical queue with id \p queue_id.
  size_t size(size_t port_id, size_t queue_id) const {
    LockType lock(mutex);
    auto it = port_q_info.find({port_id, queue_id});
    if (it == port_q_info.end()) return 0;
    auto &q_info = it->second;
    return q_info.size;
  }

  size_t get_q_size(size_t port_id, size_t queue_id) const {
    return size(port_id, queue_id);
  }
  
  size_t get_overall_size() const {
    LockType lock(mutex);
    return overal_qdepth;
  }

  std::vector<std::tuple<size_t, size_t, size_t>> get_port_queue_size() const {
      std::vector<std::tuple<size_t, size_t, size_t>> p_q_size;
    LockType lock(mutex);
    for (auto it = port_q_info.begin(); it != port_q_info.end(); ++it) {
        size_t port_id = it->first.first;
        size_t queue_id = it->first.second;
        size_t q_size = it->second.size;

        p_q_size.push_back(std::make_tuple(port_id, queue_id, q_size));
    }
      return p_q_size;
  }


  size_t set_active_queue(size_t qid) {
    LockType lock(mutex);
    active_calendar_queue = qid;
    return 0;
  }

  size_t get_active_queue() const {
    LockType lock(mutex);
    return active_calendar_queue;
  }

  //! Deleted copy constructor
  CalendarQueue(const CalendarQueue &) = delete;
  //! Deleted copy assignment operator
  CalendarQueue &operator =(const CalendarQueue &) = delete;

  //! Deleted move constructor
  CalendarQueue(CalendarQueue &&) = delete;
  //! Deleted move assignment operator
  CalendarQueue &&operator =(CalendarQueue &&) = delete;

 private:
  struct QE {
    QE(T e, size_t port_id)
        : e(std::move(e)), port_id(port_id) { }

    T e;
    size_t port_id;
  };

  using MyQ = std::deque<QE>;

  struct QueueInfo {
    explicit QueueInfo(): size(0) { }
    size_t size;
  };

  QueueInfo &get_queue(size_t port_id, size_t queue_id) {
    auto it = port_q_info.find({port_id,queue_id});
    if (it != port_q_info.end()) return it->second;
    // piecewise_construct because QueueInfo is not copyable (because of mutex
    // member)
    auto p = port_q_info.emplace(std::make_pair(port_id,queue_id), QueueInfo());
    return p.first->second;
  }

  const QueueInfo &get_queue_or_throw(size_t port_id, size_t queue_id) const {
    return port_q_info.at({port_id,queue_id});
  }

  QueueInfo &get_queue_or_throw(size_t port_id, size_t queue_id) {
    return port_q_info.at({port_id,queue_id});
  }

  struct PairHash {
    template <class T1, class T2>
    std::size_t operator() (const std::pair<T1, T2>& p) const {
        auto h1 = std::hash<T1>{}(p.first);
        auto h2 = std::hash<T2>{}(p.second);
        return h1 ^ (h2 << 1);
    }
  };

  struct PairEqual {
      template <class T1, class T2>
      bool operator() (const std::pair<T1, T2>& lhs, const std::pair<T1, T2>& rhs) const {
          return lhs.first == rhs.first && lhs.second == rhs.second;
      }
  };

  mutable MutexType mutex{};
  size_t capacity;  // default capacity
  size_t overal_qdepth;
  size_t nb_calendar_queues;
  size_t active_calendar_queue = nb_calendar_queues;
  std::unordered_map<std::pair<size_t, size_t>, QueueInfo, PairHash, PairEqual> port_q_info;

  std::condition_variable *q_not_empty;
  MyQ *calendar_queues;
};