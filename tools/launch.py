"""What MapleTracker.exe runs (the package's own __main__ uses relative imports, which a
packaged app can't start from).

There's no console window, so a crash would vanish without a trace: it's shown in a message
box and written to data/crash.log instead."""
import traceback


def run():
    try:
        from maple_tracker.app import main
        main()
    except Exception:
        report = traceback.format_exc()
        try:
            from maple_tracker import config
            config.DATA.mkdir(parents=True, exist_ok=True)
            (config.DATA / "crash.log").write_text(report, "utf-8")
            where = f"\n\nThe details are in {config.DATA / 'crash.log'}"
        except Exception:
            where = ""
        import tkinter
        from tkinter import messagebox
        root = tkinter.Tk()
        root.withdraw()
        messagebox.showerror("Maple Tracker", f"Maple Tracker stopped because of an error.{where}"
                             f"\n\n{report.strip().splitlines()[-1]}")
        root.destroy()


if __name__ == "__main__":
    run()
