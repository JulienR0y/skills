"""Timeline marks: the operator stamps each beat while the recorder runs; the director reads them back as take times.

usage: python mark.py <label words>                    # appends "<unix ms>,<label>" to marks.csv
       python mark.py --take take.mp4 [take-002.mp4]   # each mark's time in the take(s) that cover it
       python mark.py --clicks take.mp4                # each click in the take, from its cursor log
       --file <marks.csv> picks another marks file (default: marks.csv in the current folder).
"""
import argparse
import csv
import time
from pathlib import Path

from sidecar import start_time


def add(path, label):
    with open(path, "a", encoding="utf-8", newline="\n") as f:
        f.write(f"{int(time.time() * 1000)},{label.replace(',', ' ')}\n")
    print(f"marked: {label}")


def read_marks(path):
    with open(path, encoding="utf-8") as f:
        return [(int(ms) / 1000, label) for ms, label in csv.reader(f)]


def locate(at, starts):
    """Where unix time `at` falls: the latest take started by then, as "<take> @ <seconds into it> s"."""
    take = [(s, t) for s, t in starts if s <= at]
    return f"{Path(take[-1][1]).name} @ {at - take[-1][0]:7.1f} s" if take else "before every take"


def show(marks, starts):
    for at, label in marks:
        print(f"{time.strftime('%H:%M:%S', time.localtime(at))}  {locate(at, starts)}  {label}")


def presses(rows):
    """(take seconds, x, y) of each left-button press in cursor-log rows (dicts with ms, x, y, down)."""
    found, was_down = [], False
    for r in rows:
        down = r["down"] == "1"
        if down and not was_down:
            found.append((int(r["ms"]) / 1000, int(r["x"]), int(r["y"])))
        was_down = down
    return found


def show_clicks(take):
    with open(f"{take}.cursor.csv", encoding="utf-8") as f:
        for t, x, y in presses(csv.DictReader(f)):
            print(f"{t:7.1f} s  click at {x},{y}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("label", nargs="*")
    ap.add_argument("--take", nargs="+", help="show marks as times in these takes")
    ap.add_argument("--clicks", help="list the clicks in this take")
    ap.add_argument("--file", default="marks.csv")
    args = ap.parse_args()
    if args.take:
        show(read_marks(args.file), sorted((start_time(t), t) for t in args.take if start_time(t) is not None))
    elif args.clicks:
        show_clicks(args.clicks)
    elif args.label:
        add(args.file, " ".join(args.label))
    else:
        ap.error("give a label, --take or --clicks")


if __name__ == "__main__":
    main()
