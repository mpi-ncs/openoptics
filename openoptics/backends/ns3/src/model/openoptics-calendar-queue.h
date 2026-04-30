// Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
// Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
//
// Author: Yiming Lei (ylei@mpi-inf.mpg.de)
//
// License: Creative Commons NC BY SA 4.0
// https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en

#ifndef OPENOPTICS_CALENDAR_QUEUE_H
#define OPENOPTICS_CALENDAR_QUEUE_H

#include <cstddef>
#include <cstdint>
#include <deque>
#include <utility>
#include <vector>

namespace ns3
{
namespace openoptics
{

// Per-slice FIFO queue bank. Items destined for slice s are pushed into
// m_queues[s]; the caller drains m_queues[CurrentSlice()] each boundary.
// A per-item ``port`` cookie travels alongside so the drain side knows
// where to transmit. Only TIME_BASED semantics here — CONTROL_BASED
// (externally advanced active queue) is not yet implemented.
//
// Header-only so the template avoids per-TU instantiation overhead.
template <typename T>
class CalendarQueue
{
  public:
    explicit CalendarQueue(std::size_t nb_slices)
        : m_queues(nb_slices),
          m_drops(0)
    {
    }

    // Push (item, port) onto the queue for `slice`.
    // Returns false if `slice` is out of range; the internal drop counter is
    // incremented for invalid slice ids. Buffer-limit enforcement lives in
    // TorApp because it is a total byte limit across all slices and uplinks.
    bool Enqueue(std::size_t slice, T item, uint32_t port)
    {
        if (slice >= m_queues.size())
        {
            ++m_drops;
            return false;
        }
        auto& q = m_queues[slice];
        q.emplace_back(std::move(item), port);
        return true;
    }

    // Pop the front-most item from queue[`slice`]. Returns false if empty.
    bool Dequeue(std::size_t slice, T* item, uint32_t* port)
    {
        if (slice >= m_queues.size())
        {
            return false;
        }
        auto& q = m_queues[slice];
        if (q.empty())
        {
            return false;
        }
        *item = std::move(q.front().first);
        *port = q.front().second;
        q.pop_front();
        return true;
    }

    // Inspect the head of queue[slice] without removing it. Use Peek
    // -> decide -> Dequeue when a drain may need to leave the head in
    // place (e.g. admission-blocked).
    bool Peek(std::size_t slice, T* item, uint32_t* port) const
    {
        if (slice >= m_queues.size())
        {
            return false;
        }
        const auto& q = m_queues[slice];
        if (q.empty())
        {
            return false;
        }
        *item = q.front().first;
        *port = q.front().second;
        return true;
    }

    // Current occupancy of queue[slice]. Returns 0 for out-of-range slices.
    std::size_t Depth(std::size_t slice) const
    {
        if (slice >= m_queues.size())
        {
            return 0;
        }
        return m_queues[slice].size();
    }

    std::size_t NumSlices() const
    {
        return m_queues.size();
    }

    uint64_t GetDropCount() const
    {
        return m_drops;
    }

    // Reset to empty (drops included). For test setup / teardown only.
    void Clear()
    {
        for (auto& q : m_queues)
        {
            q.clear();
        }
        m_drops = 0;
    }

  private:
    std::vector<std::deque<std::pair<T, uint32_t>>> m_queues;
    uint64_t m_drops;
};

} // namespace openoptics
} // namespace ns3

#endif // OPENOPTICS_CALENDAR_QUEUE_H
