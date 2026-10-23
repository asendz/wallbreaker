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


def test_log_follows_only_when_pinned_to_bottom():
    """New output follows the view only while the operator is at the bottom.

    Regression: previously every mount called scroll_end unconditionally, so
    scrolling up to read was impossible — each new message yanked back down.
    """

    async def run():
        app = _build_app()
        async with app.run_test() as pilot:
            for i in range(40):
                app._mount(f"message {i}")
            await pilot.pause()
            log = app._log
            assert log.max_scroll_y > 0  # content overflows the viewport

            # operator scrolls up to read history
            log.scroll_home(animate=False)
            await pilot.pause()
            assert log.scroll_y <= 1

            # a new message arrives while scrolled up -> must NOT jump to bottom
            app._mount("incoming while reading")
            await pilot.pause()
            assert log.scroll_y <= 1, f"view jumped to {log.scroll_y}"

            # back at the bottom -> new messages follow again
            log.scroll_end(animate=False)
            await pilot.pause()
            app._mount("incoming at bottom")
            await pilot.pause()
            assert log.scroll_y >= log.max_scroll_y - 2

    asyncio.run(run())
