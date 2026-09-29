"""Store screenshots from a web build made with --dart-define=SHOTS=true,
served at http://localhost:8766/shots/ (python -m http.server 8766 in the folder above it).
Needs: pip install playwright, and Edge on the PC (channel msedge, no download).
Run: SHOTS_WORDS="twelve words" python app/tool/shoot.py [appstore-6.7|play-9x16]


Recovers the demo wallet from its twelve words, then walks the screens and
saves PNGs at App Store 6.7" size (1290x2796) and Play 9:16 size (1080x1920).
"""
import asyncio, os, sys, time
from playwright.async_api import async_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "store-screenshots")
WORDS = os.environ["SHOTS_WORDS"]       # twelve words of a demo wallet with a letter or two in it
PASS = os.environ.get("SHOTS_PASS", "demo-pass")
URL = "http://localhost:8766/shots/"

SIZES = {"appstore-6.7": (430, 932, 3), "play-9x16": (360, 640, 3)}


async def shoot(page, name, tag):
    await page.wait_for_timeout(700)
    path = os.path.join(OUT, f"{tag}-{name}.png")
    await page.screenshot(path=path)
    print("saved", path)


async def flutter_text(page, text, timeout=15000):
    """Flutter web renders to canvas; the accessibility tree carries the labels.
    Off-screen list items have no node at all, so scroll until one appears."""
    loc = page.get_by_role("button", name=text)
    for i in range(14):
        try:
            if await loc.count() and await loc.first.is_visible():
                return loc.first
        except Exception:
            pass
        await page.mouse.move(200, 400)
        await page.mouse.wheel(0, 260)
        await page.wait_for_timeout(400)
    await loc.first.wait_for(timeout=timeout)
    return loc.first


async def run_size(pw, tag, w, h, scale):
    browser = await pw.chromium.launch(channel='msedge', headless=True)
    ctx = await browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=scale, is_mobile=True, has_touch=True)
    page = await ctx.new_page()
    await page.goto(URL)
    await page.wait_for_timeout(6000)
    # enable Flutter's semantics tree so get_by_text works
    await page.evaluate("const p=document.querySelector('flt-semantics-placeholder'); p && p.dispatchEvent(new MouseEvent('click',{bubbles:true}))")
    await page.wait_for_timeout(2000)
    await shoot(page, "1-welcome", tag)
    await (await flutter_text(page, "I already have a wallet")).click()
    await page.wait_for_timeout(1500)
    boxes = page.locator("input, textarea")
    await boxes.nth(0).fill(WORDS)
    await boxes.nth(1).fill("Marlow")
    await boxes.nth(2).fill(PASS)
    await boxes.nth(3).fill(PASS)
    await (await flutter_text(page, "Recover wallet")).click()
    for _ in range(40):
        await page.wait_for_timeout(1000)
        if await page.get_by_text("BERRY", exact=False).count() and not await page.get_by_text("Not connected yet").count():
            break
    await page.wait_for_timeout(2500)
    await shoot(page, "2-home", tag)
    await (await flutter_text(page, "Letters")).click()
    for _ in range(30):
        await page.wait_for_timeout(1000)
        if await page.get_by_text("block", exact=False).count():
            break
    await page.wait_for_timeout(1500)
    await shoot(page, "3-letters", tag)
    # open the first letter if there is one
    try:
        first = page.get_by_role("button").filter(has_text="block")
        if await first.count():
            await first.first.click()
            await page.wait_for_timeout(2500)
            await shoot(page, "4-letter", tag)
            await page.go_back()
            await page.wait_for_timeout(1500)
    except Exception as e:
        print("no letter open:", e)
    try:
        await (await flutter_text(page, "Write", timeout=5000)).click()
        await page.wait_for_timeout(2000)
        await shoot(page, "5-compose", tag)
        await page.go_back()
        await page.wait_for_timeout(1500)
    except Exception as e:
        print("compose:", e)
    await page.go_back()
    await page.wait_for_timeout(1500)
    try:
        await (await flutter_text(page, "People", timeout=5000)).click()
        await page.wait_for_timeout(2500)
        await shoot(page, "6-people", tag)
        await page.go_back()
        await page.wait_for_timeout(1500)
    except Exception as e:
        print("people:", e)
    try:
        await (await flutter_text(page, "Receive", timeout=5000)).click()
        await page.wait_for_timeout(2500)
        await shoot(page, "7-receive", tag)
    except Exception as e:
        print("receive:", e)
    await browser.close()


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as pw:
        only = sys.argv[1:]
        for tag, (w, h, s) in SIZES.items():
            if only and tag not in only:
                continue
            await run_size(pw, tag, w, h, s)


asyncio.run(main())
