"""Run as: python -m worker.main worker|scheduler|importer [--once]."""
import argparse
import json
import logging
import signal
import threading

from backend.app.db import engine
from .services import import_incoming, process_one, recover_stalled, scheduler_tick
from .jobs import periodic_jobs


def main():
    parser = argparse.ArgumentParser(description="Quality QR durable background services")
    parser.add_argument("mode", choices=("worker", "scheduler", "importer"))
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        try:
            if args.mode == "worker":
                recovered = recover_stalled(engine)
                worked = process_one(engine)
                if recovered or worked:
                    logging.info("worker recovered=%d processed=%s", recovered, worked)
                wait = 0.1 if worked else 2
            elif args.mode == "scheduler":
                logging.info("scheduler queued=%d", scheduler_tick(engine))
                result = periodic_jobs(engine)
                if any(result.values()):
                    logging.info("jobs %s", json.dumps(result))
                wait = 15
            else:
                for result in import_incoming(engine):
                    logging.info("import %s", json.dumps(result, ensure_ascii=False))
                wait = 5
        except Exception as exc:
            logging.exception("background iteration failed; durable work retained")
            try:
                import traceback
                from backend.app.system import record_error
                record_error('worker', f'{args.mode}: {type(exc).__name__}: {exc}', traceback.format_exc())
            except Exception:
                pass
            wait = 5
        if args.once:
            break
        stop.wait(wait)


if __name__ == "__main__":
    main()
