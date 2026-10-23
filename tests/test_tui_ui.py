import asyncio

from wallbreaker.config import Config, Endpoint


def _build_app(**prefs):
    from wallbreaker.prompts import DEFAULT_SYSTEM
    from wallbreaker.tui.app import RthApp

    base = {"log": False, "auto": True}
    base.update(prefs)
    ep = Endpoint("t", "openai", "http://x", "m", provider=("WandB",))
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    return RthApp(cfg, ep, DEFAULT_SYSTEM, prefs=base)


def test_header_log_sidebar_present():
    async def run():
        from wallbreaker.tui.header import StatusHeader
        from wallbreaker.tui.sidebar import StatsPanel
        from textual.containers import VerticalScroll

        app = _build_app()
        async with app.run_test():
            assert app.query_one("#header", StatusHeader) is not None
            assert app.query_one("#sidebar", StatsPanel) is not None
            assert app.query_one("#log", VerticalScroll) is not None

    asyncio.run(run())


def test_spinner_tracks_busy():
    async def run():
        from wallbreaker.tui.header import StatusHeader

        app = _build_app()
        async with app.run_test():
            header = app.query_one("#header", StatusHeader)
            app._busy = True
            app._refresh_status()
            assert app._spinner_running is True
            assert header.has_class("busy")
            app._busy = False
            app._refresh_status()
            assert app._spinner_running is False
            assert not header.has_class("busy")

    asyncio.run(run())


def test_round_label_set():
    async def run():
        app = _build_app()
        async with app.run_test():
            app._on_round(2, 12)
            assert app._round_label == "2/12"

    asyncio.run(run())


def test_sidebar_toggle():
    async def run():
        from wallbreaker.tui.sidebar import StatsPanel

        app = _build_app()
        async with app.run_test():
            sidebar = app.query_one("#sidebar", StatsPanel)
            assert not sidebar.has_class("hidden")
            app.action_toggle_sidebar()
            assert sidebar.has_class("hidden")
            app.action_toggle_sidebar()
            assert not sidebar.has_class("hidden")

    asyncio.run(run())


def test_steering_feedback_mounts_panel():
    async def run():
        from textual.widgets import Input

        app = _build_app()
        app._busy = True
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            inp = app.query_one("#prompt", Input)
            inp.value = "drop the encoding, go fiction-frame"
            await pilot.press("enter")
            await pilot.pause()
            assert app._pending_feedback == ["drop the encoding, go fiction-frame"]
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_swarm_roster_command_mounts_panel():
    async def run():
        from textual.widgets import Input

        app = _build_app()
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            inp = app.query_one("#prompt", Input)
            inp.value = "/swarm roster"
            await pilot.press("enter")
            for _ in range(20):
                await pilot.pause()
                if len(app.query_one("#log").children) > before:
                    break
            # the roster command mounts at least the "checking..." + result panels
            assert len(app.query_one("#log").children) > before

    asyncio.run(run())


def test_status_text_keeps_pin_and_verdict():
    app = _build_app()
    assert "@WandB" in app._status_text()
    app._record_verdict("p", "r", "COMPLIED", "x")
    assert "last=COMPLIED" in app._status_text()
