def usd_to_crypto(usd, price):
    return usd / price


def risk_estimate(pr_win: float, frac_loss: float, frac_gain: float, frac: float = 0.5):
    return frac * kelly_criterion_bin(pr_win, frac_loss, frac_gain)


def kelly_criterion_bin(pr_win: float, frac_loss: float, frac_gain: float) -> float:
    """Binary outcomes"""
    pr_loss = 1 - pr_win
    fraction = pr_win / frac_loss - pr_loss / frac_gain

    return fraction
