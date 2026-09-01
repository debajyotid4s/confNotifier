import random
import time


def _human_like_scroll(page) -> None:
    """Inject small randomized scroll to mimic human behavior."""
    steps = random.randint(3, 5)
    for _ in range(steps):
        try:
            page.evaluate(
                "window.scrollTo({top: Math.random()*500, behavior: 'smooth'})"
            )
            time.sleep(random.uniform(0.3, 0.8))
        except Exception:
            break
