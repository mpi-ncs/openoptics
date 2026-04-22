# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# License: Creative Commons NC BY SA 4.0
import asyncio
import threading
import time
import unittest

from openoptics.dashboard.broker import EventBroker
from openoptics.dashboard.events import MetricSample


def _sample(i: int) -> MetricSample:
    return MetricSample(
        metric_type="queue_depth",
        device="tor0",
        value=float(i),
        timestep=i,
        timestamp=time.time(),
        epoch_id=1,
        labels={"port": 0, "queue": 0},
    )


class TestBrokerFanOut(unittest.IsolatedAsyncioTestCase):
    async def test_publish_fans_out_to_all_subscribers(self):
        broker = EventBroker()
        with broker.subscribe() as q1, broker.subscribe() as q2:
            await broker.publish(_sample(0))
            await broker.publish(_sample(1))
            self.assertEqual((await q1.get()).timestep, 0)
            self.assertEqual((await q2.get()).timestep, 0)
            self.assertEqual((await q1.get()).timestep, 1)
            self.assertEqual((await q2.get()).timestep, 1)

    async def test_unsubscribe_on_exit(self):
        broker = EventBroker()
        with broker.subscribe():
            self.assertEqual(len(broker._subscribers), 1)
        self.assertEqual(len(broker._subscribers), 0)

    async def test_overflow_drops_oldest(self):
        broker = EventBroker(queue_size=2)
        with broker.subscribe() as q:
            for i in range(5):
                await broker.publish(_sample(i))
            # Queue size is 2 → only the newest two survive.
            self.assertEqual(q.qsize(), 2)
            self.assertEqual((await q.get()).timestep, 3)
            self.assertEqual((await q.get()).timestep, 4)

    async def test_publish_threadsafe_from_other_thread(self):
        broker = EventBroker()
        broker.bind_loop(asyncio.get_event_loop())

        with broker.subscribe() as q:
            def publisher():
                time.sleep(0.01)
                broker.publish_threadsafe(_sample(42))

            t = threading.Thread(target=publisher)
            t.start()
            sample = await asyncio.wait_for(q.get(), timeout=1.0)
            t.join()
            self.assertEqual(sample.timestep, 42)


if __name__ == "__main__":
    unittest.main()
